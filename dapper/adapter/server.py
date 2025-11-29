"""
Implementation of the Debug Adapter Protocol Server and integrated Python debugger.

This module merges the DebugAdapterServer and PyDebugger to avoid circular
dependencies and simplify interactions between the server and debugger.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
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
from multiprocessing import connection as mp_conn
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from typing_extensions import Protocol

from dapper.adapter.inprocess_bridge import InProcessBridge
from dapper.adapter.payload_extractor import DebugDataExtractor
from dapper.adapter.request_handlers import RequestHandler
from dapper.adapter.types import BreakpointDict
from dapper.adapter.types import BreakpointResponse
from dapper.adapter.types import DAPRequest
from dapper.adapter.types import PyDebuggerThread
from dapper.adapter.types import SourceDict
from dapper.core.inprocess_debugger import InProcessDebugger
from dapper.ipc.ipc_binary import pack_frame
from dapper.ipc.ipc_context import IPCContext
from dapper.protocol.protocol import ProtocolHandler
from dapper.protocol.protocol_types import Source
from dapper.protocol.protocol_types import SourceBreakpoint

try:
    # Optional integration module; may not be present on all platforms.
    from dapper._frame_eval.debugger_integration import integrate_py_debugger
except Exception:  # pragma: no cover - optional feature
    integrate_py_debugger = None


if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Sequence

    from dapper.ipc.connections.base import ConnectionBase
    from dapper.protocol.debugger_protocol import Variable
    from dapper.protocol.protocol_types import Breakpoint
    from dapper.protocol.protocol_types import ContinueResponseBody
    from dapper.protocol.protocol_types import DataBreakpointInfoResponseBody
    from dapper.protocol.protocol_types import EvaluateResponseBody
    from dapper.protocol.protocol_types import ExceptionDetails
    from dapper.protocol.protocol_types import ExceptionFilterOptions
    from dapper.protocol.protocol_types import ExceptionInfoResponseBody
    from dapper.protocol.protocol_types import ExceptionOptions
    from dapper.protocol.protocol_types import FunctionBreakpoint
    from dapper.protocol.protocol_types import GenericRequest
    from dapper.protocol.protocol_types import Module
    from dapper.protocol.protocol_types import Scope
    from dapper.protocol.protocol_types import SetVariableResponseBody
    from dapper.protocol.protocol_types import StackTraceResponseBody
    from dapper.protocol.protocol_types import Thread


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event loop acquisition helpers
# ---------------------------------------------------------------------------
def _acquire_event_loop(
    preferred: asyncio.AbstractEventLoop | None = None,
) -> tuple[asyncio.AbstractEventLoop, bool]:
    """Return an event loop avoiding deprecated APIs.

    Order of preference:
    1. A caller-supplied loop (never marked owned).
    2. A currently running loop (``asyncio.get_running_loop``).
    3. A freshly created loop (marked owned so the debugger can close it).

    We intentionally avoid ``asyncio.get_event_loop`` to silence deprecation
    warnings under Python 3.12+ when no loop is set for the current thread.
    """
    if preferred is not None:
        return preferred, False
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is not None:
        return running, False
    new_loop = asyncio.new_event_loop()
    return new_loop, True


class DebugServer(Protocol):
    """Protocol defining the interface expected by PyDebugger for server communication."""

    @property
    def debugger(self) -> PyDebugger:
        """Access the debugger instance."""
        ...  # type: ignore[empty-body]

    async def send_event(self, event_name: str, body: dict[str, Any] | None = None) -> None:
        """Send an event to the debug client.

        Args:
            event_name: The event name (e.g., 'stopped', 'output', 'process')
            body: Optional event payload
        """
        ...  # type: ignore[empty-body]

    async def send_message(self, message: dict[str, Any]) -> None:
        """Send a raw message to the debug client.

        Args:
            message: The complete message dictionary
        """
        ...  # type: ignore[empty-body]

    def spawn_threadsafe(self, callback: Callable[[], Any]) -> None:
        """Schedule a callback to be run on the server's event loop.

        Args:
            callback: The function to call on the server's event loop
        """
        ...  # type: ignore[empty-body]


class PyDebugger:
    """
    Main debugger class that integrates with Python's built-in debugging tools
    and communicates back to the DebugAdapterServer.
    """

    def __init__(
        self,
        server: DebugServer,
        loop: asyncio.AbstractEventLoop | None = None,
        enable_frame_eval: bool = False,
    ):
        """Initialize the PyDebugger.

        Args:
            server: The debug server that implements the DebugServer protocol
            loop: Optional event loop to use. If not provided, gets the current event loop.
            enable_frame_eval: Whether to enable frame evaluation optimization.
        """
        self.server: DebugServer = server
        self.loop: asyncio.AbstractEventLoop
        self._owns_loop: bool
        self.loop, self._owns_loop = _acquire_event_loop(loop)

        if enable_frame_eval and integrate_py_debugger is not None:
            # Optional integration - resolved at import time to avoid dynamic
            # imports at runtime. The integration function may be None if the
            # frame-eval module is not available on this platform.
            integrate_py_debugger(self)

        # Core state
        self.threads: dict[int, PyDebuggerThread] = {}
        self.main_thread_id: int | None = None
        self.next_thread_id: int = 1
        self.next_var_ref: int = 1000
        self.var_refs: dict[int, object] = {}
        self.breakpoints: dict[str, list[BreakpointDict]] = {}
        # store function breakpoints as list[FunctionBreakpoint] at runtime for flexibility
        self.function_breakpoints: list[FunctionBreakpoint] = []
        # Exception breakpoint flags (two booleans for clarity)
        self.exception_breakpoints_uncaught: bool = False
        self.exception_breakpoints_raised: bool = False
        self.process: subprocess.Popen | None = None
        self.debugger_thread: threading.Thread | None = None
        self.is_terminated: bool = False
        self.program_running: bool = False
        self.stop_on_entry: bool = False
        self.no_debug: bool = False
        self.current_stack_frames: dict[int, list] = {}
        self.program_path: str | None = None
        self.thread_exit_events: dict[int, object] = {}
        self.lock: threading.RLock = threading.RLock()
        # Use thread-safe Event objects for synchronization. Tests and
        # asyncio code may await these — the helper `_await_event` will
        # bridge the synchronous wait to an awaitable when needed.
        self.stopped_event = threading.Event()
        self.configuration_done = threading.Event()

        # Keep references to background tasks so they don't get GC'd
        self._bg_tasks: set[asyncio.Task] = set()

        # Test mode flag (used by tests to start debuggee in a real thread)
        self._test_mode: bool = False

        # Command tracking for request/response
        self._next_command_id: int = 1
        self._pending_commands: dict[int, asyncio.Future] = {}
        # In-process debugging support (optional/opt-in)
        self.in_process: bool = False
        self._inproc_bridge: InProcessBridge | None = None

        # Optional IPC transport context (initialized lazily in launch)
        self._use_ipc: bool = False
        self.ipc: IPCContext = IPCContext()

        # Data breakpoint containers
        self._data_watches: dict[str, dict[str, Any]] = {}  # dataId -> watch metadata
        self._frame_watches: dict[int, list[str]] = {}  # frameId -> list of dataIds

    def spawn_threadsafe(self, callback: Callable[[], Any]) -> None:
        """Schedule a (possibly coroutine-producing) callback on the debugger loop.

        The callback is always executed on the event loop thread. If it returns
        an awaitable, we wrap it in a Task and track it for shutdown. This
        avoids creating coroutines on worker threads which can cause 'never
        awaited' warnings.
        """

        def _run_on_loop() -> None:
            try:
                result = callback()
            except Exception:
                logger.exception("Error in spawn_threadsafe callback")
                return
            if inspect.isawaitable(result):
                try:
                    task = asyncio.ensure_future(result)
                except Exception:
                    logger.exception("error creating task for awaitable")
                else:
                    self._bg_tasks.add(task)
                    task.add_done_callback(lambda t: self._bg_tasks.discard(t))

        try:
            self.loop.call_soon_threadsafe(_run_on_loop)
        except Exception:  # pragma: no cover - defensive
            logger.debug("spawn_threadsafe drop (loop closed)")
            return

    async def _await_event(self, ev: object) -> None:
        """Await a blocking or patched event.wait() in an asyncio-friendly way.

        This helper inspects the event.wait attribute and either runs the
        blocking wait in an executor (threading.Event) or directly awaits a
        patched awaitable-returning stub.
        """
        wait = getattr(ev, "wait", None)
        if wait is None:
            return

        try:
            bound_self = getattr(wait, "__self__", None)
            if isinstance(bound_self, threading.Event):
                await self.loop.run_in_executor(None, wait)
                return
        except Exception:
            pass

        try:
            res = wait()
        except Exception:
            await self.loop.run_in_executor(None, wait)
            return

        if inspect.isawaitable(res):
            await res
            return

        return

    def data_breakpoint_info(self, *, name: str, frame_id: int) -> DataBreakpointInfoResponseBody:
        """Return minimal data breakpoint info for a variable in a frame."""
        data_id = f"frame:{frame_id}:var:{name}"
        return {
            "dataId": data_id,
            "description": f"Variable '{name}' in frame {frame_id}",
            "accessTypes": ["write"],
            "canPersist": False,
        }

    def set_data_breakpoints(self, breakpoints: list[dict[str, Any]]) -> list[Breakpoint]:
        """Register a set of data breakpoints (bookkeeping only)."""
        # Clear existing watches (DAP semantics: full replace)
        self._data_watches.clear()
        self._frame_watches.clear()

        results: list[Breakpoint] = []
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

    def _check_data_watches_for_frame(self, frame_id: int, _frame_locals: dict[str, Any]) -> None:  # noqa: ARG002
        """(Future) Detect variable changes for watches tied to frame_id."""
        return

    def _forward_event(self, event_name: str, payload: dict[str, Any]) -> None:
        """Forward an event (defer creation unless immediate path in spawn_threadsafe)."""
        # Attempt to call server.send_event immediately so synchronous test
        # helpers can observe calls without requiring an extra loop tick.
        try:
            res = self.server.send_event(event_name, payload)
        except Exception:
            logger.exception("error calling server.send_event")
            return

        # If the handler returned an awaitable, ensure it's scheduled on the
        # debugger loop for execution (safe whether or not the loop is running).
        try:
            if inspect.isawaitable(res):
                try:
                    # If already on the debugger loop, create the task directly
                    if asyncio.get_running_loop() is self.loop:
                        t = asyncio.ensure_future(res)
                        # Track background task so it can be cancelled during shutdown
                        self._bg_tasks.add(t)
                        t.add_done_callback(lambda _t: self._bg_tasks.discard(_t))
                    else:
                        # Otherwise schedule creation on the debugger loop
                        def _spawn():
                            t2 = asyncio.ensure_future(res)
                            self._bg_tasks.add(t2)
                            t2.add_done_callback(lambda _t: self._bg_tasks.discard(_t))

                        self.loop.call_soon_threadsafe(_spawn)
                except RuntimeError:
                    # No running loop in this thread; schedule thread-safely
                    def _spawn2():
                        t3 = asyncio.ensure_future(res)
                        self._bg_tasks.add(t3)
                        t3.add_done_callback(lambda _t: self._bg_tasks.discard(_t))

                    self.loop.call_soon_threadsafe(_spawn2)
        except Exception:
            # Be defensive: do not let event forwarding raise during debug message handling
            logger.debug("error scheduling awaitable returned by server.send_event", exc_info=True)

    async def launch(
        self,
        program: str,
        args: list[str] | None = None,
        stop_on_entry: bool = False,
        no_debug: bool = False,
        in_process: bool = False,
        use_binary_ipc: bool = True,
        ipc_transport: str | None = None,
        ipc_pipe_name: str | None = None,
    ) -> None:
        """Launch a new Python program for debugging.
        """
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
            "dapper.launcher.debug_launcher",
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
        # IPC is now mandatory; always enable it.
        self._use_ipc = True
        self.set_ipc_binary(bool(use_binary_ipc))
        self._prepare_ipc_listener(ipc_transport, ipc_pipe_name, debug_args)
        if self.ipc.binary:
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

        # Accept the IPC connection from the launcher (IPC is mandatory)
        if self.ipc.listen_sock is not None or self.ipc.pipe_listener is not None:
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
            await self._await_event(self.stopped_event)

    async def _launch_in_process(self) -> None:
        """Initialize in-process debugging bridge and emit process event."""
        self.in_process = True
        inproc = InProcessDebugger()
        self._inproc_bridge = InProcessBridge(
            inproc,
            on_stopped=self._handle_event_stopped,
            on_thread=self._handle_event_thread,
            on_exited=self._handle_event_exited,
            on_output=self._handle_inproc_output,
        )

        # Mark running and emit process event for current interpreter
        self.program_running = True
        proc_event = {
            "name": Path(self.program_path or "").name,
            "systemProcessId": os.getpid(),
            "isLocalProcess": True,
            "startMethod": "launch",
        }
        await self.server.send_event("process", proc_event)

    def _handle_inproc_output(self, category: str, output: str) -> None:
        """Forward output events from in-process debugger to the server."""
        try:
            payload = {"category": category, "output": output}
            self.spawn_threadsafe(lambda: self.server.send_event("output", payload))
        except Exception:
            logger.exception("error in on_output callback")

    async def attach(  # noqa: PLR0915
        self,
        *,
        ipc_transport: str | None = None,
        ipc_host: str | None = None,
        ipc_port: int | None = None,
        ipc_path: str | None = None,
        ipc_pipe_name: str | None = None,
        use_ipc: bool = True,  # Kept for compatibility, must be True
    ) -> None:
        """Attach to an already running debuggee via IPC.

        IPC is mandatory for attach; the use_ipc parameter must be True.
        """
        if not use_ipc:
            msg = "attach requires IPC (use_ipc must be True)"
            raise RuntimeError(msg)

        default_transport = "pipe" if os.name == "nt" else "unix"
        transport = (ipc_transport or default_transport).lower()

        if os.name == "nt" and transport == "pipe":
            if not ipc_pipe_name:
                msg = "ipcPipeName required for pipe attach"
                raise RuntimeError(msg)
            try:
                conn = mp_conn.Client(address=ipc_pipe_name, family="AF_PIPE")
            except Exception as exc:  # pragma: no cover - depends on OS
                msg = "failed to connect pipe"
                raise RuntimeError(msg) from exc
            # Use helper to centralize state changes
            self.enable_ipc_pipe_connection(conn, binary=False)

            def _reader():
                try:
                    while True:
                        try:
                            conn = cast("mp_conn.Connection", self.ipc.pipe_conn)
                            msg = conn.recv()
                        except (EOFError, OSError):
                            break
                        if isinstance(msg, str) and msg.startswith("DBGP:"):
                            self._handle_debug_message(msg[5:].strip())
                finally:
                    self.disable_ipc()

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
            # Use helper that configures rfile/wfile and flags
            self.enable_ipc_socket_from_connected(sock, binary=False)

            def _reader_sock():
                try:
                    while True:
                        rfile = self.ipc.rfile
                        assert rfile is not None
                        line = rfile.readline()
                        if not line:
                            break
                        line_s = cast("str", line)
                        if line_s.startswith("DBGP:"):
                            self._handle_debug_message(line_s[5:].strip())
                finally:
                    self.disable_ipc()

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
            # Centralized helper to set up the connected socket
            self.enable_ipc_socket_from_connected(sock, binary=False)

            def _reader_tcp():
                try:
                    while True:
                        rfile = self.ipc.rfile
                        assert rfile is not None
                        line = rfile.readline()
                        if not line:
                            break
                        line_s = cast("str", line)
                        if line_s.startswith("DBGP:"):
                            self._handle_debug_message(line_s[5:].strip())
                finally:
                    self.disable_ipc()

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
                listener = mp_conn.Listener(address=pipe_name, family="AF_PIPE")
            except Exception:
                logger.exception("Failed to create named pipe listener")
                listener = None
            self.set_ipc_pipe_listener(listener)
            if listener is not None:
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
                self.set_ipc_listen_socket(listen, unix_path)
                debug_args.extend(["--ipc", "unix", "--ipc-path", str(unix_path)])
                return

        host = "127.0.0.1"
        listen = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        with contextlib.suppress(Exception):
            listen.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        listen.bind((host, 0))
        listen.listen(1)
        _addr, port = listen.getsockname()
        self.set_ipc_listen_socket(listen)
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
            if self.ipc.pipe_listener is not None:
                self.ipc.accept_and_read_pipe(self._handle_debug_message)
                return
            if self.ipc.listen_sock is not None:
                self.ipc.accept_and_read_socket(self._handle_debug_message)
        except Exception:
            logger.exception("IPC reader error")
        finally:
            # Ensure we clean up IPC resources before we exit
            self.disable_ipc()

    # ------------------------------------------------------------------
    # IPC helper methods
    # ------------------------------------------------------------------
    def enable_ipc_pipe_connection(self, conn: Any, *, binary: bool = False) -> None:
        """Enable IPC using an already-connected pipe connection."""
        self.ipc.enable_pipe_connection(conn, binary=binary)

    def enable_ipc_socket_from_connected(self, sock: Any, *, binary: bool = False) -> None:
        """Enable IPC using an already-connected socket."""
        self.ipc.enable_socket_from_connected(sock, binary=binary)

    def set_ipc_pipe_listener(self, listener: Any) -> None:
        """Register a pipe listener that will accept a single connection later."""
        self.ipc.set_pipe_listener(listener)

    def set_ipc_listen_socket(self, listen_sock: Any, unix_path: Any | None = None) -> None:
        """Register a listening socket that will accept a single connection later."""
        self.ipc.set_listen_socket(listen_sock, unix_path)

    def set_ipc_binary(self, binary: bool) -> None:
        """Set the binary flag on the IPC context without enabling or disabling."""
        self.ipc.set_binary(binary)

    def enable_ipc_wfile(self, wfile: Any, *, binary: bool = False) -> None:
        """Enable IPC using an already-created writer file-like object."""
        self.ipc.enable_wfile(wfile, binary=binary)

    def disable_ipc(self) -> None:
        """Disable IPC and perform cleanup via the IPCContext helper."""
        try:
            self.ipc.disable()
        except Exception:
            logger.exception("error disabling ipc")

    # Legacy IPC helper methods removed; direct calls use ipc.* now.

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

            self.spawn_threadsafe(lambda c=exit_code: self._handle_program_exit(c))
        except Exception:
            logger.exception("Error starting debuggee")
            self.is_terminated = True
            self.spawn_threadsafe(lambda: self._handle_program_exit(1))

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
                    # Always schedule via factory to defer coroutine creation to loop thread
                    self.spawn_threadsafe(
                        lambda line_text=line, cat=category: self.server.send_event(
                            "output", {"category": cat, "output": line_text}
                        )
                    )
        except Exception:
            logger.exception("Error reading %s", category)

    def _handle_event_stopped(self, data: dict[str, Any]) -> None:
        """Handle a stopped event's local state updates and forwarding."""
        thread_id = data.get("threadId", 1)
        reason = data.get("reason", "breakpoint")

        with self.lock:
            thread = self.threads.get(thread_id)
            if thread is None:
                self.threads[thread_id] = thread = PyDebuggerThread(
                    thread_id, f"Thread {thread_id}"
                )
            thread.is_stopped = True
            thread.stop_reason = reason

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

        self._forward_event("stopped", stop_event)

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
        # Use unified spawn_threadsafe with factory to avoid constructing coroutine off-loop
        self.spawn_threadsafe(lambda c=exit_code: self._handle_program_exit(c))

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

        Uses a small DataWrapper to centralize safe access to the incoming
        dict and helper methods that construct event payload dictionaries.
        """
        try:
            data: dict[str, Any] = json.loads(message)
        except Exception:
            logger.exception("Error handling debug message")
            return

        wrapper = DebugDataExtractor(data)

        command_id = wrapper.get("id")
        if command_id is not None and command_id in self._pending_commands:
            with self.lock:
                future = self._pending_commands.pop(command_id, None)

            if future is not None:
                self._resolve_pending_response(future, data)
            return

        event_type: str | None = wrapper.get("event")

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
        # Use the registered payload mapping on DebugDataExtractor to
        # resolve the method name for a given event and invoke it.
        elif event_type is not None:
            method_name = DebugDataExtractor.payload_dispatch.get(event_type)
            if method_name is not None:
                method = getattr(wrapper, method_name, None)
                if callable(method):
                    payload = method()
                    # type: ignore[arg-type]
                    self._forward_event(event_type, cast("dict[str, Any]", payload))

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
        self, source: SourceDict | str, breakpoints: Sequence[SourceBreakpoint]
    ) -> list[BreakpointResponse]:
        """Set breakpoints for a source file.

        Args:
            source: Either a path string or a dictionary containing at least a 'path' key
            breakpoints: List of breakpoint specifications to set

        Returns:
            List of breakpoint results with verification status
        """
        # Extract and validate path
        path = source if isinstance(source, str) else source.get("path")
        if not path:
            return [{"verified": False, "message": "Source path is required"} for _ in breakpoints]
        path = str(Path(path).resolve())

        # Process breakpoints
        spec_list, storage_list = self._process_breakpoints(breakpoints)
        self.breakpoints[path] = storage_list

        # Try in-process debugger first
        if self.in_process and self._inproc_bridge is not None:
            return await self._set_breakpoints_in_process(path, spec_list, storage_list)

        # Fall back to external process debugger
        if self.process and not self.is_terminated:
            await self._set_breakpoints_external_process(path, storage_list)

        return storage_list  # type: ignore[return-value]

    def _process_breakpoints(
        self, breakpoints: Sequence[SourceBreakpoint]
    ) -> tuple[list[SourceBreakpoint], list[BreakpointDict]]:
        """Process breakpoints into spec and storage lists.

        Args:
            breakpoints: List of breakpoint specifications

        Returns:
            Tuple of (spec_list, storage_list)
        """
        spec_list: list[SourceBreakpoint] = []
        storage_list: list[BreakpointDict] = []

        for bp in breakpoints:
            line_val = int(bp.get("line", 0))

            # Extract optional fields
            optional_fields = {}
            for field in ["condition", "hitCondition", "logMessage"]:
                value = bp.get(field)
                if value is not None:
                    optional_fields[field] = str(value) if field != "logMessage" else value

            # Create spec entry for debugger API
            spec_list.append(SourceBreakpoint(line=line_val, **optional_fields))

            # Create storage entry for response
            storage_list.append(BreakpointDict(line=line_val, verified=True, **optional_fields))

        return spec_list, storage_list

    async def _set_breakpoints_in_process(
        self, path: str, spec_list: list[SourceBreakpoint], storage_list: list[BreakpointDict]
    ) -> list[BreakpointResponse]:
        """Set breakpoints using in-process debugger.

        Args:
            path: Source file path
            spec_list: Breakpoint specs for debugger API
            storage_list: Storage list for fallback

        Returns:
            List of breakpoint responses
        """
        try:
            if self._inproc_bridge is None:
                return [{"verified": False} for _ in storage_list]
            result = self._inproc_bridge.set_breakpoints(path, spec_list)
            return [
                {
                    "verified": bp.get("verified", False),
                    "line": bp.get("line"),
                    "condition": bp.get("condition"),
                    "hitCondition": bp.get("hitCondition"),
                    "logMessage": bp.get("logMessage"),
                }
                for bp in result
            ]  # type: ignore[return-value]
        except Exception:
            logger.exception("in-process set_breakpoints failed")
            return [{"verified": False} for _ in storage_list]

    async def _set_breakpoints_external_process(
        self, path: str, storage_list: list[BreakpointDict]
    ) -> None:
        """Set breakpoints using external process debugger.

        Args:
            path: Source file path
            storage_list: List of breakpoint dictionaries
        """
        # Create command for external debugger
        source_dict = {"path": path}
        bp_command = {
            "command": "setBreakpoints",
            "arguments": {
                "source": source_dict,
                "breakpoints": storage_list,
            },
        }

        # Generate progress ID
        try:
            progress_id = f"setBreakpoints:{path}:{int(time.time() * 1000)}"
        except Exception:
            progress_id = f"setBreakpoints:{path}"

        # Send progress events around the command
        self.spawn_threadsafe(
            lambda pid=progress_id: self.server.send_event(
                "progressStart", {"progressId": pid, "title": "Setting breakpoints"}
            )
        )

        await self._send_command_to_debuggee(bp_command)

        # Forward breakpoint events
        self._forward_breakpoint_events(storage_list)

        # End progress
        self.spawn_threadsafe(
            lambda pid=progress_id: self.server.send_event("progressEnd", {"progressId": pid})
        )

    def _forward_breakpoint_events(self, storage_list: list[BreakpointDict]) -> None:
        """Forward breakpoint-changed events to clients.

        Args:
            storage_list: List of breakpoint dictionaries
        """
        try:
            bp_events = [
                {
                    "reason": "changed",
                    "breakpoint": {
                        "verified": bp.get("verified", True),
                        "line": bp.get("line"),
                    },
                }
                for bp in storage_list
            ]
            for be in bp_events:
                self._forward_event("breakpoint", be)
        except Exception:
            logger.debug("Failed to forward breakpoint events")

    async def set_function_breakpoints(
        self, breakpoints: list[FunctionBreakpoint]
    ) -> list[FunctionBreakpoint]:
        """Set breakpoints for functions"""
        spec_funcs: list[FunctionBreakpoint] = []
        storage_funcs: list[FunctionBreakpoint] = []
        for bp in breakpoints:
            name = str(bp.get("name", ""))
            spec_entry: FunctionBreakpoint = {"name": name}
            cond = bp.get("condition")
            if cond is not None:
                spec_entry["condition"] = str(cond)
            hc = bp.get("hitCondition")
            if hc is not None:
                spec_entry["hitCondition"] = str(hc)
            spec_funcs.append(spec_entry)

            storage_funcs.append(
                {
                    "name": name,
                    "condition": cond,
                    "hitCondition": hc,
                    "verified": True,
                }
            )

        # Store runtime representation (with verified flag) for IPC and state
        self.function_breakpoints = storage_funcs

        if self.in_process and self._inproc_bridge is not None:
            try:
                result = self._inproc_bridge.set_function_breakpoints(spec_funcs)
                return list(result)
            except Exception:
                logger.exception("in-process set_function_breakpoints failed")
                return [{"verified": False} for _ in storage_funcs]
        if self.process and not self.is_terminated:
            bp_command = {
                "command": "setFunctionBreakpoints",
                "arguments": {"breakpoints": storage_funcs},
            }
            await self._send_command_to_debuggee(bp_command)

        return [{"verified": bp.get("verified", True)} for bp in storage_funcs]

    async def set_exception_breakpoints(
        self,
        filters: list[str],
        filter_options: list[ExceptionFilterOptions] | None = None,
        exception_options: list[ExceptionOptions] | None = None,
    ) -> list[Breakpoint]:
        """Set exception breakpoints.

        Accepts the DAP-shaped arguments: `filters`, optional `filterOptions`,
        and optional `exceptionOptions`. For in-process debuggers we currently
        only apply the boolean flags derived from `filters`; the optional
        options are forwarded to an external debuggee process when present.
        """
        # Update runtime flags derived from the simple `filters` list.
        self.exception_breakpoints_raised = "raised" in filters
        self.exception_breakpoints_uncaught = "uncaught" in filters

        # In-process path: underlying in-process APIs accept just the
        # simple filters list for now (backwards compatible).
        if self.in_process and self._inproc_bridge is not None:
            try:
                result = self._inproc_bridge.set_exception_breakpoints(filters)
                return list(result)
            except Exception:
                logger.exception("in-process set_exception_breakpoints failed")
                return [{"verified": False} for _ in filters]

        # Remote/process path: forward the full arguments when present.
        if self.process and not self.is_terminated:
            args: dict[str, Any] = {"filters": filters}
            if filter_options is not None:
                args["filterOptions"] = filter_options
            if exception_options is not None:
                args["exceptionOptions"] = exception_options

            bp_command = {"command": "setExceptionBreakpoints", "arguments": args}
            await self._send_command_to_debuggee(bp_command)

        # Best-effort: assume the breakpoints were set when no response is
        # available (e.g., no in-process bridge). Callers rely on the
        # returned list length matching `filters`.
        return [{"verified": True} for _ in filters]

    async def _send_command_to_debuggee(
        self, command: dict[str, Any], expect_response: bool = False
    ) -> dict[str, Any] | None:
        """Send a command to the debuggee process or in-process bridge."""
        if self.in_process and self._inproc_bridge is not None:
            return self._inproc_bridge.dispatch_command(command, expect_response)

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

    def _write_command_to_channel(self, cmd_str: str) -> None:
        """Write a command to the active IPC channel.
        """
        if self.ipc.enabled and self.ipc.pipe_conn is not None:
            with contextlib.suppress(Exception):
                if self.ipc.binary:
                    self.ipc.pipe_conn.send_bytes(pack_frame(2, cmd_str.encode("utf-8")))
                else:
                    self.ipc.pipe_conn.send(cmd_str)
            return
        if self.ipc.enabled and self.ipc.wfile is not None:
            with contextlib.suppress(Exception):
                if self.ipc.binary:
                    self.ipc.wfile.write(pack_frame(2, cmd_str.encode("utf-8")))  # type: ignore[arg-type]
                    self.ipc.wfile.flush()  # type: ignore[call-arg]
                else:
                    self.ipc.wfile.write(f"{cmd_str}\n")  # type: ignore[arg-type]
                    self.ipc.wfile.flush()
            return

        msg = "IPC is required but no IPC channel is available. Cannot send command."
        raise RuntimeError(msg)

    # (old _schedule_coroutine implementation removed; use spawn/spawn_threadsafe)

    async def continue_execution(self, thread_id: int) -> ContinueResponseBody:
        """Continue execution of the specified thread"""
        if not self.program_running or self.is_terminated:
            return {"allThreadsContinued": False}

        self.stopped_event.clear()

        with self.lock:
            if thread_id in self.threads:
                self.threads[thread_id].is_stopped = False

        if self.in_process and self._inproc_bridge is not None:
            try:
                result = self._inproc_bridge.continue_(thread_id)
                return cast("ContinueResponseBody", result)
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

        if self.in_process and self._inproc_bridge is not None:
            try:
                self._inproc_bridge.next_(thread_id)
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

        if self.in_process and self._inproc_bridge is not None:
            try:
                self._inproc_bridge.step_in(thread_id)
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

        if self.in_process and self._inproc_bridge is not None:
            try:
                self._inproc_bridge.step_out(thread_id)
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

        if self.in_process and self._inproc_bridge is not None:
            return False
        command = {"command": "pause", "arguments": {"threadId": thread_id}}
        await self._send_command_to_debuggee(command)
        return True

    async def get_threads(self) -> list[Thread]:
        """Get all threads"""
        threads: list[Thread] = []
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

    async def get_modules(self) -> list[Module]:
        """Get all loaded Python modules"""
        all_modules: list[Module] = []

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

            module_obj: Module = {
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
    ) -> StackTraceResponseBody:
        """Get stack trace for a thread"""
        if self.in_process and self._inproc_bridge is not None:
            try:
                result = self._inproc_bridge.stack_trace(thread_id, start_frame, levels)
                return cast("StackTraceResponseBody", result)
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

    async def get_scopes(self, frame_id: int) -> list[Scope]:
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
        self, variables_reference: int, filter_type: str = "", start: int = 0, count: int = 0
    ) -> list[Variable]:
        """Get variables for the given reference."""
        if self.in_process and self._inproc_bridge is not None:
            try:
                # Use the variables method instead of get_variables
                result = self._inproc_bridge.variables(
                    variables_reference,
                    filter_type=filter_type,
                    start=start,
                    count=count if count > 0 else None,
                )
                # The in-process debugger returns a list of variables directly
                if isinstance(result, list):
                    return cast("list[Variable]", result)
                # Fall back to old behavior for backward compatibility
                return cast("list[Variable]", result.get("variables", []))
            except Exception:
                logger.exception("in-process variables failed")
                return []

        command = {
            "command": "variables",
            "arguments": {"variablesReference": variables_reference},
        }
        if filter_type:
            command["arguments"]["filter"] = filter_type
        if start > 0:
            command["arguments"]["start"] = start
        if count > 0:
            command["arguments"]["count"] = count

        response = await self._send_command_to_debuggee(command, expect_response=True)

        if response and "body" in response and "variables" in response["body"]:
            return cast("list[Variable]", response["body"]["variables"])

        variables: list[Variable] = []
        with self.lock:
            if variables_reference in self.var_refs and isinstance(
                self.var_refs[variables_reference], list
            ):
                variables = cast("list[Variable]", self.var_refs[variables_reference])

        return variables

    async def set_variable(
        self,
        var_ref: int,
        name: str,
        value: str,
    ) -> SetVariableResponseBody:
        """Set a variable value in the specified scope."""
        with self.lock:
            if var_ref not in self.var_refs:
                msg = f"Invalid variable reference: {var_ref}"
                raise ValueError(msg)

            ref_info = self.var_refs[var_ref]

        scope_ref_tuple_len = 2
        if isinstance(ref_info, tuple) and len(ref_info) == scope_ref_tuple_len:
            frame_id, _scope_type = ref_info

            if self.in_process and self._inproc_bridge is not None:
                try:
                    result = self._inproc_bridge.set_variable(var_ref, name, value)
                    return cast("SetVariableResponseBody", result)
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
        self, expression: str, frame_id: int | None = None, context: str | None = None
    ) -> EvaluateResponseBody:
        """Evaluate an expression in a specific context"""
        if self.in_process and self._inproc_bridge is not None:
            try:
                result = self._inproc_bridge.evaluate(expression, frame_id, context)
                return cast("EvaluateResponseBody", result)
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
                "context": context or "hover",
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

    async def exception_info(self, thread_id: int) -> ExceptionInfoResponseBody:
        """Get exception information for a thread"""
        command = {
            "command": "exceptionInfo",
            "arguments": {"threadId": thread_id},
        }

        response = await self._send_command_to_debuggee(command, expect_response=True)

        if response and "body" in response:
            return cast("ExceptionInfoResponseBody", response["body"])

        exception_details: ExceptionDetails = {
            "message": "Exception information not available",
            "typeName": "Unknown",
            "fullTypeName": "Unknown",
            "stackTrace": "Exception information not available",
        }

        return {
            "exceptionId": "Unknown",
            "description": "Exception information not available",
            "breakMode": "unhandled",
            "details": exception_details,
        }

    async def get_exception_info(self, thread_id: int) -> ExceptionInfoResponseBody:
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
    ) -> EvaluateResponseBody:
        """Evaluate an expression (alias for evaluate)"""
        return await self.evaluate(expression, frame_id, context)

    async def handle_debug_message(self, message) -> None:
        """Handle a debug protocol message (alias for _handle_debug_message)"""
        if isinstance(message, dict):
            message = json.dumps(message)
        self._handle_debug_message(message)
        # Give the loop a chance to run any tasks spawned by the handler so
        # tests that assert immediately after this call observe the effects.
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:
            await asyncio.sleep(0)

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
                lambda: self.process.stdin.write(f"{command}\n")
                if self.process and self.process.stdin
                else None,
            )
        except Exception:
            logger.exception("Error sending command to debuggee")

    async def shutdown(self) -> None:
        """Shut down the debugger and clean up resources."""
        # Cancel background tasks
        for task in list(self._bg_tasks):
            task.cancel()

        # Fail all pending command futures
        with self.lock:
            pending = dict(self._pending_commands)
            self._pending_commands.clear()

        shutdown_error = RuntimeError("Debugger shutdown")
        for cid, fut in pending.items():
            if fut.done():
                continue
            try:
                fut.set_exception(shutdown_error)
            except Exception:
                # Future may be on a different loop; try thread-safe scheduling
                try:
                    self.loop.call_soon_threadsafe(
                        lambda f=fut: f.done() or f.set_exception(shutdown_error)
                    )
                except Exception:
                    logger.debug("failed to fail pending future %s", cid)

        # Clean up event loop if we own it
        if self.loop:
            with contextlib.suppress(Exception):
                await self.loop.shutdown_asyncgens()

            if getattr(self, "_owns_loop", False):
                with contextlib.suppress(Exception):
                    if self.loop.is_running():
                        self.loop.stop()
                with contextlib.suppress(Exception):
                    if not self.loop.is_closed():
                        self.loop.close()

        # Close process stdio streams
        proc = self.process
        if proc is not None:
            for stream_name in ("stdin", "stdout", "stderr"):
                with contextlib.suppress(Exception):
                    stream = getattr(proc, stream_name, None)
                    if stream is not None:
                        stream.close()

            with contextlib.suppress(Exception):
                self.ipc.cleanup()

        # Clear state
        self.var_refs.clear()
        self.threads.clear()
        self.breakpoints.clear()
        self.function_breakpoints.clear()
        self.current_stack_frames.clear()
        self.program_running = False
        self.is_terminated = True


class DebugAdapterServer(DebugServer):
    """Server implementation that handles DAP protocol communication.

    This class implements the DebugServer protocol expected by PyDebugger.
    """

    def __init__(
        self,
        connection: ConnectionBase,
        loop: asyncio.AbstractEventLoop | None = None,
    ):
        self.connection = connection
        self.request_handler = RequestHandler(self)
        # Prefer caller-supplied or running loop; create one only if needed.
        self.loop, _ = _acquire_event_loop(loop)  # _owns unused here
        self._debugger = PyDebugger(self, self.loop)
        self.running = False
        self.sequence_number = 0
        self.protocol_handler = ProtocolHandler()

    @property
    def debugger(self) -> PyDebugger:
        """Get the debugger instance."""
        return self._debugger

    def spawn_threadsafe(self, callback: Callable[[], Any]) -> None:
        """Schedule a callback to be run on the server's event loop.

        This implements the DebugServer protocol method.

        Args:
            callback: The function to call on the server's event loop
        """
        if not self.loop.is_running():
            logger.warning("Event loop is not running, cannot schedule callback")
            return

        def _wrapped() -> None:
            try:
                callback()
            except Exception:
                logger.exception("Error in spawn_threadsafe callback")

        self.loop.call_soon_threadsafe(_wrapped)

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
            response = await self.request_handler.handle_request(cast("DAPRequest", request))
            if response:
                await self.send_message(cast("dict[str, Any]", response))
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
        response = self.protocol_handler.create_response(
            cast("GenericRequest", request), True, body
        )
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
