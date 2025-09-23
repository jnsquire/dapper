"""
Implementation of the Debug Adapter Protocol Server and integrated Python debugger.

This module merges the DebugAdapterServer and PyDebugger to avoid circular
dependencies and simplify interactions between the server and debugger.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import inspect
import json
import linecache
import logging
import os
import re
import socket as _socket
import subprocess
import sys
import tempfile
import threading
import time
from multiprocessing import connection as mp_conn
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import Callable
from typing import cast

from dapper.ipc_binary import HEADER_SIZE
from dapper.ipc_binary import pack_frame
from dapper.ipc_binary import read_exact
from dapper.ipc_binary import unpack_header
from dapper.protocol import ProtocolHandler

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from concurrent.futures import Future as _CFuture

    from dapper.connections import ConnectionBase
    from dapper.inprocess_debugger import InProcessDebugger
    from dapper.protocol_types import ExceptionInfoRequest
    from dapper.protocol_types import GenericRequest
    from dapper.protocol_types import Source


logger = logging.getLogger(__name__)


class PyDebuggerThread:
    """Lightweight thread model tracked by the debugger."""

    def __init__(self, thread_id: int, name: str):
        self.id = thread_id
        self.name = name
        self.frames = []
        self.is_stopped = False
        self.stop_reason = ""


class PyDebugger:
    """
    Main debugger class that integrates with Python's built-in debugging tools
    and communicates back to the DebugAdapterServer.
    """

    # Instance attribute type hints (help static analysis tools)
    threads: dict[int, PyDebuggerThread]
    main_thread_id: int | None
    next_thread_id: int
    next_var_ref: int
    var_refs: dict[int, object]
    breakpoints: dict[str, list[dict]]
    function_breakpoints: list[dict[str, Any]]
    exception_breakpoints: dict[str, bool]
    process: subprocess.Popen | None
    debugger_thread: threading.Thread | None
    is_terminated: bool
    program_running: bool
    stop_on_entry: bool
    no_debug: bool
    current_stack_frames: dict[int, list]
    program_path: str | None
    thread_exit_events: dict[int, object]
    lock: threading.RLock
    stopped_event: asyncio.Event
    configuration_done: asyncio.Event
    _bg_tasks: set[asyncio.Task]
    _test_mode: bool
    # Data breakpoint state
    _data_watches: dict[str, dict[str, Any]]  # dataId -> watch metadata
    _frame_watches: dict[int, list[str]]  # frameId -> list of dataIds

    def __init__(self, server, loop: asyncio.AbstractEventLoop | None = None):
        self.server = server
        # Prefer the caller-provided loop; otherwise reuse the current event loop.
        # Avoid creating ad-hoc event loops by default to prevent leaks in tests
        # and to integrate cleanly with pytest-asyncio.
        if loop is None:
            try:
                self.loop = asyncio.get_event_loop()
                self._owns_loop = False
            except RuntimeError:
                # No current loop set; fall back to creating one we own.
                self.loop = asyncio.new_event_loop()
                self._owns_loop = True
        else:
            self.loop = loop
            self._owns_loop = False

        # Core state
        self.threads: dict[int, PyDebuggerThread] = {}
        self.main_thread_id: int | None = None
        self.next_thread_id = 1
        self.next_var_ref = 1000
        self.var_refs: dict[int, object] = {}
        self.breakpoints: dict[str, list[dict]] = {}
        # store function breakpoints as list[dict] at runtime for flexibility
        self.function_breakpoints = []
        # Exception breakpoint flags (two booleans for clarity)
        self.exception_breakpoints_uncaught = False
        self.exception_breakpoints_raised = False
        self.process = None
        self.debugger_thread = None
        self.is_terminated = False
        self.program_running = False
        self.stop_on_entry = False
        self.no_debug = False
        self.current_stack_frames: dict[int, list] = {}
        self.program_path: str | None = None
        self.thread_exit_events: dict[int, object] = {}
        self.lock = threading.RLock()
        self.stopped_event = asyncio.Event()
        self.configuration_done = asyncio.Event()

        # Keep references to background tasks so they don't get GC'd
        self._bg_tasks: set[asyncio.Task] = set()

        # Test mode flag (used by tests to start debuggee in a real thread)
        self._test_mode = False

        # Command tracking for request-response communication
        self._next_command_id = 1
        self._pending_commands: dict[int, asyncio.Future] = {}
        # In-process debugging support (optional/opt-in)
        self.in_process = False
        self._inproc: InProcessDebugger | None = None

        # Optional IPC transport to the launcher (subprocess mode)
        self._use_ipc: bool = False
        self._ipc_enabled: bool = False
        self._ipc_listen_sock = None
        self._ipc_sock = None
        self._ipc_rfile = None
        self._ipc_wfile = None
        self._ipc_pipe_listener = None  # type: mp_conn.Listener | None
        self._ipc_pipe_conn = None  # type: mp_conn.Connection | None
        self._ipc_unix_path = None  # type: Path | None
        self._ipc_binary = False

        # Data breakpoint containers
        self._data_watches = {}
        self._frame_watches = {}

    # ------------------------------------------------------------------
    # Data Breakpoint (Watchpoint) Support (Phase 1: bookkeeping only)
    # ------------------------------------------------------------------
    def data_breakpoint_info(self, *, name: str, frame_id: int) -> dict[str, Any]:
        """Return minimal data breakpoint info for a variable in a frame."""
        data_id = f"frame:{frame_id}:var:{name}"
        return {
            "dataId": data_id,
            "description": f"Variable '{name}' in frame {frame_id}",
            "accessTypes": ["write"],
            "canPersist": False,
        }

    def set_data_breakpoints(self, breakpoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Register a set of data breakpoints (bookkeeping only)."""
        # Clear existing watches (DAP semantics: full replace)
        self._data_watches.clear()
        self._frame_watches.clear()

        results: list[dict[str, Any]] = []
        frame_id_parts_expected = 4  # pattern: frame:{id}:var:{name}
        watch_names: set[str] = set()
        watch_meta: list[tuple[str, dict[str, Any]]] = []
        for bp in breakpoints:
            data_id = bp.get("dataId")
            if not data_id or not isinstance(data_id, str):
                results.append({"verified": False, "message": "Missing dataId"})
                continue
            # Parse frame id for indexing (best-effort extraction)
            frame_id = None
            parts = data_id.split(":")
            # Expect pattern frame:{fid}:var:{name}
            if len(parts) >= frame_id_parts_expected and parts[0] == "frame" and parts[2] == "var":
                try:
                    frame_id = int(parts[1])
                except ValueError:
                    frame_id = None
                # capture variable name portion for runtime detection bridging
                if len(parts) >= frame_id_parts_expected:
                    var_name = parts[3]
                    watch_names.add(var_name)
            meta = {
                "dataId": data_id,
                "accessType": bp.get("accessType", "write"),
                "condition": bp.get("condition"),
                "hitCondition": bp.get("hitCondition"),
                "hit": 0,
                "verified": True,
            }
            self._data_watches[data_id] = meta
            # store meta for bridging keyed by variable name
            if "var:" in data_id:
                try:
                    watch_meta.append((parts[3], meta))
                except Exception:  # pragma: no cover - defensive
                    pass
            if frame_id is not None:
                self._frame_watches.setdefault(frame_id, []).append(data_id)
            results.append({"verified": True})
        # Bridge to in-process debugger (if active) so it can detect changes by name
        try:
            inproc = getattr(self, "_inproc", None)
            if inproc is not None and hasattr(inproc, "debugger"):
                dbg = getattr(inproc, "debugger", None)
                register = getattr(dbg, "register_data_watches", None)
                if callable(register):
                    register(sorted(watch_names), watch_meta)
        except Exception:  # pragma: no cover - defensive
            logger.debug("Failed bridging data watches to BDB", exc_info=True)
        return results

    def _check_data_watches_for_frame(self, frame_id: int, frame_locals: dict[str, Any]) -> None:  # noqa: ARG002
        """(Future) Detect variable changes for watches tied to frame_id."""
        return

    def _forward_event(self, event_name: str, payload: dict[str, Any]) -> None:
        """Forward an event to the client, scheduling on the debugger loop."""
        self._schedule_coroutine(self.server.send_event(event_name, payload))

    async def launch(
        self,
        program: str,
        args: list[str] | None = None,
        stop_on_entry: bool = False,
        no_debug: bool = False,
        in_process: bool = False,
        use_ipc: bool = False,
        use_binary_ipc: bool = False,
        ipc_transport: str | None = None,
        ipc_pipe_name: str | None = None,
    ) -> None:
        """Launch a new Python program for debugging."""
        if self.program_running:
            msg = "A program is already being debugged"
            raise RuntimeError(msg)

        self.program_path = str(Path(program).resolve())
        self.stop_on_entry = stop_on_entry
        self.no_debug = no_debug
        args = args or []

        # Optional in-process mode
        if in_process:
            await self._launch_in_process()
            return

        # Create a new subprocess running the debugged program
        debug_args = [
            sys.executable,
            "-m",
            "dapper.debug_launcher",
            "--program",
            self.program_path,
        ]

        # Pass other arguments
        for arg in args:
            debug_args.extend(["--arg", arg])

        if stop_on_entry:
            debug_args.append("--stop-on-entry")

        if no_debug:
            debug_args.append("--no-debug")

        # If IPC is requested, prepare a listener and pass coordinates.
        self._use_ipc = bool(use_ipc)
        self._ipc_binary = bool(use_binary_ipc)
        if self._use_ipc:
            self._prepare_ipc_listener(ipc_transport, ipc_pipe_name, debug_args)
            if self._ipc_binary:
                debug_args.append("--ipc-binary")

        logger.info("Launching program: %s", self.program_path)
        logger.debug("Debug command: %s", " ".join(debug_args))

        # Start the subprocess in a worker thread to avoid blocking.
        if getattr(self, "_test_mode", False):
            threading.Thread(
                target=self._start_debuggee_process,
                args=(debug_args,),
                daemon=True,
            ).start()
        else:
            try:
                await self.loop.run_in_executor(None, self._start_debuggee_process, debug_args)
            except Exception:
                await asyncio.to_thread(self._start_debuggee_process, debug_args)

        # If IPC is enabled, accept the connection from the launcher
        if self._use_ipc and (
            self._ipc_listen_sock is not None or self._ipc_pipe_listener is not None
        ):
            threading.Thread(target=self._run_ipc_accept_and_read, daemon=True).start()

        self.program_running = True

        # Send event to tell the client the process has started
        process_event = {
            "name": Path(self.program_path).name,
            "systemProcessId": self.process.pid if self.process else None,
            "isLocalProcess": True,
            "startMethod": "launch",
        }
        await self.server.send_event("process", process_event)

        # If we need to stop on entry, we should wait for the stopped event
        if stop_on_entry and not no_debug:
            await self.stopped_event.wait()

    async def _launch_in_process(self) -> None:
        """Initialize in-process debugging bridge and emit process event."""
        _inproc_cls = self._import_inprocess_cls()

        # Create the in-process bridge and attach event listeners
        self.in_process = True
        self._inproc = _inproc_cls()
        self._inproc.on_stopped.add_listener(self._inproc_on_stopped)  # type: ignore[attr-defined]
        self._inproc.on_thread.add_listener(self._inproc_on_thread)  # type: ignore[attr-defined]
        self._inproc.on_exited.add_listener(self._inproc_on_exited)  # type: ignore[attr-defined]
        self._inproc.on_output.add_listener(self._inproc_on_output)  # type: ignore[attr-defined]

        # Mark running and emit process event for current interpreter
        self.program_running = True
        proc_event = {
            "name": Path(self.program_path or "").name,
            "systemProcessId": os.getpid(),
            "isLocalProcess": True,
            "startMethod": "launch",
        }
        await self.server.send_event("process", proc_event)

    def _import_inprocess_cls(self):
        """Import and return the InProcessDebugger class.

        Raises RuntimeError with a clear message if import fails.
        """
        try:
            module = importlib.import_module("dapper.inprocess_debugger")
        except Exception as exc:  # pragma: no cover - defensive import
            msg = f"In-process debugging not available: {exc!s}"
            raise RuntimeError(msg) from exc
        else:
            return module.InProcessDebugger  # type: ignore[attr-defined]

    def _make_inproc_callbacks(self):
        """Return a dict of event handlers that forward inproc events to the server."""
        return {
            "stopped": self._inproc_on_stopped,
            "thread": self._inproc_on_thread,
            "exited": self._inproc_on_exited,
            "output": self._inproc_on_output,
        }

    def _inproc_on_stopped(self, data: dict[str, Any]) -> None:
        """Forward stopped events from inproc to the server, with isolation."""
        try:
            self._handle_event_stopped(data)
        except Exception:
            logger.exception("error in on_stopped callback")

    def _inproc_on_thread(self, data: dict[str, Any]) -> None:
        """Forward thread events from inproc to the server, with isolation."""
        try:
            self._handle_event_thread(data)
        except Exception:
            logger.exception("error in on_thread callback")

    def _inproc_on_exited(self, data: dict[str, Any]) -> None:
        """Forward exited events from inproc to the server, with isolation."""
        try:
            self._handle_event_exited(data)
        except Exception:
            logger.exception("error in on_exited callback")

    def _inproc_on_output(self, category: str, output: str) -> None:
        """Forward output events from inproc to the server, with isolation."""
        try:
            payload = {"category": category, "output": output}
            self.server.send_event("output", payload)
        except Exception:
            logger.exception("error in on_output callback")

    async def attach(  # noqa: PLR0915
        self,
        *,
        use_ipc: bool = False,
        ipc_transport: str | None = None,
        ipc_host: str | None = None,
        ipc_port: int | None = None,
        ipc_path: str | None = None,
        ipc_pipe_name: str | None = None,
    ) -> None:
        """Attach to an already running debuggee via IPC."""
        if not use_ipc:
            msg = "attach without useIpc is not supported yet"
            raise RuntimeError(msg)

        default_transport = "pipe" if os.name == "nt" else "unix"
        transport = (ipc_transport or default_transport).lower()

        if os.name == "nt" and transport == "pipe":
            if not ipc_pipe_name:
                msg = "ipcPipeName required for pipe attach"
                raise RuntimeError(msg)
            try:
                self._ipc_pipe_conn = mp_conn.Client(address=ipc_pipe_name, family="AF_PIPE")
            except Exception as exc:  # pragma: no cover - depends on OS
                msg = "failed to connect pipe"
                raise RuntimeError(msg) from exc
            self._ipc_pipe_listener = None
            self._ipc_enabled = True

            def _reader():
                try:
                    while True:
                        try:
                            conn = cast("mp_conn.Connection", self._ipc_pipe_conn)
                            msg = conn.recv()
                        except (EOFError, OSError):
                            break
                        if isinstance(msg, str) and msg.startswith("DBGP:"):
                            self._handle_debug_message(msg[5:].strip())
                finally:
                    self._ipc_enabled = False
                    self._cleanup_ipc_resources()

            threading.Thread(target=_reader, daemon=True).start()
        elif transport == "unix":
            af_unix = getattr(_socket, "AF_UNIX", None)
            if not (af_unix and ipc_path):
                msg = "ipcPath required for unix attach"
                raise RuntimeError(msg)
            try:
                sock = _socket.socket(af_unix, _socket.SOCK_STREAM)
                sock.connect(ipc_path)
            except Exception as exc:  # pragma: no cover - platform dependent
                msg = "failed to connect unix socket"
                raise RuntimeError(msg) from exc
            self._ipc_sock = sock
            self._ipc_rfile = sock.makefile("r", encoding="utf-8", newline="")
            self._ipc_wfile = sock.makefile("w", encoding="utf-8", newline="")
            self._ipc_enabled = True

            def _reader_sock():
                try:
                    while True:
                        rfile = self._ipc_rfile
                        assert rfile is not None
                        line = rfile.readline()
                        if not line:
                            break
                        line_s = cast("str", line)
                        if line_s.startswith("DBGP:"):
                            self._handle_debug_message(line_s[5:].strip())
                finally:
                    self._ipc_enabled = False
                    self._cleanup_ipc_resources()

            threading.Thread(target=_reader_sock, daemon=True).start()
        elif transport == "tcp":
            host = ipc_host or "127.0.0.1"
            if not ipc_port:
                msg = "ipcPort required for tcp attach"
                raise RuntimeError(msg)
            try:
                sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
                sock.connect((host, int(ipc_port)))
            except Exception as exc:
                msg = "failed to connect tcp socket"
                raise RuntimeError(msg) from exc
            self._ipc_sock = sock
            self._ipc_rfile = sock.makefile("r", encoding="utf-8", newline="")
            self._ipc_wfile = sock.makefile("w", encoding="utf-8", newline="")
            self._ipc_enabled = True

            def _reader_tcp():
                try:
                    while True:
                        rfile = self._ipc_rfile
                        assert rfile is not None
                        line = rfile.readline()
                        if not line:
                            break
                        line_s = cast("str", line)
                        if line_s.startswith("DBGP:"):
                            self._handle_debug_message(line_s[5:].strip())
                finally:
                    self._ipc_enabled = False
                    self._cleanup_ipc_resources()

            threading.Thread(target=_reader_tcp, daemon=True).start()
        else:
            msg = f"unsupported attach transport: {transport}"
            raise RuntimeError(msg)

        # Mark running and send a generic process event
        self.program_running = True
        await self.server.send_event(
            "process",
            {
                "name": self.program_path or "attached",
                "isLocalProcess": True,
                "startMethod": "attach",
            },
        )

    # --- Helper methods to reduce branching in launch ---

    def _prepare_ipc_listener(
        self,
        ipc_transport: str | None,
        ipc_pipe_name: str | None,
        debug_args: list[str],
    ) -> None:
        """Prepare IPC listener resources and extend debug_args for launcher."""
        default_transport = "pipe" if os.name == "nt" else "unix"
        transport = (ipc_transport or default_transport).lower()

        if os.name == "nt" and transport == "pipe":
            pipe_name = (
                ipc_pipe_name or rf"\\.\pipe\dapper-{os.getpid()}-{int(time.time() * 1000)}"
            )
            try:
                self._ipc_pipe_listener = mp_conn.Listener(address=pipe_name, family="AF_PIPE")
            except Exception:
                logger.exception("Failed to create named pipe listener")
                self._ipc_pipe_listener = None
            else:
                debug_args.extend(["--ipc", "pipe", "--ipc-pipe", pipe_name])
            return

        af_unix = getattr(_socket, "AF_UNIX", None)
        if transport == "unix" and af_unix:
            try:
                name = f"dapper-{os.getpid()}-{int(time.time() * 1000)}.sock"
                unix_path = Path(tempfile.gettempdir()) / name
                with contextlib.suppress(FileNotFoundError):
                    unix_path.unlink()
                listen = _socket.socket(af_unix, _socket.SOCK_STREAM)
                listen.bind(str(unix_path))
                listen.listen(1)
            except Exception:
                logger.exception("Failed to create UNIX socket; fallback to TCP")
            else:
                self._ipc_listen_sock = listen
                self._ipc_unix_path = unix_path
                debug_args.extend(["--ipc", "unix", "--ipc-path", str(unix_path)])
                return

        host = "127.0.0.1"
        listen = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        with contextlib.suppress(Exception):
            listen.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        listen.bind((host, 0))
        listen.listen(1)
        _addr, port = listen.getsockname()
        self._ipc_listen_sock = listen
        debug_args.extend(
            [
                "--ipc",
                "tcp",
                "--ipc-host",
                host,
                "--ipc-port",
                str(port),
            ]
        )

    def _run_ipc_accept_and_read(self) -> None:
        """Accept one IPC connection then stream DBGP lines to handler."""
        try:
            if self._ipc_pipe_listener is not None:
                self._ipc_accept_and_read_pipe()
                return

            if self._ipc_listen_sock is not None:
                self._ipc_accept_and_read_socket()
        except Exception:
            logger.exception("IPC reader error")
        finally:
            self._ipc_enabled = False
            self._cleanup_ipc_resources()

    def _ipc_accept_and_read_pipe(self) -> None:
        """Accept and read from a named pipe connection."""
        conn = self._ipc_pipe_listener.accept()  # type: ignore[union-attr]
        self._ipc_pipe_conn = conn
        self._ipc_enabled = True
        while True:
            try:
                if self._ipc_binary:
                    data = conn.recv_bytes()
                    if not data:
                        break
                    try:
                        kind, length = unpack_header(data[:HEADER_SIZE])
                    except Exception:
                        break
                    payload = data[HEADER_SIZE:HEADER_SIZE + length]
                    if kind == 1:
                        self._handle_debug_message(payload.decode("utf-8"))
                    continue
                msg = conn.recv()
            except (EOFError, OSError):
                break
            if isinstance(msg, str) and msg.startswith("DBGP:"):
                self._handle_debug_message(msg[5:].strip())

    def _ipc_accept_and_read_socket(self) -> None:
        """Accept and read from a TCP/UNIX socket connection."""
        listen_sock = self._ipc_listen_sock
        assert listen_sock is not None
        conn2, _ = listen_sock.accept()
        self._ipc_sock = conn2
        if self._ipc_binary:
            self._ipc_rfile = conn2.makefile("rb", buffering=0)
            self._ipc_wfile = conn2.makefile("wb", buffering=0)
        else:
            self._ipc_rfile = conn2.makefile("r", encoding="utf-8", newline="")
            self._ipc_wfile = conn2.makefile("w", encoding="utf-8", newline="")
        self._ipc_enabled = True
        while True:
            if self._ipc_binary:
                # Read header then payload
                header = read_exact(self._ipc_rfile, HEADER_SIZE)  # type: ignore[arg-type]
                if not header:
                    break
                try:
                    kind, length = unpack_header(header)
                except Exception:
                    break
                payload = read_exact(self._ipc_rfile, length)  # type: ignore[arg-type]
                if not payload:
                    break
                if kind == 1:
                    self._handle_debug_message(payload.decode("utf-8"))
                continue
            line = self._ipc_rfile.readline()  # type: ignore[union-attr]
            if not line:
                break
            line_s = cast("str", line)
            if line_s.startswith("DBGP:"):
                self._handle_debug_message(line_s[5:].strip())

    def _cleanup_ipc_resources(self) -> None:
        """Close IPC resources quietly and clean up files."""
        for f in (self._ipc_rfile, self._ipc_wfile):
            with contextlib.suppress(Exception):
                f.close()  # type: ignore[union-attr]

        with contextlib.suppress(Exception):
            if self._ipc_sock is not None:
                self._ipc_sock.close()
        with contextlib.suppress(Exception):
            if self._ipc_listen_sock is not None:
                self._ipc_listen_sock.close()

        with contextlib.suppress(Exception):
            if self._ipc_unix_path:
                self._ipc_unix_path.unlink()

        with contextlib.suppress(Exception):
            if self._ipc_pipe_conn is not None:
                self._ipc_pipe_conn.close()
        with contextlib.suppress(Exception):
            if self._ipc_pipe_listener is not None:
                self._ipc_pipe_listener.close()

    def _start_debuggee_process(self, debug_args: list[str]) -> None:
        """Start the debuggee process in a separate thread."""
        try:
            self.process = subprocess.Popen(
                debug_args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

            stdout = cast("Any", self.process.stdout)
            stderr = cast("Any", self.process.stderr)
            threading.Thread(
                target=self._read_output,
                args=(stdout, "stdout"),
                daemon=True,
            ).start()
            threading.Thread(
                target=self._read_output,
                args=(stderr, "stderr"),
                daemon=True,
            ).start()

            exit_code = self.process.wait()

            if not self.is_terminated:
                self.is_terminated = True

            self._schedule_coroutine(self._handle_program_exit(exit_code))
        except Exception:
            logger.exception("Error starting debuggee")
            self.is_terminated = True
            self._schedule_coroutine(self._handle_program_exit(1))

    def _read_output(self, stream, category: str) -> None:
        """Read output from the debuggee's stdout/stderr streams."""
        try:
            while True:
                line = stream.readline()
                if not line:
                    break

                if line.startswith("DBGP:"):
                    self._handle_debug_message(line[5:].strip())
                else:
                    self._schedule_coroutine(
                        self.server.send_event("output", {"category": category, "output": line})
                    )
        except Exception:
            logger.exception("Error reading %s", category)

    def _handle_event_stopped(self, data: dict[str, Any]) -> None:
        """Handle a stopped event's local state updates and forwarding."""
        thread_id = data.get("threadId", 1)
        reason = data.get("reason", "breakpoint")

        with self.lock:
            if thread_id not in self.threads:
                thread_name = f"Thread {thread_id}"
                self.threads[thread_id] = PyDebuggerThread(thread_id, thread_name)
            self.threads[thread_id].is_stopped = True
            self.threads[thread_id].stop_reason = reason

        stop_event = {
            "reason": reason,
            "threadId": thread_id,
            "allThreadsStopped": data.get("allThreadsStopped", True),
        }
        if "text" in data:
            stop_event["text"] = data["text"]

        try:
            self.stopped_event.set()
        except Exception:
            try:
                self.loop.call_soon_threadsafe(self.stopped_event.set)
            except Exception:
                with contextlib.suppress(Exception):
                    self.stopped_event.set()

        awaitable = self.server.send_event("stopped", stop_event)
        if awaitable is not None:
            self._schedule_coroutine(awaitable)

    def _handle_event_thread(self, data: dict[str, Any]) -> None:
        """Handle thread started/exited events and forward to client."""
        thread_id = data.get("threadId", 1)
        reason = data.get("reason", "started")

        if reason == "started":
            with self.lock:
                if thread_id not in self.threads:
                    default_name = f"Thread {thread_id}"
                    thread_name = data.get("name", default_name)
                    self.threads[thread_id] = PyDebuggerThread(thread_id, thread_name)
        else:
            with self.lock:
                if thread_id in self.threads:
                    del self.threads[thread_id]

        self._forward_event("thread", {"reason": reason, "threadId": thread_id})

    def _handle_event_exited(self, data: dict[str, Any]) -> None:
        """Handle debuggee exited event and schedule cleanup."""
        exit_code = data.get("exitCode", 0)
        self.is_terminated = True
        self._schedule_coroutine(self._handle_program_exit(exit_code))

    def _handle_event_stacktrace(self, data: dict[str, Any]) -> None:
        """Cache stack trace data from the debuggee."""
        thread_id = data.get("threadId", 1)
        stack_frames = data.get("stackFrames", [])
        with self.lock:
            self.current_stack_frames[thread_id] = stack_frames

    def _handle_event_variables(self, data: dict[str, Any]) -> None:
        """Cache variables payload from the debuggee."""
        var_ref = data.get("variablesReference", 0)
        variables = data.get("variables", [])
        with self.lock:
            self.var_refs[var_ref] = variables

    def _handle_debug_message(self, message: str) -> None:
        """Handle a debug protocol message from the debuggee."""
        try:
            data: dict[str, Any] = json.loads(message)
        except Exception:
            logger.exception("Error handling debug message")
            return

        command_id = data.get("id")
        if command_id is not None and command_id in self._pending_commands:
            with self.lock:
                future = self._pending_commands.pop(command_id, None)

            if future is not None:
                self._resolve_pending_response(future, data)
            return

        event_type: str | None = data.get("event")

        if event_type == "stopped":
            self._handle_event_stopped(data)
        elif event_type == "thread":
            self._handle_event_thread(data)
        elif event_type == "exited":
            self._handle_event_exited(data)
        elif event_type == "stackTrace":
            self._handle_event_stacktrace(data)
        elif event_type == "variables":
            self._handle_event_variables(data)
        else:

            def _payload_output() -> dict[str, Any]:
                return {
                    "category": data.get("category", "console"),
                    "output": data.get("output", ""),
                    "source": data.get("source"),
                    "line": data.get("line"),
                    "column": data.get("column"),
                }

            dispatch: dict[str, tuple[Callable[[], dict[str, Any]], bool]] = {
                "output": (_payload_output, False),
                "continued": (
                    lambda: {
                        "threadId": data.get("threadId", 1),
                        "allThreadsContinued": data.get("allThreadsContinued", True),
                    },
                    True,
                ),
                "exception": (
                    lambda: {
                        "exceptionId": data.get("exceptionId", "Exception"),
                        "description": data.get("description", ""),
                        "breakMode": data.get("breakMode", "always"),
                        "threadId": data.get("threadId", 1),
                    },
                    True,
                ),
                "breakpoint": (
                    lambda: {
                        "reason": data.get("reason", "changed"),
                        "breakpoint": data.get("breakpoint", {}),
                    },
                    True,
                ),
                "module": (
                    lambda: {
                        "reason": data.get("reason", "new"),
                        "module": data.get("module", {}),
                    },
                    True,
                ),
                "process": (
                    lambda: {
                        "name": data.get("name", ""),
                        "systemProcessId": data.get("systemProcessId"),
                        "isLocalProcess": data.get("isLocalProcess", True),
                        "startMethod": data.get("startMethod", "launch"),
                    },
                    True,
                ),
                "loadedSource": (
                    lambda: {
                        "reason": data.get("reason", "new"),
                        "source": data.get("source", {}),
                    },
                    True,
                ),
            }

            if event_type is not None:
                handler = dispatch.get(event_type)
                if handler is not None:
                    payload_factory, immediate = handler
                    self._forward_event(event_type, payload_factory())

    def _resolve_pending_response(
        self, future: asyncio.Future[dict[str, Any]], data: dict[str, Any]
    ) -> None:
        """Resolve a pending response future on the correct loop."""
        current_loop = None
        with contextlib.suppress(RuntimeError):
            current_loop = asyncio.get_running_loop()

        def _resolve(fut: asyncio.Future[dict[str, Any]], payload: dict[str, Any]) -> None:
            if not fut.done():
                fut.set_result(payload)

        if current_loop is self.loop:
            if not future.done():
                try:
                    future.set_result(data)
                except Exception:
                    logger.debug("failed to set result on pending future")
            else:
                return

        try:
            self.loop.call_soon_threadsafe(_resolve, future, data)
        except Exception:
            logger.debug("failed to schedule resolution on debugger loop")
        else:
            return

        if not future.done():
            try:
                future.set_result(data)
            except Exception:
                logger.debug("direct set_result failed for pending future")
            else:
                return

    async def _handle_program_exit(self, exit_code: int) -> None:
        """Handle the debuggee program exit"""
        if self.program_running:
            self.program_running = False
            self.is_terminated = True

            await self.server.send_event("exited", {"exitCode": exit_code})
            await self.server.send_event("terminated")

    async def set_breakpoints(
        self, source: dict[str, Any] | str, breakpoints: list[dict[str, Any]]
    ) -> list[Any]:
        """Set breakpoints for a source file"""
        path = source if isinstance(source, str) else source.get("path")
        if not path:
            return [{"verified": False, "message": "Source path is required"} for _ in breakpoints]
        path = str(Path(path).resolve())

        bp_lines: list[dict[str, Any]] = [
            {
                "line": bp.get("line", 0),
                "condition": bp.get("condition"),
                "hitCondition": bp.get("hitCondition"),
                "logMessage": bp.get("logMessage"),
                "verified": True,
            }
            for bp in breakpoints
        ]

        self.breakpoints[path] = bp_lines

        if self.in_process and self._inproc is not None:
            try:
                result = self._inproc.set_breakpoints(path, bp_lines)
                return list(result)  # ensure a concrete list for the declared return type
            except Exception:
                logger.exception("in-process set_breakpoints failed")
                return [{"verified": False} for _ in bp_lines]
        if self.process and not self.is_terminated:
            bp_command = {
                "command": "setBreakpoints",
                "arguments": {
                    "source": {"path": path},
                    "breakpoints": bp_lines,
                },
            }
            # Emit a progress start event for longer running operations so
            # clients can show a spinner if they want. We keep this lightweight
            # and emit progress end once the command is sent.
            # build a reasonably unique progress id without touching other
            # properties that static analysis may not like
            try:
                progress_id = f"setBreakpoints:{path}:{int(time.time() * 1000)}"
            except Exception:
                progress_id = f"setBreakpoints:{path}"

            # schedule progressStart and progressEnd around the outgoing command
            self._schedule_coroutine(
                self.server.send_event(
                    "progressStart", {"progressId": progress_id, "title": "Setting breakpoints"}
                )
            )

            await self._send_command_to_debuggee(bp_command)

            # After sending the setBreakpoints command to the debuggee, forward
            # a breakpoint-changed event so clients can react to changes.
            try:
                bp_events = [
                    {"reason": "changed", "breakpoint": {"verified": bp.get("verified", True), "line": bp.get("line")}}
                    for bp in bp_lines
                ]
                for be in bp_events:
                    # forward as an adapter-level 'breakpoint' event
                    self._forward_event("breakpoint", be)
            except Exception:
                logger.debug("Failed to forward breakpoint events")

            # schedule a progressEnd
            self._schedule_coroutine(
                self.server.send_event(
                    "progressEnd", {"progressId": progress_id}
                )
            )

        return [{"verified": bp.get("verified", True)} for bp in bp_lines]

    async def set_function_breakpoints(
        self, breakpoints: list[dict[str, Any]]
    ) -> list[Any]:
        """Set breakpoints for functions"""
        bp_funcs = [
            {
                "name": bp.get("name", ""),
                "condition": bp.get("condition"),
                "hitCondition": bp.get("hitCondition"),
                "verified": True,
            }
            for bp in breakpoints
        ]

        self.function_breakpoints = bp_funcs

        if self.in_process and self._inproc is not None:
            try:
                result = self._inproc.set_function_breakpoints(bp_funcs)
                return list(result)
            except Exception:
                logger.exception("in-process set_function_breakpoints_failed")
                return [{"verified": False} for _ in breakpoints]
        if self.process and not self.is_terminated:
            bp_command = {
                "command": "setFunctionBreakpoints",
                "arguments": {"breakpoints": bp_funcs},
            }
            await self._send_command_to_debuggee(bp_command)

        return [{"verified": bp.get("verified", True)} for bp in bp_funcs]

    async def set_exception_breakpoints(self, filters: list[str]) -> list[Any]:
        """Set exception breakpoints"""
        self.exception_breakpoints_raised = "raised" in filters
        self.exception_breakpoints_uncaught = "uncaught" in filters

        if self.in_process and self._inproc is not None:
            try:
                result = self._inproc.set_exception_breakpoints(filters)
                return list(result)
            except Exception:
                logger.exception("in-process set_exception_breakpoints failed")
                return [{"verified": False} for _ in filters]
        if self.process and not self.is_terminated:
            bp_command = {
                "command": "setExceptionBreakpoints",
                "arguments": {"filters": filters},
            }
            await self._send_command_to_debuggee(bp_command)

        return [{"verified": True} for _ in filters]

    async def _send_command_to_debuggee(
        self, command: dict[str, Any], expect_response: bool = False
    ) -> dict[str, Any] | None:
        """Send a command to the debuggee process or in-process bridge."""
        if self.in_process and self._inproc is not None:
            return self._dispatch_inprocess_command(command, expect_response)

        if not self.process or self.is_terminated:
            return None

        try:
            command_id = None
            response_future = None

            if expect_response:
                command_id = self._next_command_id
                self._next_command_id += 1
                command["id"] = command_id
                try:
                    response_future = self.loop.create_future()
                except Exception:
                    response_future = asyncio.Future()

                with self.lock:
                    self._pending_commands[command_id] = response_future

            cmd_str = json.dumps(command)

            await asyncio.to_thread(self._write_command_to_channel, cmd_str)

            if expect_response and response_future:
                try:
                    response = await asyncio.wait_for(response_future, timeout=5.0)
                except asyncio.TimeoutError:
                    if command_id is not None:
                        self._pending_commands.pop(command_id, None)
                    return None
                else:
                    return response

        except Exception:
            logger.exception("Error sending command to debuggee")

        return None

    def _dispatch_inprocess_command(
        self, command: dict[str, Any], expect_response: bool
    ) -> Any | None:
        """Dispatch in-process commands through the bridge using a mapping."""
        try:
            cmd_key = command.get("command")
            args = command.get("arguments", {})
            bridge = self._inproc
            assert bridge is not None

            def _exception_info() -> Any:
                return {
                    "exceptionId": "Unknown",
                    "description": ("Exception information not available"),
                    "breakMode": "unhandled",
                    "details": {
                        "message": ("Exception information not available"),
                        "typeName": "Unknown",
                        "fullTypeName": "Unknown",
                        "source": "Unknown",
                        "stackTrace": ("Exception information not available"),
                    },
                }

            def _tid() -> int:
                return int(args.get("threadId", 1))

            def _cmd_next() -> Any:
                return bridge.next_(_tid())

            def _cmd_step_in() -> Any:
                return bridge.step_in(_tid())

            def _cmd_step_out() -> Any:
                return bridge.step_out(_tid())

            def _cmd_stack_trace() -> Any:
                return bridge.stack_trace(
                    _tid(),
                    args.get("startFrame", 0),
                    args.get("levels", 0),
                )

            def _cmd_variables() -> Any:
                return bridge.variables(
                    args.get("variablesReference"),
                    _filter=args.get("filter"),
                    _start=args.get("start"),
                    _count=args.get("count"),
                )

            def _cmd_set_variable() -> Any | None:
                return bridge.set_variable(
                    args.get("variablesReference"),
                    args.get("name"),
                    args.get("value"),
                )

            def _cmd_evaluate() -> Any:
                return bridge.evaluate(
                    args.get("expression", ""),
                    args.get("frameId", 0),
                    args.get("context", "hover"),
                )

            dispatch: dict[str, Callable[[], Any]] = {
                "continue": lambda: bridge.continue_(_tid()),
                "next": _cmd_next,
                "stepIn": _cmd_step_in,
                "stepOut": _cmd_step_out,
                "stackTrace": _cmd_stack_trace,
                "variables": _cmd_variables,
                "setVariable": _cmd_set_variable,
                "evaluate": _cmd_evaluate,
                "exceptionInfo": _exception_info,
                "configurationDone": lambda: None,
                "terminate": lambda: None,
                "pause": lambda: None,
            }

            key = cmd_key if isinstance(cmd_key, str) else ""
            body = dispatch.get(key, lambda: None)()
        except Exception:
            logger.exception("in-process command handling failed")
            if expect_response:
                return {"body": {}}
            return None
        else:
            if expect_response:
                return {"body": body or {}}
            return None

    def _write_command_to_channel(self, cmd_str: str) -> None:
        """Safely write a DBGCMD line to the active IPC or stdio channel."""
        if self._ipc_enabled and self._ipc_pipe_conn is not None:
            with contextlib.suppress(Exception):
                if self._ipc_binary:
                    self._ipc_pipe_conn.send_bytes(pack_frame(2, cmd_str.encode("utf-8")))
                else:
                    self._ipc_pipe_conn.send(f"DBGCMD:{cmd_str}")
            return
        if self._ipc_enabled and self._ipc_wfile is not None:
            with contextlib.suppress(Exception):
                if self._ipc_binary:
                    self._ipc_wfile.write(pack_frame(2, cmd_str.encode("utf-8")))  # type: ignore[arg-type]
                    self._ipc_wfile.flush()  # type: ignore[call-arg]
                else:
                    self._ipc_wfile.write(f"DBGCMD:{cmd_str}\n")  # type: ignore[arg-type]
                    self._ipc_wfile.flush()
            return

        stdin = getattr(self.process, "stdin", None)
        if self.process and stdin:
            with contextlib.suppress(Exception):
                stdin.write(f"DBGCMD:{cmd_str}\n")
                with contextlib.suppress(Exception):
                    stdin.flush()

    def _schedule_coroutine(self, obj: Any) -> None:
        """Schedule a coroutine, Future, or a factory producing one on the debugger loop."""

        def _submit() -> None:
            try:
                # ensure_future accepts coroutine or Future
                if inspect.iscoroutine(obj) or isinstance(obj, asyncio.Future):
                    task = asyncio.ensure_future(obj)
                    # keep a reference so it isn't GC'd prematurely
                    self._bg_tasks.add(task)
                    task.add_done_callback(self._bg_tasks.discard)
            except Exception:
                logger.debug("failed to schedule coroutine", exc_info=True)

        try:
            self.loop.call_soon_threadsafe(_submit)
        except Exception:
            logger.debug("failed to submit coroutine to loop", exc_info=True)

    async def continue_execution(self, thread_id: int) -> dict[str, Any]:
        """Continue execution of the specified thread"""
        if not self.program_running or self.is_terminated:
            return {"allThreadsContinued": False}

        self.stopped_event.clear()

        with self.lock:
            if thread_id in self.threads:
                self.threads[thread_id].is_stopped = False

        if self.in_process and self._inproc is not None:
            try:
                result = self._inproc.continue_(thread_id)
                return cast("dict[str, Any]", result)
            except Exception:
                logger.exception("in-process continue failed")
                return {"allThreadsContinued": False}
        command = {"command": "continue", "arguments": {"threadId": thread_id}}
        await self._send_command_to_debuggee(command)

        return {"allThreadsContinued": True}

    async def next(self, thread_id: int) -> None:
        """Step over to the next line"""
        if not self.program_running or self.is_terminated:
            return

        self.stopped_event.clear()

        if self.in_process and self._inproc is not None:
            try:
                self._inproc.next_(thread_id)
            except Exception:
                logger.exception("in-process next failed")
                return
        else:
            command = {"command": "next", "arguments": {"threadId": thread_id}}
            await self._send_command_to_debuggee(command)

    async def step_in(self, thread_id: int) -> None:
        """Step into a function"""
        if not self.program_running or self.is_terminated:
            return

        self.stopped_event.clear()

        if self.in_process and self._inproc is not None:
            try:
                self._inproc.step_in(thread_id)
            except Exception:
                logger.exception("in-process step_in failed")
                return
        else:
            command = {
                "command": "stepIn",
                "arguments": {"threadId": thread_id},
            }
            await self._send_command_to_debuggee(command)

    async def step_out(self, thread_id: int) -> None:
        """Step out of the current function"""
        if not self.program_running or self.is_terminated:
            return

        self.stopped_event.clear()

        if self.in_process and self._inproc is not None:
            try:
                self._inproc.step_out(thread_id)
            except Exception:
                logger.exception("in-process step_out failed")
                return
        else:
            command = {
                "command": "stepOut",
                "arguments": {"threadId": thread_id},
            }
            await self._send_command_to_debuggee(command)

    async def pause(self, thread_id: int) -> bool:
        """Pause execution of the specified thread"""
        if not self.program_running or self.is_terminated:
            return False

        if self.in_process and self._inproc is not None:
            return False
        command = {"command": "pause", "arguments": {"threadId": thread_id}}
        await self._send_command_to_debuggee(command)
        return True

    async def get_threads(self) -> list[dict[str, Any]]:
        """Get all threads"""
        threads = []
        with self.lock:
            for thread_id, thread in self.threads.items():
                threads.append({"id": thread_id, "name": thread.name})

        return threads

    def _is_python_source_file(self, filename: str | Path) -> bool:
        try:
            return str(filename).endswith((".py", ".pyw"))
        except Exception:
            return False

    def _resolve_path(self, filename: str | Path) -> Path | None:
        try:
            return Path(filename).resolve()
        except Exception:
            return None

    def _make_source(self, path: Path, origin: str, name: str | None = None) -> Source:
        src: dict[str, Any] = {
            "name": name or path.name,
            "path": str(path),
        }
        if origin:
            src["origin"] = origin
        return src  # type: ignore[return-value]

    def _try_add_source(
        self,
        seen_paths: set[str],
        loaded_sources: list[Source],
        filename: str | Path,
        *,
        origin: str = "",
        name: str | None = None,
        check_exists: bool = False,
    ) -> None:
        if not self._is_python_source_file(filename):
            return
        path = self._resolve_path(filename)
        if path is None or (abs_path := str(path)) in seen_paths:
            return
        if check_exists and not path.exists():
            return
        seen_paths.add(abs_path)
        loaded_sources.append(self._make_source(path, origin, name))

    def _iter_python_module_files(self):
        # Iterate over a snapshot to avoid 'dictionary changed size during iteration'
        # if imports occur while scanning.
        for module_name, module in list(sys.modules.items()):
            if module is None:
                continue
            try:
                module_file = getattr(module, "__file__", None)
                if not module_file:
                    continue
                path = self._resolve_path(module_file)
                if path is None or not self._is_python_source_file(path):
                    continue
                package = getattr(module, "__package__", None)
                origin = f"module:{package or module_name}"
                yield module_name, path, origin
            except Exception:
                continue

    async def get_loaded_sources(self) -> list[Source]:
        """Get all loaded source files"""
        loaded_sources: list[Source] = []
        seen_paths: set[str] = set()

        for _name, path, origin in self._iter_python_module_files():
            self._try_add_source(
                seen_paths,
                loaded_sources,
                path,
                origin=origin,
                name=path.name,
                check_exists=False,
            )

        for filename in list(linecache.cache.keys()):
            self._try_add_source(
                seen_paths,
                loaded_sources,
                filename,
                origin="linecache",
                check_exists=True,
            )

        if self.program_path:
            self._try_add_source(
                seen_paths,
                loaded_sources,
                self.program_path,
                origin="main",
                check_exists=True,
            )

        loaded_sources.sort(key=lambda s: s.get("name", ""))
        return loaded_sources

    async def get_modules(self) -> list[dict[str, Any]]:
        """Get all loaded Python modules"""
        all_modules = []

        for name, module in sys.modules.items():
            if module is None:
                continue

            module_id = str(id(module))

            path = None
            try:
                if hasattr(module, "__file__") and module.__file__:
                    path = module.__file__
            except Exception:
                pass

            is_user_code = False
            if path:
                is_user_code = (
                    not path.startswith(sys.prefix)
                    and not path.startswith(sys.base_prefix)
                    and "site-packages" not in path
                )

            module_obj = {
                "id": module_id,
                "name": name,
                "isUserCode": is_user_code,
            }
            if path:
                module_obj["path"] = path

            all_modules.append(module_obj)

        all_modules.sort(key=lambda m: m["name"])

        return all_modules

    async def get_stack_trace(
        self, thread_id: int, start_frame: int = 0, levels: int = 0
    ) -> dict[str, Any]:
        """Get stack trace for a thread"""
        if self.in_process and self._inproc is not None:
            try:
                result = self._inproc.stack_trace(thread_id, start_frame, levels)
                return cast("dict[str, Any]", result)
            except Exception:
                logger.exception("in-process stack_trace failed")
                return {"stackFrames": [], "totalFrames": 0}

        command = {
            "command": "stackTrace",
            "arguments": {
                "threadId": thread_id,
                "startFrame": start_frame,
                "levels": levels,
            },
        }

        response = await self._send_command_to_debuggee(command, expect_response=True)

        if response and "body" in response:
            return response["body"]

        stack_frames = []
        total_frames = 0

        with self.lock:
            if thread_id in self.current_stack_frames:
                frames = self.current_stack_frames[thread_id]
                total_frames = len(frames)

                if levels > 0:
                    end_frame = min(start_frame + levels, total_frames)
                    frames = frames[start_frame:end_frame]
                else:
                    frames = frames[start_frame:]

                stack_frames = frames

        return {"stackFrames": stack_frames, "totalFrames": total_frames}

    async def get_scopes(self, frame_id: int) -> list[dict[str, Any]]:
        """Get variable scopes for a stack frame"""
        var_ref = self.next_var_ref
        self.next_var_ref += 1

        global_var_ref = self.next_var_ref
        self.next_var_ref += 1

        self.var_refs[var_ref] = (frame_id, "locals")
        self.var_refs[global_var_ref] = (frame_id, "globals")

        return [
            {
                "name": "Local",
                "variablesReference": var_ref,
                "expensive": False,
            },
            {
                "name": "Global",
                "variablesReference": global_var_ref,
                "expensive": True,
            },
        ]

    async def get_variables(
        self,
        var_ref: int,
        filter_type: str | None = None,
        start: int = 0,
        count: int = 0,
    ) -> list[dict[str, Any]]:
        """Get variables for a scope or object"""
        if self.in_process and self._inproc is not None:
            try:
                body = self._inproc.variables(
                    var_ref,
                    _filter=filter_type,
                    _start=start if start else None,
                    _count=count if count else None,
                )
                return cast("list[dict[str, Any]]", body.get("variables", []))
            except Exception:
                logger.exception("in-process variables failed")
                return []

        command = {
            "command": "variables",
            "arguments": {"variablesReference": var_ref},
        }
        if filter_type:
            command["arguments"]["filter"] = filter_type
        if start > 0:
            command["arguments"]["start"] = start
        if count > 0:
            command["arguments"]["count"] = count

        response = await self._send_command_to_debuggee(command, expect_response=True)

        if response and "body" in response and "variables" in response["body"]:
            return response["body"]["variables"]

        variables = []
        with self.lock:
            if var_ref in self.var_refs and isinstance(self.var_refs[var_ref], list):
                variables = self.var_refs[var_ref]

        return cast("list[dict[str, Any]]", variables)

    async def set_variable(
        self,
        var_ref: int,
        name: str,
        value: str,
    ) -> dict[str, Any]:
        """Set a variable value in the specified scope."""
        with self.lock:
            if var_ref not in self.var_refs:
                msg = f"Invalid variable reference: {var_ref}"
                raise ValueError(msg)

            ref_info = self.var_refs[var_ref]

        scope_ref_tuple_len = 2
        if isinstance(ref_info, tuple) and len(ref_info) == scope_ref_tuple_len:
            frame_id, _scope_type = ref_info

            if self.in_process and self._inproc is not None:
                try:
                    result = self._inproc.set_variable(var_ref, name, value)
                    return cast("dict[str, Any]", result)
                except Exception:
                    logger.exception("in-process set_variable failed")
                    return {
                        "value": value,
                        "type": "string",
                        "variablesReference": 0,
                    }

            command = {
                "command": "setVariable",
                "arguments": {
                    "variablesReference": var_ref,
                    "name": name,
                    "value": value,
                },
            }

            response = await self._send_command_to_debuggee(command, expect_response=True)

            if response and "body" in response:
                return response["body"]

            return {
                "value": value,
                "type": "string",
                "variablesReference": 0,
            }

        msg = f"Cannot set variable in reference type: {type(ref_info)}"
        raise ValueError(msg)

    async def evaluate(
        self, expression: str, frame_id: int, context: str = "hover"
    ) -> dict[str, Any]:
        """Evaluate an expression in a specific context"""
        if self.in_process and self._inproc is not None:
            try:
                result = self._inproc.evaluate(expression, frame_id, context)
                return cast("dict[str, Any]", result)
            except Exception:
                logger.exception("in-process evaluate failed")
                return {
                    "result": f"<evaluation of '{expression}' not available>",
                    "type": "string",
                    "variablesReference": 0,
                }

        command = {
            "command": "evaluate",
            "arguments": {
                "expression": expression,
                "frameId": frame_id,
                "context": context,
            },
        }

        response = await self._send_command_to_debuggee(command, expect_response=True)

        if response and "body" in response:
            return response["body"]

        return {
            "result": f"<evaluation of '{expression}' not available>",
            "type": "string",
            "variablesReference": 0,
        }

    async def exception_info(self, thread_id: int) -> dict[str, Any]:
        """Get exception information for a thread"""
        command = {
            "command": "exceptionInfo",
            "arguments": {"threadId": thread_id},
        }

        response = await self._send_command_to_debuggee(command, expect_response=True)

        if response and "body" in response:
            return response["body"]

        exception_details = {
            "message": "Exception information not available",
            "typeName": "Unknown",
            "fullTypeName": "Unknown",
            "source": "Unknown",
            "stackTrace": "Exception information not available",
        }

        return {
            "exceptionId": "Unknown",
            "description": "Exception information not available",
            "breakMode": "unhandled",
            "details": exception_details,
        }

    async def get_exception_info(self, thread_id: int) -> dict[str, Any]:
        """Get exception information for a thread (convenience method)"""
        return await self.exception_info(thread_id)

    async def configuration_done_request(self) -> None:
        """Signal that configuration is done and debugging can start"""
        self.configuration_done.set()

        if not self.in_process:
            command = {"command": "configurationDone"}
            await self._send_command_to_debuggee(command)

    async def disconnect(self, terminate_debuggee: bool = False) -> None:
        """Disconnect from the debuggee"""
        if self.program_running:
            if terminate_debuggee and self.process:
                try:
                    await self.terminate()
                    await asyncio.sleep(0.5)
                    if self.process.poll() is None:
                        self.process.kill()
                except Exception:
                    logger.exception("Error terminating debuggee")

            self.program_running = False

        await self.shutdown()

    async def terminate(self) -> None:
        """Terminate the debuggee"""
        if self.in_process:
            try:
                self.is_terminated = True
                self.program_running = False
                await self.server.send_event("terminated")
            except Exception:
                logger.exception("in-process terminate failed")
            return

        if self.program_running and self.process:
            try:
                self.process.terminate()
                command = {"command": "terminate"}
                await self._send_command_to_debuggee(command)
                self.is_terminated = True
                self.program_running = False
            except Exception:
                logger.exception("Error sending terminate command")

    async def restart(self) -> None:
        """Request a session restart by signaling terminated(restart=true)."""
        try:
            await self.server.send_event("terminated", {"restart": True})
        except Exception:
            logger.exception("failed to send terminated(restart=true) event")

        try:
            if self.program_running and self.process:
                try:
                    self.process.terminate()
                except Exception:
                    logger.debug("process.terminate() failed during restart")
        except Exception:
            logger.debug("error during restart termination path")

        self.is_terminated = True
        self.program_running = False

        await self.shutdown()

    async def evaluate_expression(
        self, expression: str, frame_id: int, context: str = "hover"
    ) -> dict[str, Any]:
        """Evaluate an expression (alias for evaluate)"""
        return await self.evaluate(expression, frame_id, context)

    async def handle_debug_message(self, message) -> None:
        """Handle a debug protocol message (alias for _handle_debug_message)"""
        if isinstance(message, dict):
            message = json.dumps(message)
        self._handle_debug_message(message)

    async def handle_program_exit(self, exit_code: int) -> None:
        """Handle program exit (alias for _handle_program_exit)"""
        await self._handle_program_exit(exit_code)

    async def send_command_to_debuggee(self, command: str) -> None:
        """Send a raw command string to the debuggee"""
        if not self.process or self.is_terminated:
            msg = "No debuggee process"
            raise RuntimeError(msg)

        try:
            await asyncio.to_thread(
                lambda: self.process.stdin.write(f"DBGCMD:{command}\n")
                if self.process and self.process.stdin
                else None,
            )
        except Exception:
            logger.exception("Error sending command to debuggee")

    async def shutdown(self) -> None:  # noqa: PLR0912, PLR0915
        """Shut down the debugger and clean up resources."""

        # Helper methods used by shutdown to resolve pending futures robustly.
        # Keep these nested to make their intent clear and avoid polluting the class API.
        # NOTE: They intentionally prefer best-effort failure signaling over strict guarantees.

        # mypy/ruff complain about unknown attributes earlier, so we provide class-level helpers.

        # Set exception directly if the future is bound to the current loop
        def _shutdown_try_set_on_current_loop(
            fut: asyncio.Future,
            fut_loop: asyncio.AbstractEventLoop | None,
            current_loop: asyncio.AbstractEventLoop,
            cid: int,
        ) -> bool:
            if fut_loop is current_loop:
                if not fut.done():
                    try:
                        fut.set_exception(RuntimeError("Debugger shutdown"))
                    except Exception:
                        logger.debug("set_exception failed for %s on current loop", cid)
                return True
            return False

        # Fallback: attempt to use run_coroutine_threadsafe to signal failure
        def _shutdown_try_run_coroutine_threadsafe_on_loop(
            fut: asyncio.Future,
            fut_loop: asyncio.AbstractEventLoop | None,
            to_wait_cf: list[_CFuture],
            cid: int,
        ) -> bool:
            if fut_loop is not None and fut_loop.is_running():

                async def _mark_failed() -> None:
                    if not fut.done():
                        fut.set_exception(RuntimeError("Debugger shutdown"))

                try:
                    cfut = asyncio.run_coroutine_threadsafe(_mark_failed(), fut_loop)
                    to_wait_cf.append(cfut)
                except Exception:
                    logger.debug("run_coroutine_threadsafe failed for %s", cid)
                else:
                    return True
            return False

        # Last resort: schedule on debugger's own loop
        def _shutdown_schedule_on_debugger_loop(fut: asyncio.Future, cid: int) -> None:
            try:
                self.loop.call_soon_threadsafe(
                    lambda: (not fut.done())
                    and fut.set_exception(RuntimeError("Debugger shutdown"))
                )
            except Exception:
                logger.debug("failed scheduling on debugger loop for %s", cid)

        if self.loop:
            try:
                await self.loop.shutdown_asyncgens()
            except Exception:
                logger.debug("error during shutdown_asyncgens", exc_info=True)

            if getattr(self, "_owns_loop", False):
                try:
                    if self.loop.is_running():
                        self.loop.stop()
                except Exception:
                    logger.debug("error stopping owned loop", exc_info=True)
                try:
                    if not self.loop.is_closed():
                        self.loop.close()
                except Exception:
                    logger.debug("error closing owned loop", exc_info=True)

        try:
            tasks = list(self._bg_tasks)
            for t in tasks:
                t.cancel()
        except Exception:
            logger.debug("error cancelling background tasks")

        with self.lock:
            pending = dict(self._pending_commands)
            self._pending_commands.clear()

        # Track cross-loop completions using thread-safe concurrent futures
        to_wait_cf: list[_CFuture] = []

        current_loop = asyncio.get_running_loop()

        for cid, fut in pending.items():
            fut_loop = None
            try:
                fut_loop = fut.get_loop()
            except Exception:
                fut_loop = None

            logger.debug(
                "shutdown: failing future %s (loop=%r done=%s)",
                cid,
                fut_loop,
                fut.done(),
            )

            if _shutdown_try_set_on_current_loop(fut, fut_loop, current_loop, cid):
                continue

            if _shutdown_try_run_coroutine_threadsafe_on_loop(fut, fut_loop, to_wait_cf, cid):
                continue

            if not fut.done():
                try:
                    fut.set_exception(RuntimeError("Debugger shutdown"))
                except Exception:
                    logger.debug(
                        "direct set_exception failed for pending %s",
                        cid,
                    )
                else:
                    continue

            _shutdown_schedule_on_debugger_loop(fut, cid)

        if to_wait_cf:
            deadline = time.monotonic() + 0.25
            while time.monotonic() < deadline:
                if all(f.done() for f in to_wait_cf):
                    break
                try:
                    await asyncio.sleep(0.01)
                except Exception:
                    pass

        proc = self.process
        if proc is not None:
            try:
                with contextlib.suppress(Exception):
                    stdin = getattr(proc, "stdin", None)
                    if stdin is not None:
                        try:
                            stdin.close()
                        except Exception:
                            pass

                    stdout = getattr(proc, "stdout", None)
                    if stdout is not None:
                        try:
                            stdout.close()
                        except Exception:
                            pass

                    stderr = getattr(proc, "stderr", None)
                    if stderr is not None:
                        try:
                            stderr.close()
                        except Exception:
                            pass
            except Exception:
                logger.debug("error closing process stdio")

            try:
                self._cleanup_ipc_resources()
            except Exception:
                logger.debug("error cleaning up IPC resources during shutdown")

        self.var_refs.clear()
        self.threads.clear()
        self.breakpoints.clear()
        self.function_breakpoints.clear()
        self.current_stack_frames.clear()
        self.program_running = False
        self.is_terminated = True


class RequestHandler:
    """
    Handles incoming requests from the DAP client and routes them to the
    appropriate handler methods.
    """

    def __init__(self, server: DebugAdapterServer):
        self.server = server

    async def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """
        Handle a DAP request and return a response.
        """
        command = request["command"]
        handler_method = getattr(self, f"_handle_{command}", None)
        if handler_method is None:
            # Attempt snake_case fallback for camelCase DAP commands (e.g. setBreakpoints -> set_breakpoints)
            snake = re.sub(r"(?<!^)([A-Z])", r"_\1", command).lower()
            handler_method = getattr(self, f"_handle_{snake}", self._handle_unknown)
        return await handler_method(request)

    async def _handle_unknown(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle an unknown request command."""
        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": False,
            "command": request["command"],
            "message": f"Unsupported command: {request['command']}",
        }

    async def _handle_initialize(self, request: dict[str, Any]) -> None:
        """Handle initialize request."""
        # Directly send the response for initialize
        response = {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "initialize",
            "body": {
                "supportsConfigurationDoneRequest": True,
                "supportsFunctionBreakpoints": True,
                "supportsConditionalBreakpoints": True,
                "supportsHitConditionalBreakpoints": True,
                "supportsEvaluateForHovers": True,
                "exceptionBreakpointFilters": [
                    {
                        "filter": "raised",
                        "label": "Raised Exceptions",
                        "default": False,
                    },
                    {
                        "filter": "uncaught",
                        "label": "Uncaught Exceptions",
                        "default": True,
                    },
                ],
                "supportsStepInTargetsRequest": True,
                "supportsGotoTargetsRequest": True,
                "supportsCompletionsRequest": True,
                "supportsModulesRequest": True,
                "supportsLoadedSourcesRequest": True,
                "supportsRestartRequest": True,
                "supportsExceptionOptions": True,
                "supportsValueFormattingOptions": True,
                "supportsExceptionInfoRequest": True,
                "supportTerminateDebuggee": True,
                "supportsDelayedStackTraceLoading": True,
                "supportsLogPoints": True,
                "supportsSetVariable": True,
                "supportsSetExpression": True,
                "supportsDisassembleRequest": True,
                "supportsSteppingGranularity": True,
                "supportsInstructionBreakpoints": True,
                "supportsDataBreakpoints": True,
                "supportsDataBreakpointInfo": True,
            },
        }
        await self.server.send_message(response)
        # Send the initialized event
        await self.server.send_event("initialized")

    async def _handle_launch(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle launch request."""
        args = request.get("arguments", {})
        program = args.get("program")
        if not program:
            return {
                "type": "response",
                "request_seq": request["seq"],
                "success": False,
                "command": "launch",
                "message": "Missing required argument 'program'.",
            }

        program_args = args.get("args", [])
        stop_on_entry = args.get("stopOnEntry", False)
        no_debug = args.get("noDebug", False)
        in_process = args.get("inProcess", False)
        use_ipc = args.get("useIpc", False)
        use_binary_ipc = args.get("useBinaryIpc", False)
        # Optional IPC transport details (used only when useIpc is True)
        ipc_transport = args.get("ipcTransport")
        ipc_pipe_name = args.get("ipcPipeName")

        # Only include the in_process/use_ipc kwargs if explicitly enabled to
        # keep backward-compat tests (which assert four positional args) happy.
        if in_process or use_ipc:
            launch_kwargs: dict[str, Any] = {}
            if in_process:
                launch_kwargs["in_process"] = True
            if use_ipc:
                launch_kwargs["use_ipc"] = True
                if ipc_transport is not None:
                    launch_kwargs["ipc_transport"] = ipc_transport
                if ipc_pipe_name is not None:
                    launch_kwargs["ipc_pipe_name"] = ipc_pipe_name
                if use_binary_ipc:
                    launch_kwargs["use_binary_ipc"] = True

            await self.server.debugger.launch(
                program,
                program_args,
                stop_on_entry,
                no_debug,
                **launch_kwargs,
            )
        else:
            await self.server.debugger.launch(
                program,
                program_args,
                stop_on_entry,
                no_debug,
            )

        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "launch",
        }

    async def _handle_attach(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle attach request.

        MVP attach connects to an existing debuggee IPC endpoint.
        The client should specify useIpc and the endpoint coordinates
        (transport + host/port or path or pipe name).
        """
        args = request.get("arguments", {})

        use_ipc: bool = bool(args.get("useIpc", False))
        ipc_transport = args.get("ipcTransport")
        ipc_host = args.get("ipcHost")
        ipc_port = args.get("ipcPort")
        ipc_path = args.get("ipcPath")
        ipc_pipe_name = args.get("ipcPipeName")

        try:
            await self.server.debugger.attach(
                use_ipc=use_ipc,
                ipc_transport=ipc_transport,
                ipc_host=ipc_host,
                ipc_port=ipc_port,
                ipc_path=ipc_path,
                ipc_pipe_name=ipc_pipe_name,
            )
        except Exception as e:  # pragma: no cover - exercised by error tests
            logging.getLogger(__name__).exception("attach failed")
            return {
                "type": "response",
                "request_seq": request["seq"],
                "success": False,
                "command": "attach",
                "message": f"Attach failed: {e!s}",
            }

        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "attach",
        }

    async def _handle_set_breakpoints(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle setBreakpoints request."""
        args = request.get("arguments", {})
        source = args.get("source", {})
        path = source.get("path")
        breakpoints = args.get("breakpoints", [])

        verified_breakpoints = await self.server.debugger.set_breakpoints(path, breakpoints)

        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "setBreakpoints",
            "body": {"breakpoints": verified_breakpoints},
        }

    async def _handle_continue(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle continue request."""
        thread_id = request["arguments"]["threadId"]
        continued = await self.server.debugger.continue_execution(thread_id)
        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "continue",
            "body": {"allThreadsContinued": continued},
        }

    async def _handle_next(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle next request."""
        thread_id = request["arguments"]["threadId"]
        # Map DAP 'next' to debugger.step_over when available for tests,
        # otherwise fall back to debugger.next.
        step_over = getattr(self.server.debugger, "step_over", None)
        if callable(step_over):
            await cast("Callable[[int], Awaitable[Any]]", step_over)(thread_id)
        else:
            await self.server.debugger.next(thread_id)
        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "next",
        }

    async def _handle_step_in(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle stepIn request."""
        args = request["arguments"]
        thread_id = args["threadId"]
        target_id = args.get("targetId")
        # Pass targetId if provided for compatibility with tests
        step_in = self.server.debugger.step_in
        if target_id is not None:
            await cast("Callable[..., Awaitable[Any]]", step_in)(thread_id, target_id)
        else:
            await cast("Callable[..., Awaitable[Any]]", step_in)(thread_id)
        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "stepIn",
        }

    async def _handle_step_out(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle stepOut request."""
        thread_id = request["arguments"]["threadId"]
        await self.server.debugger.step_out(thread_id)
        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "stepOut",
        }

    async def _handle_pause(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle pause request by delegating to the debugger.pause method.

        Accepts an optional `threadId` argument per the DAP spec.
        """
        args = request.get("arguments", {}) or {}
        thread_id: int = args["threadId"]

        try:
            # Support sync or async implementations of pause()
            success = await self.server.debugger.pause(thread_id)

            return {
                "type": "response",
                "request_seq": request["seq"],
                "success": success,
                "command": "pause",
            }
        except Exception as e:  # pragma: no cover - defensive
            logger = logging.getLogger(__name__)
            logger.exception("Error handling pause request")
            return {
                "type": "response",
                "request_seq": request["seq"],
                "success": False,
                "command": "pause",
                "message": f"Pause failed: {e!s}",
            }

    async def _handle_disconnect(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle disconnect request."""
        await self.server.debugger.shutdown()
        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "disconnect",
        }

    async def _handle_terminate(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle terminate request - force terminate the debugged program."""
        try:
            await self.server.debugger.terminate()
            return {
                "type": "response",
                "request_seq": request["seq"],
                "success": True,
                "command": "terminate",
            }
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.exception("Error handling terminate request")
            return {
                "type": "response",
                "request_seq": request["seq"],
                "success": False,
                "command": "terminate",
                "message": f"Terminate failed: {e!s}",
            }

    async def _handle_restart(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle restart request.

        Semantics: terminate current debuggee and emit a terminated event with
        restart=true so the client restarts the session. Resources are cleaned
        up via the debugger's shutdown.
        """
        try:
            # Delegate to debugger which will send the terminated(restart=true)
            await self.server.debugger.restart()
            return {
                "type": "response",
                "request_seq": request["seq"],
                "success": True,
                "command": "restart",
            }
        except Exception as e:  # pragma: no cover - defensive
            logger = logging.getLogger(__name__)
            logger.exception("Error handling restart request")
            return {
                "type": "response",
                "request_seq": request["seq"],
                "success": False,
                "command": "restart",
                "message": f"Restart failed: {e!s}",
            }

    async def _handle_configurationDone(  # noqa: N802
        self, request: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle configurationDone request."""
        try:
            result = self.server.debugger.configuration_done_request()
            # Only await if it's an awaitable (tests may provide a plain Mock)
            if inspect.isawaitable(result):
                await result
            return {
                "type": "response",
                "request_seq": request["seq"],
                "success": True,
                "command": "configurationDone",
            }
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.exception("Error handling configurationDone request")
            return {
                "type": "response",
                "request_seq": request["seq"],
                "success": False,
                "command": "configurationDone",
                "message": f"Configuration done failed: {e!s}",
            }

    async def _handle_threads(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle threads request."""
        threads = await self.server.debugger.get_threads()
        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "threads",
            "body": {"threads": threads},
        }

    async def _handle_loaded_sources(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle loadedSources request."""
        loaded_sources = await self.server.debugger.get_loaded_sources()
        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "loadedSources",
            "body": {"sources": loaded_sources},
        }

    async def _handle_modules(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle modules request."""
        args = request.get("arguments", {})
        start_module = args.get("startModule", 0)
        module_count = args.get("moduleCount")

        # Get all loaded modules from the debugger
        all_modules = await self.server.debugger.get_modules()

        # Apply paging
        if module_count is not None:
            end_module = start_module + module_count
            modules = all_modules[start_module:end_module]
        else:
            modules = all_modules[start_module:]

        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "modules",
            "body": {"modules": modules, "totalModules": len(all_modules)},
        }

    async def _handle_stack_trace(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle stackTrace request."""
        args = request["arguments"]
        thread_id = args["threadId"]
        start_frame = args.get("startFrame", 0)
        levels = args.get("levels", 20)
        stack_frames = await self.server.debugger.get_stack_trace(thread_id, start_frame, levels)
        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "stackTrace",
            "body": {
                "stackFrames": stack_frames,
                "totalFrames": len(stack_frames),
            },
        }

    async def _handle_scopes(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle scopes request."""
        frame_id = request["arguments"]["frameId"]
        scopes = await self.server.debugger.get_scopes(frame_id)
        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "scopes",
            "body": {"scopes": scopes},
        }

    async def _handle_variables(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle variables request."""
        args = request["arguments"]
        variables_reference = args["variablesReference"]
        filter_ = args.get("filter")
        start = args.get("start")
        count = args.get("count")
        variables = await self.server.debugger.get_variables(
            variables_reference, filter_, start, count
        )
        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "variables",
            "body": {"variables": variables},
        }

    async def _handle_setVariable(  # noqa: N802
        self, request: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle setVariable request."""
        try:
            args = request["arguments"]
            variables_reference = args["variablesReference"]
            name = args["name"]
            value = args["value"]

            result = await self.server.debugger.set_variable(variables_reference, name, value)

            return {
                "type": "response",
                "request_seq": request["seq"],
                "success": True,
                "command": "setVariable",
                "body": result,
            }
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.exception("Error handling setVariable request")
            return {
                "type": "response",
                "request_seq": request["seq"],
                "success": False,
                "command": "setVariable",
                "message": f"Set variable failed: {e!s}",
            }

    async def _handle_evaluate(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle evaluate request."""
        args = request["arguments"]
        expression = args["expression"]
        frame_id = args.get("frameId")
        context = args.get("context")
        result = await self.server.debugger.evaluate(expression, frame_id, context)
        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "evaluate",
            "body": result,
        }

    async def _handle_dataBreakpointInfo(self, request: dict[str, Any]) -> dict[str, Any]:  # noqa: N802
        """Handle dataBreakpointInfo request (subset: variable name + frameId)."""
        args = request.get("arguments", {})
        name = args.get("name")
        frame_id = args.get("frameId")
        if name is None or frame_id is None:
            body = {
                "dataId": None,
                "description": "Data breakpoint unsupported for missing name/frameId",
                "accessTypes": ["write"],
                "canPersist": False,
            }
        else:
            body = self.server.debugger.data_breakpoint_info(name=name, frame_id=frame_id)
        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "dataBreakpointInfo",
            "body": body,
        }

    async def _handle_setDataBreakpoints(self, request: dict[str, Any]) -> dict[str, Any]:  # noqa: N802
        """Handle setDataBreakpoints request (full replace)."""
        args = request.get("arguments", {})
        bps = args.get("breakpoints", [])
        results = self.server.debugger.set_data_breakpoints(bps)
        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "setDataBreakpoints",
            "body": {"breakpoints": results},
        }

    async def _handle_exceptionInfo(  # noqa: N802
        self, request: ExceptionInfoRequest
    ) -> dict[str, Any]:
        """Handle exceptionInfo request."""
        try:
            args = request["arguments"]
            thread_id = args["threadId"]

            body = await self.server.debugger.get_exception_info(thread_id)

            return {
                "type": "response",
                "seq": 0,  # Will be set by protocol handler
                "request_seq": request["seq"],
                "success": True,
                "command": "exceptionInfo",
                "body": body,
            }
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.exception("Error handling exceptionInfo request")
            return {
                "type": "response",
                "seq": 0,  # Will be set by protocol handler
                "request_seq": request["seq"],
                "success": False,
                "command": "exceptionInfo",
                "message": f"exceptionInfo failed: {e!s}",
            }


class DebugAdapterServer:
    """
    Debug adapter server that communicates with a DAP client
    """

    def __init__(
        self,
        connection: ConnectionBase,
        loop: asyncio.AbstractEventLoop | None = None,
    ):
        self.connection = connection
        self.request_handler = RequestHandler(self)
        self.loop = loop or asyncio.get_event_loop()
        self.debugger = PyDebugger(self, self.loop)
        self.running = False
        self.sequence_number = 0
        self.protocol_handler = ProtocolHandler()

    @property
    def next_seq(self) -> int:
        """Get the next sequence number for messages"""
        self.sequence_number += 1
        return self.sequence_number

    async def start(self) -> None:
        """Start the debug adapter server"""
        try:
            await self.connection.accept()
            self.running = True
            await self._message_loop()
        except Exception:
            logger.exception("Error starting debug adapter")
            raise
        finally:
            await self._cleanup()

    async def stop(self) -> None:
        """Stop the debug adapter server"""
        logger.info("Stopping debug adapter server")
        self.running = False
        await self._cleanup()

    async def _cleanup(self) -> None:
        """Clean up resources"""
        if self.debugger:
            await self.debugger.shutdown()

        if self.connection and self.connection.is_connected:
            await self.connection.close()

    async def _message_loop(self) -> None:
        """Main message processing loop"""
        logger.info("Starting message processing loop")
        message: dict[str, Any] | None = None
        while self.running and self.connection.is_connected:
            try:
                message = await self.connection.read_message()
                if not message:
                    logger.info("Client disconnected")
                    break

                await self._process_message(message)
            except asyncio.CancelledError:
                logger.info("Message loop cancelled")
                break
            except Exception as e:
                logger.exception("Error processing message")
                # Send error response if this was a request
                if message is not None and ("type" in message and message["type"] == "request"):
                    await self.send_error_response(message, str(e))

        logger.info("Message loop ended")

    async def _process_message(self, message: dict[str, Any]) -> None:
        """Process an incoming DAP message"""
        if "type" not in message:
            logger.error("Invalid message, missing 'type': %s", message)
            return

        message_type = message["type"]

        if message_type == "request":
            await self._handle_request(message)
        elif message_type == "response":
            logger.warning("Received unexpected response: %s", message)
        elif message_type == "event":
            logger.warning("Received unexpected event: %s", message)
        else:
            logger.error("Unknown message type: %s", message_type)

    async def _handle_request(self, request: dict[str, Any]) -> None:
        """Handle an incoming DAP request"""
        if "command" not in request:
            logger.error("Invalid request, missing 'command': %s", request)
            return

        command = request["command"]
        logger.info("Handling request: %s (seq: %s)", command, request.get("seq", "?"))

        try:
            response = await self.request_handler.handle_request(request)
            if response:
                await self.send_message(response)
        except Exception as e:
            logger.exception("Error handling request %s", command)
            await self.send_error_response(request, str(e))

    async def send_message(self, message: dict[str, Any]) -> None:
        """Send a DAP message to the client"""
        if not self.connection or not self.connection.is_connected:
            logger.warning("Cannot send message: No active connection")
            return

        if "seq" not in message:
            message["seq"] = self.next_seq

        try:
            await self.connection.write_message(message)
        except Exception:
            logger.exception("Error sending message")

    async def send_response(
        self, request: dict[str, Any], body: dict[str, Any] | None = None
    ) -> None:
        """Send a success response to a request"""
        response = self.protocol_handler.create_response(cast("GenericRequest", request), True, body)
        await self.send_message(cast("dict[str, Any]", response))

    async def send_error_response(self, request: dict[str, Any], error_message: str) -> None:
        """Send an error response to a request"""
        response = self.protocol_handler.create_response(
            cast("GenericRequest", request), False, None, error_message
        )
        await self.send_message(cast("dict[str, Any]", response))

    async def send_event(self, event_name: str, body: dict[str, Any] | None = None) -> None:
        """Send an event to the client"""
        event = self.protocol_handler.create_event(event_name, body)
        await self.send_message(cast("dict[str, Any]", event))
