"""Attach to a live Python 3.14 process via ``sys.remote_exec``.

This module provides two pieces used by the attach-by-PID roadmap:

1. A local helper process that calls ``sys.remote_exec(pid, script_path)``.
2. A bootstrap entry point executed inside the target interpreter that starts
   Dapper's existing IPC command loop and installs tracing into live threads.
"""

from __future__ import annotations

import argparse
import atexit
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from typing import Any
from typing import cast
import uuid

from dapper.launcher import debug_launcher
from dapper.shared import debug_shared

logger = logging.getLogger(__name__)

_ATTACH_LOCK = threading.RLock()
_ATTACH_ACTIVE = threading.Event()
_ATTACH_DIAGNOSTIC_PREFIX = "DAPPER_ATTACH_BY_PID_DIAGNOSTIC "


@dataclass(frozen=True)
class AttachByPidDiagnostic:
    """Structured diagnostics emitted by the local attach helper."""

    code: str
    message: str
    detail: str | None = None
    hint: str | None = None

    def to_dict(self) -> dict[str, str]:
        data = {
            "code": self.code,
            "message": self.message,
        }
        if self.detail:
            data["detail"] = self.detail
        if self.hint:
            data["hint"] = self.hint
        return data


@dataclass(frozen=True)
class AttachByPidPayload:
    """Serialized payload passed through ``sys.remote_exec``."""

    process_id: int
    ipc_transport: str
    ipc_host: str | None = None
    ipc_port: int | None = None
    ipc_path: str | None = None
    ipc_pipe_name: str | None = None
    session_id: str | None = None
    just_my_code: bool = True
    strict_expression_watch_policy: bool = False
    dapper_root: str | None = None

    def to_remote_exec_dict(self) -> dict[str, Any]:
        return {
            "processId": self.process_id,
            "ipcTransport": self.ipc_transport,
            "ipcHost": self.ipc_host,
            "ipcPort": self.ipc_port,
            "ipcPath": self.ipc_path,
            "ipcPipeName": self.ipc_pipe_name,
            "sessionId": self.session_id,
            "justMyCode": self.just_my_code,
            "strictExpressionWatchPolicy": self.strict_expression_watch_policy,
            "dapperRoot": self.dapper_root,
        }

    @classmethod
    def from_remote_exec_dict(cls, payload: dict[str, Any]) -> AttachByPidPayload:
        return cls(
            process_id=int(payload["processId"]),
            ipc_transport=str(payload["ipcTransport"]),
            ipc_host=cast("str | None", payload.get("ipcHost")),
            ipc_port=cast("int | None", payload.get("ipcPort")),
            ipc_path=cast("str | None", payload.get("ipcPath")),
            ipc_pipe_name=cast("str | None", payload.get("ipcPipeName")),
            session_id=cast("str | None", payload.get("sessionId")),
            just_my_code=bool(payload.get("justMyCode", True)),
            strict_expression_watch_policy=bool(payload.get("strictExpressionWatchPolicy", False)),
            dapper_root=cast("str | None", payload.get("dapperRoot")),
        )


def _resolve_dapper_root() -> str:
    import dapper  # noqa: PLC0415

    return str(Path(dapper.__file__).resolve().parent.parent)


def _build_remote_exec_script(payload: AttachByPidPayload) -> str:
    payload_json = json.dumps(payload.to_remote_exec_dict(), sort_keys=True)
    dapper_root = payload.dapper_root or _resolve_dapper_root()
    return (
        "import sys\n"
        f"_dapper_root = {dapper_root!r}\n"
        "if _dapper_root and _dapper_root not in sys.path:\n"
        "    sys.path.insert(0, _dapper_root)\n"
        "from dapper.launcher.attach_by_pid import bootstrap_from_remote_exec as _bootstrap\n"
        f"_bootstrap({payload_json!r})\n"
    )


def _schedule_script_cleanup(script_path: str, *, delay_seconds: float = 30.0) -> None:
    path = Path(script_path)

    def _cleanup() -> None:
        try:
            if delay_seconds > 0:
                time.sleep(delay_seconds)
            path.unlink(missing_ok=True)
        except Exception:
            logger.debug("Failed to remove remote-exec script %s", script_path, exc_info=True)

    atexit.register(lambda: path.unlink(missing_ok=True))
    threading.Thread(target=_cleanup, daemon=True, name="dapper-attach-script-cleanup").start()


def _write_remote_exec_script(payload: AttachByPidPayload) -> str:
    script = _build_remote_exec_script(payload)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".py", delete=False) as handle:
        handle.write(script)
        script_path = handle.name
    _schedule_script_cleanup(script_path)
    return script_path


def _require_remote_exec() -> Any:
    remote_exec = getattr(sys, "remote_exec", None)
    if not callable(remote_exec):
        msg = "This Python interpreter does not support sys.remote_exec(); Python 3.14 is required"
        raise NotImplementedError(msg)
    return remote_exec


