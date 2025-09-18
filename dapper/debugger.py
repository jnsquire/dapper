"""
Python debugger connection for the Debug Adapter Protocol.
Integrates with Python's built-in debugging capabilities through bdb and pdb.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import json
import linecache
import logging
import os
import socket as _socket
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import connection as mp_conn
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import Awaitable
from typing import Callable
from typing import cast

if TYPE_CHECKING:  # import for typing only to avoid runtime cycles
    from dapper.inprocess_debugger import InProcessDebugger
    from dapper.protocol_types import Source

    # Type alias for event handler functions
    EventPayloadFactory = Callable[[], dict[str, Any]]

logger = logging.getLogger(__name__)


class PyDebuggerThread:
    # Removed unused imports: Dict, List, Optional, inspect
    def __init__(self, thread_id: int, name: str):
        self.id = thread_id
        self.name = name
        self.frames = []
        self.is_stopped = False
        self.stop_reason = ""


class PyDebugger:
    """
    Main debugger class that integrates with Python's built-in debugging tools
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
    executor: ThreadPoolExecutor | None
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

        # Use provided loop or create a new one if none is running
        if loop is not None:
            self.loop = loop
        else:
            try:
                self.loop = asyncio.get_running_loop()
            except RuntimeError:
                self.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self.loop)

        # Core state
        self.threads: dict[int, PyDebuggerThread] = {}
        self.main_thread_id: int | None = None
        self.next_thread_id = 1
        self.next_var_ref = 1000
        self.var_refs: dict[int, object] = {}
        self.breakpoints: dict[str, list[dict]] = {}
        self.function_breakpoints: list[dict[str, Any]] = []
        # Exception breakpoint flags (two booleans for clarity)
        self.exception_breakpoints_uncaught = False
        self.exception_breakpoints_raised = False
        self.process = None
        self.debugger_thread = None
        self.is_terminated = False
        self.executor = ThreadPoolExecutor(max_workers=1)
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
        self._ipc_pipe_listener: mp_conn.Listener | None = None
        self._ipc_pipe_conn: mp_conn.Connection | None = None
        self._ipc_unix_path: Path | None = None

        # Data breakpoint containers
        self._data_watches = {}
        self._frame_watches = {}

    # ------------------------------------------------------------------
    # Data Breakpoint (Watchpoint) Support (Phase 1: bookkeeping only)
    # ------------------------------------------------------------------
    def data_breakpoint_info(self, *, name: str, frame_id: int) -> dict[str, Any]:
        """Return minimal data breakpoint info for a variable in a frame.

        We currently always return a writable watch descriptor. A dataId is
        synthesized from the frame and variable name. No validation that the
        frame exists is performed yet (future enhancement: map frame ids to
        actual frames when stackTrace responses are cached).
        """
        data_id = f"frame:{frame_id}:var:{name}"
        return {
            "dataId": data_id,
            "description": f"Variable '{name}' in frame {frame_id}",
            "accessTypes": ["write"],
            "canPersist": False,
        }

    def set_data_breakpoints(self, breakpoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Register a set of data breakpoints.

        Each breakpoint dict should contain a 'dataId'. Optional fields:
        condition, hitCondition, accessType. We store them verbatim. At this
        phase we do not yet evaluate or trigger stops; that will be added
        when integrating with line execution hooks.
        """
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
                # append tuple (name, meta dict reference) so hits update shared
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
            logger = logging.getLogger(__name__)
            logger.debug("Failed bridging data watches to BDB", exc_info=True)
        return results

    # Placeholder for future change detection hook
    def _check_data_watches_for_frame(self, frame_id: int, frame_locals: dict[str, Any]) -> None:  # noqa: ARG002
        """(Future) Detect variable changes for watches tied to frame_id.

        Phase 1: No-op. Phase 2 will compare cached last values and emit
        stopped events when changes are detected.
        """
        return

    def _schedule_coroutine(self, coro: Callable[[], Awaitable[Any]] | Awaitable[Any]) -> None:
        """Schedule a callable or awaitable on the debugger's event loop.

        Accepts either:
        - a zero-argument callable that returns an awaitable when called, or
        - an awaitable/coroutine object.

        The callable form ensures coroutine objects are only created on the
        debugger's loop thread, preventing 'coroutine was never awaited'
        warnings when tests pass lightweight awaitables.
        """
        current_loop = None
        with contextlib.suppress(RuntimeError):
            current_loop = asyncio.get_running_loop()

        is_callable = callable(coro)

        # small helper that always creates a Task on the supplied loop
        def _create_task_on_loop(
            loop: asyncio.AbstractEventLoop, awaitable: Awaitable[Any]
        ) -> None:
            try:
                if asyncio.iscoroutine(awaitable):
                    task = loop.create_task(awaitable)
                else:

                    async def _wrap(a: Awaitable[Any]) -> Any:
                        """Tiny wrapper to await non-coroutine awaitables."""
                        return await a

                    task = loop.create_task(_wrap(awaitable))

                self._bg_tasks.add(task)
                task.add_done_callback(self._bg_tasks.discard)
            except Exception:
                logger.debug("_create_task_on_loop: failed")

        if current_loop is self.loop:
            try:
                awaitable = (
                    cast("Callable[[], Awaitable[Any]]", coro)()
                    if is_callable
                    else cast("Awaitable[Any]", coro)
                )
                _create_task_on_loop(self.loop, awaitable)
            except Exception:
                logger.debug("_schedule_coroutine: failed on-loop")
            return

        # Create awaitable on the debugger loop via call_soon_threadsafe
        def _runner() -> None:
            try:
                awaitable = (
                    cast("Callable[[], Awaitable[Any]]", coro)()
                    if is_callable
                    else cast("Awaitable[Any]", coro)
                )
                _create_task_on_loop(self.loop, awaitable)
            except Exception:
                logger.debug("_schedule_coroutine: runner failed")

        try:
            self.loop.call_soon_threadsafe(_runner)
        except Exception:
            # Fallback: use run_coroutine_threadsafe and wrap
            # non-coroutines
            try:
                awaitable = (
                    cast("Callable[[], Awaitable[Any]]", coro)()
                    if is_callable
                    else cast("Awaitable[Any]", coro)
                )
                if asyncio.iscoroutine(awaitable):
                    asyncio.run_coroutine_threadsafe(awaitable, self.loop)
                else:

                    async def _wrap(a: Awaitable[Any]) -> Any:
                        return await a

                    asyncio.run_coroutine_threadsafe(_wrap(awaitable), self.loop)
            except Exception:
                logger.debug("_schedule_coroutine: scheduling failed")

    def _forward_event(
        self, event_name: str, payload: dict[str, Any], immediate: bool = False
    ) -> None:
        """Forward an event to the client, delaying awaitable creation when
        possible so coroutine objects are allocated on the debugger loop.
        """
        if immediate:
            # Tests may rely on synchronous recorder calls; create the
            # awaitable now and schedule it.
            self._schedule_coroutine(self.server.send_event(event_name, payload))
        else:
            # Defer creating the awaitable until scheduled on the loop.
            self._schedule_coroutine(lambda: self.server.send_event(event_name, payload))

    async def launch(
        self,
        program: str,
        args: list[str] | None = None,
        stop_on_entry: bool = False,
        no_debug: bool = False,
        in_process: bool = False,
        use_ipc: bool = False,
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
        # We'll use a special debug mode that integrates with our adapter
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
        if self._use_ipc:
            self._prepare_ipc_listener(ipc_transport, ipc_pipe_name, debug_args)

        logger.info("Launching program: %s", self.program_path)
        logger.debug("Debug command: %s", " ".join(debug_args))

        # Start the subprocess in a worker thread to avoid blocking.
        # In test mode we run it in a real background thread to mimic the
        # production behavior without involving the event loop's
        # run_in_executor (which can create cross-loop Future issues in
        # the test harness).
        if getattr(self, "_test_mode", False):
            threading.Thread(
                target=self._start_debuggee_process,
                args=(debug_args,),
                daemon=True,
            ).start()
        else:
            await self.loop.run_in_executor(
                self.executor, self._start_debuggee_process, debug_args
            )

        # If IPC is enabled, accept the connection from the launcher and
        # start a reader thread for DBGP messages coming over the socket.
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
        # Lazy import via importlib to avoid static import-in-function lint
        try:
            module = importlib.import_module("dapper.inprocess_debugger")
            # mypy: attribute defined on module at runtime
            # type: ignore[attr-defined] - attribute defined at runtime
            _inproc_cls = module.InProcessDebugger
        except Exception as exc:  # pragma: no cover - defensive import
            msg = f"In-process debugging not available: {exc!s}"
            raise RuntimeError(msg) from exc

        self.in_process = True
        self._inproc = _inproc_cls()

        # Callback shims to reuse existing event handlers
        def _on_stopped(data: dict[str, Any]) -> None:
            try:
                self._handle_event_stopped(data)
            except Exception:
                logger.exception("error in on_stopped callback")

        def _on_thread(data: dict[str, Any]) -> None:
            try:
                self._handle_event_thread(data)
            except Exception:
                logger.exception("error in on_thread callback")

        def _on_exited(data: dict[str, Any]) -> None:
            try:
                self._handle_event_exited(data)
            except Exception:
                logger.exception("error in on_exited callback")

        def _on_output(category: str, output: str) -> None:
            try:
                self._forward_event("output", {"category": category, "output": output})
            except Exception:
                logger.exception("error in on_output callback")

        # Direct attribute assignment
        self._inproc.on_stopped = _on_stopped  # type: ignore[attr-defined]
        self._inproc.on_thread = _on_thread  # type: ignore[attr-defined]
        self._inproc.on_exited = _on_exited  # type: ignore[attr-defined]
        self._inproc.on_output = _on_output  # type: ignore[attr-defined]

        # Mark running and emit process event for current interpreter
        self.program_running = True
        proc_event = {
            "name": Path(self.program_path or "").name,
            "systemProcessId": os.getpid(),
            "isLocalProcess": True,
            "startMethod": "launch",
        }
        await self.server.send_event("process", proc_event)

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
        """Attach to an already running debuggee.

        MVP: Connect to an existing IPC endpoint exposed by the launcher.
        """
        # In-process attach is out of scope for MVP (would require hooks).
        if not use_ipc:
            msg = "attach without useIpc is not supported yet"
            raise RuntimeError(msg)

        default_transport = "pipe" if os.name == "nt" else "unix"
        transport = (ipc_transport or default_transport).lower()

        # Connect based on transport.
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
                        if line.startswith("DBGP:"):
                            self._handle_debug_message(line[5:].strip())
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
                        if line.startswith("DBGP:"):
                            self._handle_debug_message(line[5:].strip())
                finally:
                    self._ipc_enabled = False
                    self._cleanup_ipc_resources()

            threading.Thread(target=_reader_tcp, daemon=True).start()
        else:
            msg = f"unsupported attach transport: {transport}"
            raise RuntimeError(msg)

        # Mark running and send a generic process event; actual details will
        # arrive via events from the debuggee.
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
        """Prepare IPC listener resources and extend debug_args with
        coordinates for the launcher. Chooses platform defaults when
        transport is not specified and falls back safely.
        """
        # Platform default: Windows=pipe, else=unix
        default_transport = "pipe" if os.name == "nt" else "unix"
        transport = (ipc_transport or default_transport).lower()

        if os.name == "nt" and transport == "pipe":
            # Pick a pipe name if none given
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

        # Non-Windows or non-pipe: try AF_UNIX first when requested
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
                # store Path for easier cleanup
                self._ipc_unix_path = unix_path
                debug_args.extend(["--ipc", "unix", "--ipc-path", str(unix_path)])
                return

        # TCP fallback (cross-platform)
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
        self._ipc_rfile = conn2.makefile("r", encoding="utf-8", newline="")
        self._ipc_wfile = conn2.makefile("w", encoding="utf-8", newline="")
        self._ipc_enabled = True
        while True:
            line = self._ipc_rfile.readline()  # type: ignore[union-attr]
            if not line:
                break
            if line.startswith("DBGP:"):
                self._handle_debug_message(line[5:].strip())

    def _cleanup_ipc_resources(self) -> None:
        """Close IPC resources quietly and clean up files."""
        # Close file wrappers
        for f in (self._ipc_rfile, self._ipc_wfile):
            with contextlib.suppress(Exception):
                f.close()  # type: ignore[union-attr]

        # Close sockets/listeners
        with contextlib.suppress(Exception):
            if self._ipc_sock is not None:
                self._ipc_sock.close()
        with contextlib.suppress(Exception):
            if self._ipc_listen_sock is not None:
                self._ipc_listen_sock.close()

        # Remove UNIX domain socket path
        with contextlib.suppress(Exception):
            if self._ipc_unix_path:
                self._ipc_unix_path.unlink()

        # Close pipe endpoints
        with contextlib.suppress(Exception):
            if self._ipc_pipe_conn is not None:
                self._ipc_pipe_conn.close()
        with contextlib.suppress(Exception):
            if self._ipc_pipe_listener is not None:
                self._ipc_pipe_listener.close()

    def _start_debuggee_process(self, debug_args: list[str]) -> None:
        """
        Start the debuggee process in a separate thread
        """
        try:
            # Start the process with pipes for communication
            self.process = subprocess.Popen(
                debug_args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

            # Start threads to read from stdout and stderr
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

            # Wait for process to exit
            exit_code = self.process.wait()

            # Program has terminated
            if not self.is_terminated:
                self.is_terminated = True

            # Schedule program exit handler on the debugger loop
            self._schedule_coroutine(lambda ec=exit_code: self._handle_program_exit(ec))
        except Exception:
            logger.exception("Error starting debuggee")
            self.is_terminated = True
            # Schedule program exit handler on the debugger loop
            self._schedule_coroutine(lambda ec=1: self._handle_program_exit(ec))

    def _read_output(self, stream, category: str) -> None:
        """Read output from the debuggee's stdout/stderr streams"""
        try:
            while True:
                line = stream.readline()
                if not line:
                    break

                # Check if this is a debug message or regular output
                if line.startswith("DBGP:"):
                    # Process debug protocol message
                    self._handle_debug_message(line[5:].strip())
                else:
                    # Send as regular output to the client
                    # Schedule send_event coroutine on the debugger loop
                    self._schedule_coroutine(
                        lambda out=line: self.server.send_event(
                            "output",
                            {"category": category, "output": out},
                        )
                    )
        except Exception:
            # Use exception() to include traceback
            logger.exception("Error reading %s", category)

    def _handle_event_stopped(self, data: dict[str, Any]) -> None:
        """Handle a stopped event's local state updates and forwarding."""
        thread_id = data.get("threadId", 1)
        reason = data.get("reason", "breakpoint")

        # Update thread state
        with self.lock:
            if thread_id not in self.threads:
                thread_name = f"Thread {thread_id}"
                self.threads[thread_id] = PyDebuggerThread(thread_id, thread_name)
            self.threads[thread_id].is_stopped = True
            self.threads[thread_id].stop_reason = reason

        # Create the stopped event
        stop_event = {
            "reason": reason,
            "threadId": thread_id,
            "allThreadsStopped": data.get("allThreadsStopped", True),
        }
        if "text" in data:
            stop_event["text"] = data["text"]

        # Signal that we've stopped. Ensure we call Event.set() on the
        # Signal that we've stopped. Set synchronously so callers and
        # tests observe the change immediately. For cross-thread safety
        # this is best-effort — set() is idempotent and safe to call.
        try:
            self.stopped_event.set()
        except Exception:
            # Fallback: schedule on the loop if direct set fails
            try:
                self.loop.call_soon_threadsafe(self.stopped_event.set)
            except Exception:
                with contextlib.suppress(Exception):
                    self.stopped_event.set()

        # Forward the stopped event: call send_event synchronously so
        # test-side recorders see the call immediately, then schedule
        # the returned awaitable on the debugger loop.
        awaitable = self.server.send_event("stopped", stop_event)
        # If the server returned an awaitable, schedule it on the loop.
        if awaitable is not None:
            self._schedule_coroutine(lambda: awaitable)

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

        # Forward immediately so test-side recorders see the call
        self._forward_event("thread", {"reason": reason, "threadId": thread_id}, immediate=True)

    def _handle_event_exited(self, data: dict[str, Any]) -> None:
        """Handle debuggee exited event and schedule cleanup."""
        exit_code = data.get("exitCode", 0)
        self.is_terminated = True
        self.program_running = False
        # Schedule the program exit handler on the debugger loop
        self._schedule_coroutine(lambda ec=exit_code: self._handle_program_exit(ec))

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
        """Handle a debug protocol message from the debuggee.

        Args:
            message: JSON-encoded debug message containing command responses or events
        """
        try:
            data: dict[str, Any] = json.loads(message)
        except Exception:
            logger.exception("Error handling debug message")
            return

        # Check if this is a command response and handle it via helper.
        command_id = data.get("id")
        if command_id is not None and command_id in self._pending_commands:
            with self.lock:
                future = self._pending_commands.pop(command_id, None)

            if future is not None:
                self._resolve_pending_response(future, data)
            return

        # Otherwise, handle as an event
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
            # For many events we simply forward a payload to the client.
            # Use a small dispatch map to reduce branching and keep the
            # behavior identical to the previous explicit branches.
            def _payload_output() -> dict[str, Any]:
                return {
                    "category": data.get("category", "console"),
                    "output": data.get("output", ""),
                    "source": data.get("source"),
                    "line": data.get("line"),
                    "column": data.get("column"),
                }

            dispatch: dict[str, tuple[EventPayloadFactory, bool]] = {
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
                    self._forward_event(event_type, payload_factory(), immediate)
        # Remaining event handling falls through to the rest of the method

    def _resolve_pending_response(
        self, future: asyncio.Future[dict[str, Any]], data: dict[str, Any]
    ) -> None:
        """Resolve a pending response future on the correct loop.

        Args:
            future: The future to resolve with the response data
            data: The response data to set on the future
        """
        current_loop = None
        with contextlib.suppress(RuntimeError):
            current_loop = asyncio.get_running_loop()

        def _resolve(fut: asyncio.Future[dict[str, Any]], payload: dict[str, Any]) -> None:
            if not fut.done():
                fut.set_result(payload)

        if current_loop is self.loop:
            # Directly set the result — keep try small
            if not future.done():
                try:
                    future.set_result(data)
                except Exception:
                    logger.debug("failed to set result on pending future")
            else:
                # already done; nothing to do
                return

        # Try scheduling on the debugger loop
        try:
            self.loop.call_soon_threadsafe(_resolve, future, data)
        except Exception:
            logger.debug("failed to schedule resolution on debugger loop")
        else:
            return

        # Best-effort fallback: try to set directly
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

            # Send exited event
            await self.server.send_event("exited", {"exitCode": exit_code})

            # Send terminated event
            await self.server.send_event("terminated")

    async def set_breakpoints(
        self, source: dict[str, Any] | str, breakpoints: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Set breakpoints for a source file"""
        path = source if isinstance(source, str) else source.get("path")
        if not path:
            return [
                {"verified": False, "message": "Source path is required"} for _ in breakpoints
            ]  # Convert to canonical path
        path = str(Path(path).resolve())

        # Create list of breakpoints with line numbers
        bp_lines = [
            {
                "line": bp.get("line", 0),
                "condition": bp.get("condition"),
                "hitCondition": bp.get("hitCondition"),
                "logMessage": bp.get("logMessage"),
                "verified": True,
            }
            for bp in breakpoints
        ]

        # Store the breakpoints for this file
        self.breakpoints[path] = bp_lines

        # Send breakpoint update in the appropriate mode
        if self.in_process and self._inproc is not None:
            try:
                return self._inproc.set_breakpoints(path, bp_lines)
            except Exception:
                logger.exception("in-process set_breakpoints failed")
                return [{"verified": False} for _ in bp_lines]
        # Subprocess mode: forward to debuggee
        if self.process and not self.is_terminated:
            bp_command = {
                "command": "setBreakpoints",
                "arguments": {
                    "source": {"path": path},
                    "breakpoints": bp_lines,
                },
            }
            await self._send_command_to_debuggee(bp_command)

        # Return verified breakpoints
        return [{"verified": bp.get("verified", True)} for bp in bp_lines]

    async def set_function_breakpoints(
        self, breakpoints: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
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

        # Store function breakpoints
        self.function_breakpoints = bp_funcs

        # Send function breakpoint update in appropriate mode
        if self.in_process and self._inproc is not None:
            try:
                return self._inproc.set_function_breakpoints(bp_funcs)
            except Exception:
                logger.exception("in-process set_function_breakpoints failed")
                return [{"verified": False} for _ in breakpoints]
        if self.process and not self.is_terminated:
            bp_command = {
                "command": "setFunctionBreakpoints",
                "arguments": {"breakpoints": bp_funcs},
            }
            await self._send_command_to_debuggee(bp_command)

        # Return verified breakpoints
        return [{"verified": bp.get("verified", True)} for bp in bp_funcs]

    async def set_exception_breakpoints(self, filters: list[str]) -> list[dict[str, Any]]:
        """Set exception breakpoints"""
        # Update exception breakpoint flags
        self.exception_breakpoints_raised = "raised" in filters
        self.exception_breakpoints_uncaught = "uncaught" in filters

        # Send exception breakpoint update in appropriate mode
        if self.in_process and self._inproc is not None:
            try:
                return self._inproc.set_exception_breakpoints(filters)
            except Exception:
                logger.exception("in-process set_exception_breakpoints failed")
                return [{"verified": False} for _ in filters]
        if self.process and not self.is_terminated:
            bp_command = {
                "command": "setExceptionBreakpoints",
                "arguments": {"filters": filters},
            }
            await self._send_command_to_debuggee(bp_command)

        # Return verified breakpoints
        return [{"verified": True} for _ in filters]

    async def _send_command_to_debuggee(
        self, command: dict[str, Any], expect_response: bool = False
    ) -> dict[str, Any] | None:
        """Send a command to the debuggee process"""
        # In-process path: map commands directly to bridge APIs
        if self.in_process and self._inproc is not None:
            return self._dispatch_inprocess_command(command, expect_response)

        if not self.process or self.is_terminated:
            return None

        try:
            # Assign a command ID if we expect a response
            command_id = None
            response_future = None

            if expect_response:
                command_id = self._next_command_id
                self._next_command_id += 1
                command["id"] = command_id
                # Create the Future bound to the debugger loop to avoid
                # cross-loop issues and register it under the lock.
                try:
                    response_future = self.loop.create_future()
                except Exception:
                    response_future = asyncio.Future()

                with self.lock:
                    self._pending_commands[command_id] = response_future

            # Convert command to a string and send to IPC (when enabled)
            cmd_str = json.dumps(command)

            # Use run_in_executor to avoid blocking the event loop
            await self.loop.run_in_executor(
                self.executor, lambda: self._write_command_to_channel(cmd_str)
            )

            # If we expect a response, wait for it
            if expect_response and response_future:
                try:
                    # Wait for response with timeout
                    response = await asyncio.wait_for(response_future, timeout=5.0)
                except asyncio.TimeoutError:
                    # Clean up the pending command on timeout
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
    ) -> dict[str, Any] | None:
        """Dispatch in-process commands through the bridge using a mapping
        to reduce branching. Returns a response body dict when requested.
        """
        try:
            cmd_key = command.get("command")
            args = command.get("arguments", {})
            bridge = self._inproc
            assert bridge is not None

            def _exception_info() -> dict[str, Any]:
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

            def _cmd_next() -> None:
                bridge.next_(_tid())

            def _cmd_step_in() -> None:
                bridge.step_in(_tid())

            def _cmd_step_out() -> None:
                bridge.step_out(_tid())

            def _cmd_stack_trace() -> dict[str, Any]:
                return bridge.stack_trace(
                    _tid(),
                    args.get("startFrame", 0),
                    args.get("levels", 0),
                )

            def _cmd_variables() -> dict[str, Any]:
                return bridge.variables(
                    args.get("variablesReference"),
                    _filter=args.get("filter"),
                    _start=args.get("start"),
                    _count=args.get("count"),
                )

            def _cmd_set_variable() -> dict[str, Any] | None:
                return bridge.set_variable(
                    args.get("variablesReference"),
                    args.get("name"),
                    args.get("value"),
                )

            def _cmd_evaluate() -> dict[str, Any]:
                return bridge.evaluate(
                    args.get("expression", ""),
                    args.get("frameId", 0),
                    args.get("context", "hover"),
                )

            dispatch: dict[str, Callable[[], dict[str, Any] | None]] = {
                "continue": lambda: bridge.continue_(_tid()),
                "next": _cmd_next,
                "stepIn": _cmd_step_in,
                "stepOut": _cmd_step_out,
                "stackTrace": _cmd_stack_trace,
                "variables": _cmd_variables,
                "setVariable": _cmd_set_variable,
                "evaluate": _cmd_evaluate,
                "exceptionInfo": _exception_info,
                # No-ops
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
        # Prefer named pipe connection if present
        if self._ipc_enabled and self._ipc_pipe_conn is not None:
            with contextlib.suppress(Exception):
                self._ipc_pipe_conn.send(f"DBGCMD:{cmd_str}")
            return
        if self._ipc_enabled and self._ipc_wfile is not None:
            with contextlib.suppress(Exception):
                self._ipc_wfile.write(f"DBGCMD:{cmd_str}\n")
                self._ipc_wfile.flush()
            return

        stdin = getattr(self.process, "stdin", None)
        if self.process and stdin:
            with contextlib.suppress(Exception):
                stdin.write(f"DBGCMD:{cmd_str}\n")
                with contextlib.suppress(Exception):
                    stdin.flush()

    # Small helpers used during shutdown to fail pending futures. These are
    # extracted to keep the per-function complexity low so linters don't
    # complain about a single large nested function with many branches.
    def _shutdown_try_set_on_current_loop(
        self,
        fut: asyncio.Future,
        fut_loop: asyncio.AbstractEventLoop | None,
        current_loop: asyncio.AbstractEventLoop | None,
        cid: int,
    ) -> bool:
        """If the future was created on the current loop, try to set its
        exception synchronously and return True on success."""
        if fut_loop is not current_loop or fut.done():
            return False
        try:
            fut.set_exception(RuntimeError("Debugger shutdown"))
        except Exception:
            logger.debug("failed to set exception on pending %s", cid)
            return False
        else:
            return True

    def _shutdown_try_schedule_on_fut_loop(
        self,
        fut: asyncio.Future,
        fut_loop: asyncio.AbstractEventLoop | None,
        to_wait: list[asyncio.Future],
        cid: int,
    ) -> bool:
        """Try to schedule fut.set_exception on the future's loop
        using call_soon_threadsafe. Return True on success.
        """
        if fut_loop is None:
            return False

        # Prefer run_coroutine_threadsafe which gives an acknowledgement
        # (see _shutdown_try_run_coroutine_threadsafe_on_loop) so we get
        # a best-effort synchronous confirmation that the exception was
        # scheduled on the target loop. If that fails, fall back to
        # call_soon_threadsafe.
        try:
            if self._shutdown_try_run_coroutine_threadsafe_on_loop(fut, fut_loop, to_wait, cid):
                return True
        except Exception:
            # If the coroutine-threadsafe path raises, fall back below
            logger.debug("run_coroutine_threadsafe fallback raised for %s", cid)

        try:
            fut_loop.call_soon_threadsafe(fut.set_exception, RuntimeError("Debugger shutdown"))
            logger.debug(
                "shutdown: scheduled exception on future loop for %s",
                cid,
            )
            if not fut.done():
                to_wait.append(fut)
        except Exception:
            logger.debug("failed to schedule exception on future loop %s", cid)
        else:
            return True

        return False

    def _shutdown_try_run_coroutine_threadsafe_on_loop(
        self,
        fut: asyncio.Future,
        fut_loop: asyncio.AbstractEventLoop | None,
        to_wait: list[asyncio.Future],
        cid: int,
    ) -> bool:
        """Fallback that attempts to run a tiny coroutine on fut_loop which
        sets the exception. Returns True if scheduling succeeded.
        """
        if fut_loop is None:
            return False

        async def _set_exc() -> None:
            fut.set_exception(RuntimeError("Debugger shutdown"))

        try:
            cf = asyncio.run_coroutine_threadsafe(_set_exc(), fut_loop)
            try:
                cf.result(timeout=0.1)
            except Exception:
                logger.debug(
                    "run_coroutine_threadsafe fallback failed for %s",
                    cid,
                )
            else:
                if not fut.done():
                    to_wait.append(fut)
                return True
        except Exception:
            logger.debug(
                "run_coroutine_threadsafe scheduling failed for %s",
                cid,
            )
        return False

    def _shutdown_schedule_on_debugger_loop(self, fut: asyncio.Future, cid: int) -> bool:
        """Try scheduling the exception on the debugger's own loop as a
        final fallback."""
        try:
            self.loop.call_soon_threadsafe(fut.set_exception, RuntimeError("Debugger shutdown"))
        except Exception:
            logger.debug("failed to set exception on pending %s", cid)
        else:
            return True
        return False

    async def continue_execution(self, thread_id: int) -> dict[str, Any]:
        """Continue execution of the specified thread"""
        if not self.program_running:
            return {"allThreadsContinued": False}
        if self.is_terminated:
            return {"allThreadsContinued": False}

        # Reset stopped event
        self.stopped_event.clear()

        # Update thread state
        with self.lock:
            if thread_id in self.threads:
                self.threads[thread_id].is_stopped = False

        # Continue according to mode
        if self.in_process and self._inproc is not None:
            try:
                return self._inproc.continue_(thread_id)
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

        # Reset stopped event
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

        # Reset stopped event
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

        # Reset stopped event
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

    async def pause(self, thread_id: int) -> None:
        """Pause execution of the specified thread"""
        if not self.program_running or self.is_terminated:
            return

        if self.in_process and self._inproc is not None:
            # Not implemented: best-effort no-op
            return
        command = {"command": "pause", "arguments": {"threadId": thread_id}}
        await self._send_command_to_debuggee(command)

    async def get_threads(self) -> list[dict[str, Any]]:
        """Get all threads"""
        threads = []
        with self.lock:
            for thread_id, thread in self.threads.items():
                threads.append({"id": thread_id, "name": thread.name})

        # If no threads found, add a default thread
        if not threads:
            threads.append({"id": 1, "name": "Main Thread"})

        return threads

    # Helpers for source discovery
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
        for module_name, module in sys.modules.items():
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

        # From imported modules
        for _name, path, origin in self._iter_python_module_files():
            self._try_add_source(
                seen_paths,
                loaded_sources,
                path,
                origin=origin,
                name=path.name,
                check_exists=False,  # preserve original behavior
            )

        # From linecache
        for filename in list(linecache.cache.keys()):
            self._try_add_source(
                seen_paths,
                loaded_sources,
                filename,
                origin="linecache",
                check_exists=True,
            )

        # Main program
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

            # Try to get the module path
            path = None
            try:
                if hasattr(module, "__file__") and module.__file__:
                    path = module.__file__
            except Exception:
                pass

            # Determine if this is user code (heuristic)
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

        # Sort modules by name for consistent ordering
        all_modules.sort(key=lambda m: m["name"])

        return all_modules

    async def get_stack_trace(
        self, thread_id: int, start_frame: int = 0, levels: int = 0
    ) -> dict[str, Any]:
        """Get stack trace for a thread"""
        # In-process path
        if self.in_process and self._inproc is not None:
            try:
                return self._inproc.stack_trace(thread_id, start_frame, levels)
            except Exception:
                logger.exception("in-process stack_trace failed")
                return {"stackFrames": [], "totalFrames": 0}

        # Subprocess path: request stack trace from debuggee
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

        # Fallback to cached data if no response
        stack_frames = []
        total_frames = 0

        with self.lock:
            if thread_id in self.current_stack_frames:
                frames = self.current_stack_frames[thread_id]
                total_frames = len(frames)

                # Apply start_frame and levels
                if levels > 0:
                    end_frame = min(start_frame + levels, total_frames)
                    frames = frames[start_frame:end_frame]
                else:
                    frames = frames[start_frame:]

                stack_frames = frames

        return {"stackFrames": stack_frames, "totalFrames": total_frames}

    async def get_scopes(self, frame_id: int) -> list[dict[str, Any]]:
        """Get variable scopes for a stack frame"""
        # Generate variable reference for this frame's locals
        var_ref = self.next_var_ref
        self.next_var_ref += 1

        # Generate variable reference for this frame's globals
        global_var_ref = self.next_var_ref
        self.next_var_ref += 1

        # Store references
        self.var_refs[var_ref] = (frame_id, "locals")
        self.var_refs[global_var_ref] = (frame_id, "globals")

        # Create scope objects
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
        # In-process path
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

        # Subprocess path
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

        # Fallback to cached data if no response
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
        # Check if we have the variable reference
        with self.lock:
            if var_ref not in self.var_refs:
                msg = f"Invalid variable reference: {var_ref}"
                raise ValueError(msg)

            ref_info = self.var_refs[var_ref]

        # Handle different types of variable references
        scope_ref_tuple_len = 2
        if isinstance(ref_info, tuple) and len(ref_info) == scope_ref_tuple_len:
            # This is a scope reference (frame_id, scope_type)
            frame_id, scope_type = ref_info

            # In-process path
            if self.in_process and self._inproc is not None:
                try:
                    return self._inproc.set_variable(var_ref, name, value)
                except Exception:
                    logger.exception("in-process set_variable failed")
                    return {
                        "value": value,
                        "type": "string",
                        "variablesReference": 0,
                    }

            # Subprocess path
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

            # Fallback: create a basic response
            return {
                "value": value,
                "type": "string",
                "variablesReference": 0,
            }

        # Unsupported reference type
        msg = f"Cannot set variable in reference type: {type(ref_info)}"
        raise ValueError(msg)

    async def evaluate(
        self, expression: str, frame_id: int, context: str = "hover"
    ) -> dict[str, Any]:
        """Evaluate an expression in a specific context"""
        # In-process path
        if self.in_process and self._inproc is not None:
            try:
                return self._inproc.evaluate(expression, frame_id, context)
            except Exception:
                logger.exception("in-process evaluate failed")
                return {
                    "result": f"<evaluation of '{expression}' not available>",
                    "type": "string",
                    "variablesReference": 0,
                }

        # Subprocess path
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

        # Fallback if no response or debuggee not available
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

        # Send the command and get response
        response = await self._send_command_to_debuggee(command, expect_response=True)

        if response and "body" in response:
            return response["body"]

        # Fallback if no response or debuggee not available
        # This structure matches ExceptionInfoResponseBody
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

        # Send configuration done signal (subprocess only)
        if not self.in_process:
            command = {"command": "configurationDone"}
            await self._send_command_to_debuggee(command)

    async def disconnect(self, terminate_debuggee: bool = False) -> None:
        """Disconnect from the debuggee"""
        if self.program_running:
            if terminate_debuggee and self.process:
                try:
                    # Send terminate command first
                    await self.terminate()

                    # Give it a chance to terminate gracefully
                    await asyncio.sleep(0.5)

                    # Force terminate if still running
                    if self.process.poll() is None:
                        self.process.kill()
                except Exception:
                    logger.exception("Error terminating debuggee")

            self.program_running = False

        await self.shutdown()

    async def terminate(self) -> None:
        """Terminate the debuggee"""
        if self.in_process:
            # In-process: do not kill the host interpreter. Just mark
            # state and send a terminated event for clients that expect it.
            try:
                self.is_terminated = True
                self.program_running = False
                await self.server.send_event("terminated")
            except Exception:
                logger.exception("in-process terminate failed")
            return

        if self.program_running and self.process:
            try:
                # Terminate the process
                self.process.terminate()

                # Send terminate command to debuggee
                command = {"command": "terminate"}
                await self._send_command_to_debuggee(command)

                # Set terminated flag
                self.is_terminated = True
                self.program_running = False
            except Exception:
                logger.exception("Error sending terminate command")

    async def restart(self) -> None:
        """Request a session restart.

        This method signals the client to restart by emitting a terminated
        event with restart=true, and then performs a best-effort termination
        and cleanup similar to terminate+shutdown.
        """
        try:
            # Signal client to restart the session
            await self.server.send_event("terminated", {"restart": True})
        except Exception:
            logger.exception("failed to send terminated(restart=true) event")

        # Attempt to stop the running program if any
        try:
            if self.program_running and self.process:
                try:
                    self.process.terminate()
                except Exception:
                    logger.debug("process.terminate() failed during restart")
        except Exception:
            logger.debug("error during restart termination path")

        # Ensure internal flags are updated before shutdown
        self.is_terminated = True
        self.program_running = False

        # Perform standard shutdown cleanup
        await self.shutdown()

    async def next_step(self, thread_id: int) -> None:
        """Step over to the next line (alias for next)"""
        await self.next(thread_id)

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
        """Send a command to the debuggee"""
        if not self.process or self.is_terminated:
            msg = "No debuggee process"
            raise RuntimeError(msg)

        try:
            # Use run_in_executor to avoid blocking the event loop
            await self.loop.run_in_executor(
                self.executor,
                lambda: self.process.stdin.write(f"DBGCMD:{command}\n")
                if self.process and self.process.stdin
                else None,
            )
        except Exception:
            logger.exception("Error sending command to debuggee")

    async def shutdown(self) -> None:  # noqa: PLR0912, PLR0915
        """Shut down the debugger and clean up resources."""

        # Stop the executor if present
        if self.executor:
            try:
                self.executor.shutdown(wait=False)
            except Exception:
                logger.debug("executor shutdown failed")

        # Cancel background tasks (collect list first to avoid mutation)
        try:
            tasks = list(self._bg_tasks)
            for t in tasks:
                t.cancel()
        except Exception:
            logger.debug("error cancelling background tasks")

        # Snapshot pending commands and clear the map under lock
        with self.lock:
            pending = dict(self._pending_commands)
            self._pending_commands.clear()

        # Collect futures we scheduled cross-loop so we can wait briefly
        # for their exception callbacks to execute on their owning loops.
        to_wait: list[asyncio.Future] = []

        # Determine current loop (if any)
        current_loop = None
        with contextlib.suppress(RuntimeError):
            current_loop = asyncio.get_running_loop()

        # Apply failure to all pending futures using the extracted helpers.
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

            # Try strategies in order until one succeeds.
            if self._shutdown_try_set_on_current_loop(fut, fut_loop, current_loop, cid):
                continue

            if self._shutdown_try_schedule_on_fut_loop(fut, fut_loop, to_wait, cid):
                continue

            if self._shutdown_try_run_coroutine_threadsafe_on_loop(fut, fut_loop, to_wait, cid):
                continue

            # As a last resort attempt a direct set_exception.
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

            # Final fallback: schedule on the debugger loop
            self._shutdown_schedule_on_debugger_loop(fut, cid)

        # (done above) no further per-future work is required here

        # Give cross-loop scheduled exception callbacks a short moment to
        # execute on their owning loops. This prevents races where the
        # shutdown returns before the other loop has a chance to mark the
        # future done. We poll with small sleeps to avoid blocking the
        # debugger loop for long.
        if to_wait:
            deadline = time.monotonic() + 0.25
            while time.monotonic() < deadline:
                if all(f.done() for f in to_wait):
                    break
                # Yield to the debugger loop briefly
                try:
                    await asyncio.sleep(0.01)
                except Exception:
                    # If sleep is interrupted for some reason, continue
                    pass

        # Close process stdio safely
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

        # Clear internal structures
        self.var_refs.clear()
        self.threads.clear()
        self.breakpoints.clear()
        self.function_breakpoints.clear()
        self.current_stack_frames.clear()
        self.program_running = False
        self.is_terminated = True
