"""
Subprocess debugging manager for Dapper.

This module provides the infrastructure for automatically detecting and attaching
to child processes spawned by the debuggee. It works by monkey-patching Python's
subprocess/multiprocessing APIs to inject the dapper debug launcher into child
processes.

Architecture:
    1. When subprocess debugging is enabled, SubprocessManager patches:
       - subprocess.Popen
       - multiprocessing.Process
       - os.execv/execve (when running Python)

    2. Each child process is launched with dapper's debug_launcher prepended,
       configured to connect back to the parent's IPC server on a new port.

    3. The SubprocessManager notifies the VS Code extension via a custom event
       ('dapper/childProcess') so it can spawn a new debug session for the child.

Usage:
    manager = SubprocessManager(debugger, send_event, ipc_config)
    manager.enable()  # Patches subprocess APIs
    # ... debugging happens ...
    manager.disable()  # Restores original APIs

Status: PARTIAL — Phase 1 (`subprocess.Popen` Python children) is implemented.
    Phase 2+ integrations are scaffolded incrementally.
"""

from __future__ import annotations

from concurrent import futures
from contextlib import suppress
from dataclasses import dataclass
from dataclasses import field
import logging
import multiprocessing
import os
from pathlib import Path
import shlex
import subprocess
import sys
import threading
from typing import Callable
import uuid

logger = logging.getLogger(__name__)

PYTHON_INVOCATION_MIN_ARGS = 2


@dataclass
class ChildProcessInfo:
    """Information about a detected child process."""

    pid: int
    name: str
    ipc_port: int
    command: list[str]
    cwd: str | None = None
    env: dict[str, str] | None = None
    is_python: bool = False
    parent_pid: int = 0
    session_id: str | None = None
    parent_session_id: str | None = None


@dataclass
class SubprocessConfig:
    """Configuration for subprocess debugging."""

    enabled: bool = False
    auto_attach: bool = True
    max_children: int = 10
    ipc_host: str = "localhost"
    ipc_port_range: tuple[int, int] = (5700, 5799)
    debug_options: list[str] = field(default_factory=list)
    session_id: str | None = None
    parent_session_id: str | None = None
    enable_multiprocessing_scaffold: bool = True
    enable_process_pool_scaffold: bool = True