def _classify_attach_failure(exc: Exception, *, process_id: int) -> AttachByPidDiagnostic:
    detail = str(exc).strip() or exc.__class__.__name__
    detail_lower = detail.lower()

    if isinstance(exc, NotImplementedError) and "sys.remote_exec" in detail:
        return AttachByPidDiagnostic(
            code="python_version_mismatch",
            message="Attach by PID requires a Python 3.14 helper interpreter with sys.remote_exec().",
            detail=detail,
            hint=(
                "Point Dapper at a CPython 3.14 interpreter via pythonPath or venvPath, "
                "and make sure the target process is also CPython 3.14 with the same major/minor version."
            ),
        )

    if isinstance(exc, ProcessLookupError):
        return AttachByPidDiagnostic(
            code="process_not_found",
            message=f"The target process {process_id} no longer exists or could not be found.",
            detail=detail,
            hint="Verify the PID and ensure the target Python process is still running before retrying.",
        )

    if isinstance(exc, PermissionError):
        return AttachByPidDiagnostic(
            code="missing_privileges",
            message=f"The OS denied attach-by-PID access to process {process_id}.",
            detail=detail,
            hint=(
                "Run VS Code or the attach helper with sufficient privileges for the target process. "
                "On Linux this may require ptrace permissions or CAP_SYS_PTRACE; on macOS and Windows "
                "it often requires elevated privileges."
            ),
        )

    if (
        "disable_remote_debug" in detail_lower
        or "remote debugging" in detail_lower
        or "remote debugger" in detail_lower
    ) and ("disabled" in detail_lower or "without-remote-debug" in detail_lower):
        return AttachByPidDiagnostic(
            code="remote_debugging_disabled",
            message="The target interpreter has CPython remote debugging disabled.",
            detail=detail,
            hint=(
                "Restart the target without PYTHON_DISABLE_REMOTE_DEBUG=1, without -X disable_remote_debug, "
                "and with a CPython build that was not compiled with --without-remote-debug."
            ),
        )

    if "mismatch" in detail_lower and "version" in detail_lower:
        return AttachByPidDiagnostic(
            code="python_version_mismatch",
            message="The helper interpreter and target interpreter are not version-compatible for sys.remote_exec().",
            detail=detail,
            hint=(
                "Use the same CPython major/minor version on both sides. Pre-release interpreters must match exactly, "
                "and free-threaded vs. GIL builds must also be compatible."
            ),
        )

    return AttachByPidDiagnostic(
        code="attach_failed",
        message=f"Attach by PID failed for process {process_id}.",
        detail=detail,
        hint="Check the helper output and the target interpreter constraints, then retry.",
    )


def _emit_attach_failure_diagnostic(diagnostic: AttachByPidDiagnostic) -> None:
    sys.stderr.write(f"Attach-by-PID failed: {diagnostic.message}\n")
    if diagnostic.detail:
        sys.stderr.write(f"Detail: {diagnostic.detail}\n")
    if diagnostic.hint:
        sys.stderr.write(f"Hint: {diagnostic.hint}\n")
    sys.stderr.write(
        f"{_ATTACH_DIAGNOSTIC_PREFIX}{json.dumps(diagnostic.to_dict(), sort_keys=True)}\n"
    )


def attach_by_pid(
    process_id: int,
    *,
    ipc_transport: str,
    ipc_host: str | None = None,
    ipc_port: int | None = None,
    ipc_path: str | None = None,
    ipc_pipe_name: str | None = None,
    session_id: str | None = None,
    just_my_code: bool = True,
    strict_expression_watch_policy: bool = False,
) -> str:
    """Invoke ``sys.remote_exec`` to bootstrap Dapper inside a live process."""
    payload = AttachByPidPayload(
        process_id=int(process_id),
        ipc_transport=str(ipc_transport),
        ipc_host=ipc_host,
        ipc_port=ipc_port,
        ipc_path=ipc_path,
        ipc_pipe_name=ipc_pipe_name,
        session_id=session_id,
        just_my_code=just_my_code,
        strict_expression_watch_policy=strict_expression_watch_policy,
        dapper_root=_resolve_dapper_root(),
    )
    script_path = _write_remote_exec_script(payload)
    remote_exec = _require_remote_exec()
    remote_exec(int(process_id), script_path)
    return script_path


def _thread_name(thread_id: int) -> str:
    for thread in threading.enumerate():
        if thread.ident == thread_id:
            return thread.name
    return f"Thread-{thread_id}"


def _clear_frame_traces() -> None:
    current_frames = getattr(sys, "_current_frames", None)
    if not callable(current_frames):
        return
    frames_by_thread = cast("dict[int, Any]", current_frames())
    for frame in frames_by_thread.values():
        current = frame
        while current is not None:
            try:
                current.f_trace = None
            except Exception:
                pass
            current = current.f_back


def _cleanup_attached_session() -> None:
    with _ATTACH_LOCK:
        try:
            sys.settrace(None)
        except Exception:
            logger.debug("Failed to clear sys.settrace during attach cleanup", exc_info=True)
        try:
            threading.settrace(None)
        except Exception:
            logger.debug("Failed to clear threading.settrace during attach cleanup", exc_info=True)
        _clear_frame_traces()
        session = debug_shared.state
        for stream_name in ("ipc_rfile", "ipc_wfile", "ipc_pipe_conn", "ipc_sock"):
            stream = getattr(session, stream_name)
            if stream is None:
                continue
            try:
                stream.close()
            except Exception:
                logger.debug(
                    "Failed to close %s during attach cleanup", stream_name, exc_info=True
                )
        session.debugger = None
        session.command_thread = None
        session.ipc_enabled = False
        session.ipc_sock = None
        session.ipc_rfile = None
        session.ipc_wfile = None
        session.ipc_pipe_conn = None
        _ATTACH_ACTIVE.clear()


def _install_live_tracing() -> None:
    session = debug_shared.state
    debugger = session.debugger
    if debugger is None:
        msg = "Debugger not initialized for live attach"
        raise RuntimeError(msg)

    trace_fn = cast("Any", debugger).trace_dispatch
    threading.settrace(trace_fn)
    sys.settrace(trace_fn)

    current_frames = getattr(sys, "_current_frames", None)
    if not callable(current_frames):
        return

    frames_by_thread = cast("dict[int, Any]", current_frames())
    for thread_id, frame in frames_by_thread.items():
        debugger.thread_tracker.threads.setdefault(thread_id, _thread_name(thread_id))
        current = frame
        while current is not None:
            try:
                current.f_trace = trace_fn
            except Exception:
                logger.debug("Failed to set frame trace for thread %s", thread_id, exc_info=True)
                break
            current = current.f_back


def _configure_attached_session(payload: AttachByPidPayload) -> None:
    session = debug_shared.DebugSession()
    debug_shared.state = session
    session.session_id = payload.session_id or uuid.uuid4().hex
    session.stop_at_entry = False
    session.no_debug = False
    session.cleanup_func = _cleanup_attached_session

    def _attached_exit(_code: int) -> None:
        session.terminate_session()
        session.run_cleanup()

    session.exit_func = _attached_exit

    debug_launcher.setup_session_log_file(session.session_id)

    args = SimpleNamespace(
        ipc=payload.ipc_transport,
        ipc_host=payload.ipc_host,
        ipc_port=payload.ipc_port,
        ipc_path=payload.ipc_path,
        ipc_pipe=payload.ipc_pipe_name,
    )
    debug_launcher.setup_ipc_from_args(args, session=session)
    debug_launcher.start_command_listener(session=session)
    debug_launcher.configure_debugger(
        False,
        session=session,
        just_my_code=payload.just_my_code,
        strict_expression_watch_policy=payload.strict_expression_watch_policy,
    )
    session.debugger_configured_event.set()
    _install_live_tracing()


def _bootstrap_attached_process(payload: AttachByPidPayload) -> None:
    with _ATTACH_LOCK:
        if _ATTACH_ACTIVE.is_set():
            logger.info(
                "Attach-by-PID bootstrap ignored because a live attach session already exists"
            )
            return
        _ATTACH_ACTIVE.set()

    try:
        _configure_attached_session(payload)
        logger.info(
            "Attached Dapper bootstrap is active for pid=%s session_id=%s",
            os.getpid(),
            debug_shared.state.session_id,
        )
    except Exception:
        with _ATTACH_LOCK:
            _ATTACH_ACTIVE.clear()
        raise


def bootstrap_from_remote_exec(payload_json: str) -> None:
    """Entry point executed inside the remote target process."""
    payload_data = json.loads(payload_json)
    payload = AttachByPidPayload.from_remote_exec_dict(payload_data)

    bootstrap_thread = threading.Thread(
        target=_bootstrap_attached_process,
        args=(payload,),
        daemon=True,
        name="dapper-live-attach-bootstrap",
    )
    bootstrap_thread.start()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Attach Dapper to a live Python 3.14 process")
    parser.add_argument("--pid", type=int, required=True, help="Target process ID")
    parser.add_argument("--ipc", choices=["tcp", "unix", "pipe"], required=True)
    parser.add_argument("--ipc-host", type=str, help="IPC TCP host")
    parser.add_argument("--ipc-port", type=int, help="IPC TCP port")
    parser.add_argument("--ipc-path", type=str, help="IPC UNIX socket path")
    parser.add_argument("--ipc-pipe", type=str, help="IPC Windows pipe name")
    parser.add_argument("--session-id", type=str, help="Logical session identifier")
    parser.add_argument(
        "--no-just-my-code",
        action="store_true",
        help="Disable just-my-code filtering in the attached target",
    )
    parser.add_argument(
        "--strict-expression-watch-policy",
        action="store_true",
        help="Enable strict expression watchpoint policy checks",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        attach_by_pid(
            args.pid,
            ipc_transport=args.ipc,
            ipc_host=args.ipc_host,
            ipc_port=args.ipc_port,
            ipc_path=args.ipc_path,
            ipc_pipe_name=args.ipc_pipe,
            session_id=args.session_id,
            just_my_code=not args.no_just_my_code,
            strict_expression_watch_policy=args.strict_expression_watch_policy,
        )
    except Exception as exc:
        diagnostic = _classify_attach_failure(exc, process_id=args.pid)
        logger.exception("Attach-by-PID helper failed for pid=%s", args.pid)
        _emit_attach_failure_diagnostic(diagnostic)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