class SubprocessManager:
    """Manages detection and debugging of child processes.

    This manager can be installed on a running debugger to intercept
    subprocess creation and automatically attach the debugger to child
    processes.
    """

    def __init__(
        self,
        send_event: Callable[[str, dict], None],
        config: SubprocessConfig | None = None,
    ):
        self._send_event = send_event
        self._config = config or SubprocessConfig()
        self._children: dict[int, ChildProcessInfo] = {}
        self._next_port = self._config.ipc_port_range[0]
        self._lock = threading.Lock()
        self._enabled = False
        self._original_popen = None
        self._original_mp_process = None
        self._original_mp_process_start = None
        self._original_process_pool_submit = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def children(self) -> dict[int, ChildProcessInfo]:
        return dict(self._children)

    @property
    def config(self) -> SubprocessConfig:
        """Return subprocess manager configuration."""
        return self._config

    def is_python_command(self, args: list[str]) -> bool:
        """Public wrapper for Python command detection."""
        return self._is_python_command(args)

    def allocate_port(self) -> int:
        """Public wrapper for allocating an IPC port."""
        return self._allocate_port()

    def build_launcher_args(self, original_args: list[str], port: int) -> list[str]:
        """Public wrapper for launcher argument construction."""
        return self._build_launcher_args(original_args, port)

    def _analyze_python_invocation(self, args: list[str]) -> tuple[str, str, list[str]] | None:
        """Analyze a Python invocation into mode/value/rest tuple.

        Returns:
            ("program", script_path, trailing_args)
            ("module", module_name, trailing_args)
            ("code", code_string, trailing_args)
            or None if invocation shape is unsupported.
        """
        result: tuple[str, str, list[str]] | None = None
        if len(args) < PYTHON_INVOCATION_MIN_ARGS:
            return result

        index = 1
        while index < len(args) and result is None:
            current = args[index]

            if current == "--":
                if index + 1 < len(args):
                    result = ("program", args[index + 1], args[index + 2 :])
                break

            if current == "-m":
                if index + 1 < len(args):
                    result = ("module", args[index + 1], args[index + 2 :])
                break

            if current == "-c":
                if index + 1 < len(args):
                    result = ("code", args[index + 1], args[index + 2 :])
                break

            if current == "-":
                break

            if current.startswith("-"):
                index += 1
                continue

            result = ("program", current, args[index + 1 :])

        return result

    def enable(self) -> None:
        """Enable subprocess detection by patching subprocess APIs."""
        if self._enabled:
            return

        if not self._config.enabled:
            logger.debug("Subprocess debugging is disabled in config")
            return

        logger.info("Enabling subprocess debugging")
        self._patch_subprocess()
        if self._config.enable_multiprocessing_scaffold:
            self._patch_multiprocessing()
        if self._config.enable_process_pool_scaffold:
            self._patch_process_pool_executor()
        self._enabled = True

    def disable(self) -> None:
        """Disable subprocess detection and restore original APIs."""
        if not self._enabled:
            return

        logger.info("Disabling subprocess debugging")
        self._unpatch_process_pool_executor()
        self._unpatch_multiprocessing()
        self._unpatch_subprocess()
        self._enabled = False

    def _emit_candidate_event(self, *, source: str, name: str, target: str | None = None) -> None:
        self._send_event(
            "dapper/childProcessCandidate",
            {
                "source": source,
                "name": name,
                "target": target,
                "parentPid": os.getpid(),
                "sessionId": self._config.session_id,
                "parentSessionId": self._config.session_id,
                "autoAttachImplemented": False,
            },
        )

    def on_child_detected(self, info: ChildProcessInfo) -> None:
        """Called when a new child process is detected.

        Notifies the VS Code extension so it can start a new debug session.
        """
        with self._lock:
            if len(self._children) >= self._config.max_children:
                logger.warning(
                    f"Maximum child process limit ({self._config.max_children}) reached, "
                    f"ignoring child process {info.pid}"
                )
                return

            self._children[info.pid] = info

        logger.info(f"Child process detected: pid={info.pid}, name={info.name}")

        # Notify the extension
        self._send_event(
            "dapper/childProcess",
            {
                "pid": info.pid,
                "name": info.name,
                "ipcPort": info.ipc_port,
                "command": info.command,
                "cwd": info.cwd,
                "isPython": info.is_python,
                "parentPid": info.parent_pid,
                "sessionId": info.session_id,
                "parentSessionId": info.parent_session_id,
            },
        )

    def on_child_exited(self, pid: int) -> None:
        """Called when a child process exits."""
        with self._lock:
            child = self._children.pop(pid, None)

        if child:
            logger.info(f"Child process exited: pid={pid}, name={child.name}")
            self._send_event(
                "dapper/childProcessExited",
                {
                    "pid": pid,
                    "name": child.name,
                },
            )

    def _track_child_exit(self, popen_obj: object, pid: int) -> None:
        """Track a child process and emit an exited event when it terminates."""
        wait_fn = getattr(popen_obj, "wait", None)
        if not callable(wait_fn):
            return

        def _wait_and_notify() -> None:
            try:
                wait_fn()
            except Exception:
                logger.debug("Child wait failed for pid=%s", pid, exc_info=True)
            finally:
                self.on_child_exited(pid)

        threading.Thread(target=_wait_and_notify, daemon=True).start()

    def _allocate_port(self) -> int:
        """Allocate the next available IPC port for a child process."""
        with self._lock:
            port = self._next_port
            self._next_port += 1
            if self._next_port > self._config.ipc_port_range[1]:
                self._next_port = self._config.ipc_port_range[0]
            return port

    def _is_python_command(self, args: list[str]) -> bool:
        """Check if the command appears to be running a Python interpreter."""
        if not args:
            return False
        cmd = Path(args[0]).name.lower()
        return cmd in ("python", "python3", "python.exe", "python3.exe") or cmd.startswith(
            "python3."
        )

    def _build_launcher_args(self, original_args: list[str], port: int) -> list[str]:
        """Build the command line to launch a child process with dapper attached.

        Prepends the dapper debug_launcher module to the original command.
        """
        invocation = self._analyze_python_invocation(original_args)
        if invocation is None:
            return original_args

        return self._build_launcher_args_with_session(
            original_args,
            port,
            child_session_id=None,
            invocation=invocation,
        )

    def _build_launcher_args_with_session(
        self,
        original_args: list[str],
        port: int,
        *,
        child_session_id: str | None,
        invocation: tuple[str, str, list[str]] | None = None,
    ) -> list[str]:
        python_exe = original_args[0] if original_args else sys.executable

        parsed = invocation or self._analyze_python_invocation(original_args)
        if parsed is None:
            return original_args
        mode, entry_value, trailing_args = parsed

        launcher_args = [
            python_exe,
            "-m",
            "dapper.launcher.debug_launcher",
            "--ipc",
            "tcp",
            "--ipc-host",
            self._config.ipc_host,
            "--ipc-port",
            str(port),
            "--ipc-binary",
            "--subprocess",
        ]

        if mode == "program":
            launcher_args.extend(["--program", entry_value])
        elif mode == "module":
            launcher_args.extend(["--module", entry_value])
        elif mode == "code":
            launcher_args.extend(["--code", entry_value])
        else:
            return original_args

        if child_session_id:
            launcher_args.extend(["--session-id", child_session_id])
        if self._config.session_id:
            launcher_args.extend(["--parent-session-id", self._config.session_id])

        for arg in trailing_args:
            launcher_args.extend(["--arg", arg])

        return launcher_args

    def _patch_subprocess(self) -> None:
        """Monkey-patch subprocess.Popen to intercept child process creation.

        TODO: Implement the actual patching. This is a scaffold.
        """
        self._original_popen = subprocess.Popen.__init__

        original_init = self._original_popen
        is_python_command = self.is_python_command
        allocate_port = self.allocate_port
        analyze_invocation = self._analyze_python_invocation
        build_launcher_args_with_session = self._build_launcher_args_with_session
        on_child_detected = self.on_child_detected
        track_child_exit = self._track_child_exit
        config = self.config

        def patched_popen_init(self, args, *popen_rest, **kwargs):
            """Patched Popen.__init__ that intercepts Python subprocess creation."""
            if kwargs.get("shell"):
                original_init(self, args, *popen_rest, **kwargs)
                return

            # Convert args to list if string
            if isinstance(args, str):
                args_list = shlex.split(args)
            elif isinstance(args, (list, tuple)):
                args_list = list(args)
            else:
                args_list = [str(args)]

            if "dapper.launcher.debug_launcher" in args_list or "--subprocess" in args_list:
                original_init(self, args, *popen_rest, **kwargs)
                return

            if config.auto_attach and is_python_command(args_list):
                invocation = analyze_invocation(args_list)
                if invocation is None:
                    original_init(self, args, *popen_rest, **kwargs)
                    return

                port = allocate_port()
                child_session_id = uuid.uuid4().hex
                new_args = build_launcher_args_with_session(
                    args_list,
                    port,
                    child_session_id=child_session_id,
                    invocation=invocation,
                )
                logger.debug(f"Intercepted subprocess: {args_list} -> {new_args}")

                # Call original with modified args
                original_init(self, new_args, *popen_rest, **kwargs)

                # Notify about the new child
                child_info = ChildProcessInfo(
                    pid=self.pid,
                    name=Path(args_list[-1]).name if args_list else "unknown",
                    ipc_port=port,
                    command=args_list,
                    cwd=kwargs.get("cwd"),
                    is_python=True,
                    parent_pid=os.getpid(),
                    session_id=child_session_id,
                    parent_session_id=config.session_id,
                )
                on_child_detected(child_info)
                track_child_exit(self, child_info.pid)
            else:
                original_init(self, args, *popen_rest, **kwargs)

        subprocess.Popen.__init__ = patched_popen_init
        logger.debug("Patched subprocess.Popen")

    def _unpatch_subprocess(self) -> None:
        """Restore original subprocess.Popen."""

        if self._original_popen is not None:
            subprocess.Popen.__init__ = self._original_popen
            self._original_popen = None
            logger.debug("Restored subprocess.Popen")

    def _patch_multiprocessing(self) -> None:
        """Install experimental multiprocessing.Process.start interception.

        This Phase-2 scaffold emits candidate events but does not rewrite
        multiprocessing launch internals yet.
        """
        if self._original_mp_process_start is not None:
            return

        self._original_mp_process_start = multiprocessing.Process.start
        original_start = self._original_mp_process_start
        emit_candidate_event = self._emit_candidate_event

        def patched_process_start(self, *args, **kwargs):
            target_fn = getattr(self, "_target", None)
            target_name = getattr(target_fn, "__name__", None)
            proc_name = getattr(self, "name", "multiprocessing.Process")
            with suppress(Exception):
                emit_candidate_event(
                    source="multiprocessing.Process",
                    name=str(proc_name),
                    target=target_name,
                )
            return original_start(self, *args, **kwargs)

        multiprocessing.Process.start = patched_process_start
        logger.debug("Patched multiprocessing.Process.start (scaffold)")

    def _unpatch_multiprocessing(self) -> None:
        if self._original_mp_process_start is None:
            return
        with suppress(Exception):
            multiprocessing.Process.start = self._original_mp_process_start
            logger.debug("Restored multiprocessing.Process.start")
        self._original_mp_process_start = None

    def _patch_process_pool_executor(self) -> None:
        """Install experimental ProcessPoolExecutor.submit interception.

        This Phase-2 scaffold emits candidate events but does not yet perform
        child launch rewriting for executor workers.
        """
        if self._original_process_pool_submit is not None:
            return

        self._original_process_pool_submit = futures.ProcessPoolExecutor.submit
        original_submit = self._original_process_pool_submit
        emit_candidate_event = self._emit_candidate_event

        def patched_submit(executor_obj, fn, *args, **kwargs):
            fn_name = getattr(fn, "__name__", None)
            with suppress(Exception):
                emit_candidate_event(
                    source="concurrent.futures.ProcessPoolExecutor",
                    name="ProcessPoolExecutor",
                    target=fn_name,
                )
            return original_submit(executor_obj, fn, *args, **kwargs)

        futures.ProcessPoolExecutor.submit = patched_submit
        logger.debug("Patched ProcessPoolExecutor.submit (scaffold)")

    def _unpatch_process_pool_executor(self) -> None:
        if self._original_process_pool_submit is None:
            return
        with suppress(Exception):
            futures.ProcessPoolExecutor.submit = self._original_process_pool_submit
            logger.debug("Restored ProcessPoolExecutor.submit")
        self._original_process_pool_submit = None

    def cleanup(self) -> None:
        """Clean up all resources."""
        self.disable()
        with self._lock:
            self._children.clear()
