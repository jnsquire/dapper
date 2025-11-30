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
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from dapper.adapter.external_backend import ExternalProcessBackend
from dapper.adapter.inprocess_backend import InProcessBackend
from dapper.adapter.inprocess_bridge import InProcessBridge
from dapper.adapter.payload_extractor import extract_payload
from dapper.adapter.request_handlers import RequestHandler
from dapper.adapter.source_tracker import LoadedSourceTracker
from dapper.adapter.types import BreakpointDict
from dapper.adapter.types import BreakpointResponse
from dapper.adapter.types import DAPRequest
from dapper.adapter.types import PyDebuggerThread
from dapper.adapter.types import SourceDict
from dapper.core.inprocess_debugger import InProcessDebugger
from dapper.ipc import TransportConfig
from dapper.ipc.ipc_adapter import IPCContextAdapter
from dapper.protocol.protocol import ProtocolHandler
from dapper.protocol.structures import Source
from dapper.protocol.structures import SourceBreakpoint

try:
    # Optional integration module; may not be present on all platforms.
    from dapper._frame_eval.debugger_integration import integrate_py_debugger
except Exception:  # pragma: no cover - optional feature
    integrate_py_debugger = None


if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Sequence

    from dapper.config import DapperConfig
    from dapper.ipc.connections.base import ConnectionBase
    from dapper.protocol.capabilities import ExceptionFilterOptions
    from dapper.protocol.capabilities import ExceptionOptions
    from dapper.protocol.data_breakpoints import DataBreakpointInfoResponseBody
    from dapper.protocol.debugger_protocol import Variable
    from dapper.protocol.messages import GenericRequest
    from dapper.protocol.requests import ContinueResponseBody
    from dapper.protocol.requests import EvaluateResponseBody
    from dapper.protocol.requests import ExceptionDetails
    from dapper.protocol.requests import ExceptionInfoResponseBody
    from dapper.protocol.requests import FunctionBreakpoint
    from dapper.protocol.requests import Module
    from dapper.protocol.requests import SetVariableResponseBody
    from dapper.protocol.requests import StackTraceResponseBody
    from dapper.protocol.structures import Breakpoint
    from dapper.protocol.structures import Scope
    from dapper.protocol.structures import Thread


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


class PyDebugger:
    """
    Main debugger class that integrates with Python's built-in debugging tools
    and communicates back to the DebugAdapterServer.
    """

    def __init__(
        self,
        server: DebugAdapterServer,
        loop: asyncio.AbstractEventLoop | None = None,
        enable_frame_eval: bool = False,
    ):
        """Initialize the PyDebugger.

        Args:
            server: The debug adapter server instance
            loop: Optional event loop to use. If not provided, gets the current event loop.
            enable_frame_eval: Whether to enable frame evaluation optimization.
        """
        self.server: DebugAdapterServer = server
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
        self._source_introspection = LoadedSourceTracker()
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

        # Backend for debugging operations (set in launch/attach)
        self._inproc_backend: InProcessBackend | None = None
        self._external_backend: ExternalProcessBackend | None = None

        # Optional IPC transport context (initialized lazily in launch)
        self._use_ipc: bool = False
        self.ipc: IPCContextAdapter = IPCContextAdapter()

        # Data breakpoint containers
        self._data_watches: dict[str, dict[str, Any]] = {}  # dataId -> watch metadata
        self._frame_watches: dict[int, list[str]] = {}  # frameId -> list of dataIds

    @property
    def program_path(self) -> str | None:
        """Get the program path being debugged."""
        return self._source_introspection.program_path

    @program_path.setter
    def program_path(self, value: str | None) -> None:
        """Set the program path being debugged."""
        self._source_introspection.program_path = value

    @property
    def _backend(self) -> InProcessBackend | ExternalProcessBackend | None:
        """Get the active debugger backend."""
        if self._inproc_backend is not None:
            return self._inproc_backend
        return self._external_backend

    def _get_next_command_id(self) -> int:
        """Get the next command ID and increment the counter."""
        cmd_id = self._next_command_id
        self._next_command_id += 1
        return cmd_id

    def _get_process_state(self) -> tuple[subprocess.Popen | None, bool]:
        """Get the current process state for the external backend."""
        return self.process, self.is_terminated

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

    def _emit_event(self, event_name: str, payload: dict[str, Any]) -> None:
        """Schedule an event to be sent to the DAP client.

        This is the preferred way to send events from synchronous callbacks
        and background threads. The event is scheduled on the event loop
        via spawn_threadsafe.
        """
        self.spawn_threadsafe(lambda: self.server.send_event(event_name, payload))

    async def launch(self, config: DapperConfig) -> None:
        """Launch a new Python program for debugging using centralized configuration."""
        # Validate configuration
        config.validate()
        
        if self.program_running:
            msg = "A program is already being debugged"
            raise RuntimeError(msg)

        # Update server state from config
        self.program_path = str(Path(config.debuggee.program).resolve())
        self.stop_on_entry = config.debuggee.stop_on_entry
        self.no_debug = config.debuggee.no_debug
        self.in_process = config.in_process

        # Optional in-process mode
        if config.in_process:
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
        for arg in config.debuggee.args:
            debug_args.extend(["--arg", arg])

        if config.debuggee.stop_on_entry:
            debug_args.append("--stop-on-entry")

        if config.debuggee.no_debug:
            debug_args.append("--no-debug")

        # If IPC is requested, prepare a listener and pass coordinates.
        # IPC is now mandatory; always enable it.
        self._use_ipc = True
        self.ipc.set_binary(bool(config.ipc.use_binary))
        
        # Create transport config for the factory
        transport_config = TransportConfig(
            transport=config.ipc.transport,
            pipe_name=config.ipc.pipe_name,
            host=config.ipc.host,
            port=config.ipc.port,
            path=config.ipc.path,
            use_binary=config.ipc.use_binary
        )
        
        debug_args.extend(self.ipc.create_listener(
            transport_config=transport_config
        ))
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
            # Create a wrapper to handle dict messages from binary IPC
            def _handle_ipc_message(message: dict[str, Any]) -> None:
                """Handle IPC message that may be already parsed (binary) or string."""
                if isinstance(message, dict):
                    # For binary IPC, the message is already parsed
                    asyncio.run_coroutine_threadsafe(
                        self.handle_debug_message(message), self.loop
                    )
                else:
                    # For regular IPC, the message is a string
                    self._handle_debug_message(message)
            
            self.ipc.start_reader(_handle_ipc_message, accept=True)

        # Create the external process backend
        self._external_backend = ExternalProcessBackend(
            ipc=self.ipc,
            loop=self.loop,
            get_process_state=self._get_process_state,
            pending_commands=self._pending_commands,
            lock=self.lock,
            get_next_command_id=self._get_next_command_id,
        )

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
        if self.stop_on_entry and not self.no_debug:
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
        # Create the in-process backend
        self._inproc_backend = InProcessBackend(self._inproc_bridge)

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
            self._emit_event("output", {"category": category, "output": output})
        except Exception:
            logger.exception("error in on_output callback")

    async def attach(self, config: DapperConfig) -> None:
        """Attach to an already running debuggee via IPC using centralized configuration."""
        # Validate configuration
        config.validate()
        
        # Create transport config for the factory
        transport_config = TransportConfig(
            transport=config.ipc.transport,
            pipe_name=config.ipc.pipe_name,
            host=config.ipc.host,
            port=config.ipc.port,
            path=config.ipc.path,
            use_binary=config.ipc.use_binary
        )
        
        # Connect using the new transport configuration
        self.ipc.connect(
            transport=transport_config.transport,
            pipe_name=transport_config.pipe_name,
            unix_path=transport_config.path,
            host=transport_config.host,
            port=transport_config.port,
        )

        # Start reader thread (connection already established)
        # Create a wrapper to handle dict messages from binary IPC
        def _handle_ipc_message(message: dict[str, Any]) -> None:
            """Handle IPC message that may be already parsed (binary) or string."""
            if isinstance(message, dict):
                # For binary IPC, the message is already parsed
                asyncio.run_coroutine_threadsafe(
                    self.handle_debug_message(message), self.loop
                )
            else:
                # For regular IPC, the message is a string
                self._handle_debug_message(message)
        
        self.ipc.start_reader(_handle_ipc_message, accept=False)

        # Create the external process backend
        self._external_backend = ExternalProcessBackend(
            ipc=self.ipc,
            loop=self.loop,
            get_process_state=self._get_process_state,
            pending_commands=self._pending_commands,
            lock=self.lock,
            get_next_command_id=self._get_next_command_id,
        )

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
        """Read output from the debuggee's stdout/stderr streams.

        Debug protocol messages are received via IPC, not stdout/stderr.
        This method only forwards program output to the DAP client.
        """
        try:
            while True:
                line = stream.readline()
                if not line:
                    break

                # Forward program output to DAP client
                self._emit_event("output", {"category": category, "output": line})
        except Exception:
            logger.exception("Error reading %s", category)

    def _handle_event_stopped(self, data: dict[str, Any]) -> None:
        """Handle stopped event state updates."""
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

        try:
            self.stopped_event.set()
        except Exception:
            try:
                self.loop.call_soon_threadsafe(self.stopped_event.set)
            except Exception:
                with contextlib.suppress(Exception):
                    self.stopped_event.set()

    def _handle_event_thread(self, data: dict[str, Any]) -> None:
        """Handle thread started/exited state updates."""
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

    def _handle_event_exited(self, data: dict[str, Any]) -> None:
        """Handle debuggee exited event and schedule cleanup."""
        exit_code = data.get("exitCode", 0)
        self.is_terminated = True
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
        """Handle a debug protocol message from the debuggee."""
        try:
            data: dict[str, Any] = json.loads(message)
        except Exception:
            logger.exception("Error handling debug message")
            return

        # Handle command responses
        command_id = data.get("id")
        if command_id is not None and command_id in self._pending_commands:
            with self.lock:
                future = self._pending_commands.pop(command_id, None)
            if future is not None:
                self._resolve_pending_response(future, data)
            return

        event_type: str | None = data.get("event")
        if event_type is None:
            return

        # Events that require state updates before forwarding
        if event_type == "stopped":
            self._handle_event_stopped(data)
        elif event_type == "thread":
            self._handle_event_thread(data)
        elif event_type == "exited":
            self._handle_event_exited(data)
            return  # exited schedules its own events
        # Events that only cache state (no forwarding)
        elif event_type == "stackTrace":
            self._handle_event_stacktrace(data)
            return
        elif event_type == "variables":
            self._handle_event_variables(data)
            return

        # Forward all events that have payload extractors
        payload = extract_payload(event_type, data)
        if payload is not None:
            self._emit_event(event_type, payload)

    def _resolve_pending_response(
        self, future: asyncio.Future[dict[str, Any]], data: dict[str, Any]
    ) -> None:
        """Resolve a pending response future on the debugger's event loop."""
        if future.done():
            return

        def _set_result() -> None:
            if not future.done():
                future.set_result(data)

        # If already on the debugger loop, resolve directly
        try:
            if asyncio.get_running_loop() is self.loop:
                _set_result()
                return
        except RuntimeError:
            pass  # No running loop, use thread-safe scheduling

        try:
            self.loop.call_soon_threadsafe(_set_result)
        except Exception:
            logger.debug("failed to schedule resolution on debugger loop")

    async def _handle_program_exit(self, exit_code: int) -> None:
        """Handle the debuggee program exit"""
        if self.program_running:
            self.program_running = False
            self.is_terminated = True

            await self.server.send_event("exited", {"exitCode": exit_code})
            await self.server.send_event("terminated")

    async def set_breakpoints(
        self, source: SourceDict | str, breakpoints: list[SourceBreakpoint]
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
            return [BreakpointResponse(verified=False, message="Source path is required") for _ in breakpoints]
        path = str(Path(path).resolve())

        # Process breakpoints
        spec_list, storage_list = self._process_breakpoints(breakpoints)
        self.breakpoints[path] = storage_list

        if self._backend is None:
            return [
                BreakpointResponse(
                    verified=bp.get("verified", False),
                    **{k: v for k, v in {
                        "message": bp.get("message"),
                        "line": bp.get("line"),
                        "condition": bp.get("condition"),
                        "hitCondition": bp.get("hitCondition"),
                        "logMessage": bp.get("logMessage")
                    }.items() if v is not None}
                )
                for bp in storage_list
            ]

        # For in-process backend, just use the backend directly
        if self._inproc_backend is not None:
            backend_result = await self._inproc_backend.set_breakpoints(path, spec_list)
            return [
                BreakpointResponse(
                    verified=bp.get("verified", False),
                    **{k: v for k, v in {
                        "line": bp.get("line"),
                        "condition": bp.get("condition"),
                        "hitCondition": bp.get("hitCondition"),
                        "logMessage": bp.get("logMessage")
                    }.items() if v is not None}
                )
                for bp in backend_result
            ]

        # For external process, add progress events around the backend call
        try:
            progress_id = f"setBreakpoints:{path}:{int(time.time() * 1000)}"
        except Exception:
            progress_id = f"setBreakpoints:{path}"

        self._emit_event("progressStart", {"progressId": progress_id, "title": "Setting breakpoints"})

        await self._backend.set_breakpoints(path, spec_list)
        self._forward_breakpoint_events(storage_list)

        self._emit_event("progressEnd", {"progressId": progress_id})

        return [
            BreakpointResponse(
                verified=bp.get("verified", False),
                **{k: v for k, v in {
                    "message": bp.get("message"),
                    "line": bp.get("line"),
                    "condition": bp.get("condition"),
                    "hitCondition": bp.get("hitCondition"),
                    "logMessage": bp.get("logMessage")
                }.items() if v is not None}
            )
            for bp in storage_list
        ]

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

    def _forward_breakpoint_events(self, storage_list: list[BreakpointDict]) -> None:
        """Forward breakpoint-changed events to clients."""
        try:
            for bp in storage_list:
                self._emit_event("breakpoint", {
                    "reason": "changed",
                    "breakpoint": {
                        "verified": bp.get("verified", True),
                        "line": bp.get("line"),
                    },
                })
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

            storage_entry: FunctionBreakpoint = {"name": name, "verified": True}
            if cond is not None:
                storage_entry["condition"] = str(cond)
            if hc is not None:
                storage_entry["hitCondition"] = str(hc)
            storage_funcs.append(storage_entry)

        # Store runtime representation (with verified flag) for IPC and state
        self.function_breakpoints = storage_funcs

        if self._backend is not None:
            return await self._backend.set_function_breakpoints(spec_funcs)
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

        if self._backend is not None:
            return await self._backend.set_exception_breakpoints(
                filters, filter_options, exception_options  # type: ignore[arg-type]
            )

        # Best-effort: assume the breakpoints were set when no backend available
        return [{"verified": True} for _ in filters]

    async def continue_execution(self, thread_id: int) -> ContinueResponseBody:
        """Continue execution of the specified thread"""
        if not self.program_running or self.is_terminated:
            return {"allThreadsContinued": False}

        self.stopped_event.clear()

        with self.lock:
            if thread_id in self.threads:
                self.threads[thread_id].is_stopped = False

        if self._backend is not None:
            return await self._backend.continue_(thread_id)

        return {"allThreadsContinued": False}

    async def next(self, thread_id: int) -> None:
        """Step over to the next line"""
        if not self.program_running or self.is_terminated:
            return

        self.stopped_event.clear()

        if self._backend is not None:
            await self._backend.next_(thread_id)

    async def step_in(self, thread_id: int) -> None:
        """Step into a function"""
        if not self.program_running or self.is_terminated:
            return

        self.stopped_event.clear()

        if self._backend is not None:
            await self._backend.step_in(thread_id)

    async def step_out(self, thread_id: int) -> None:
        """Step out of the current function"""
        if not self.program_running or self.is_terminated:
            return

        self.stopped_event.clear()

        if self._backend is not None:
            await self._backend.step_out(thread_id)

    async def pause(self, thread_id: int) -> bool:
        """Pause execution of the specified thread"""
        if not self.program_running or self.is_terminated:
            return False

        if self._backend is not None:
            return await self._backend.pause(thread_id)
        return False

    async def get_threads(self) -> list[Thread]:
        """Get all threads"""
        threads: list[Thread] = []
        with self.lock:
            for thread_id, thread in self.threads.items():
                threads.append({"id": thread_id, "name": thread.name})

        return threads

    async def get_loaded_sources(self) -> list[Source]:
        """Get all loaded source files."""
        return self._source_introspection.get_loaded_sources()

    async def get_modules(self) -> list[Module]:
        """Get all loaded Python modules."""
        return self._source_introspection.get_modules()

    async def get_stack_trace(
        self, thread_id: int, start_frame: int = 0, levels: int = 0
    ) -> StackTraceResponseBody:
        """Get stack trace for a thread"""
        if self._backend is not None:
            result = await self._backend.get_stack_trace(thread_id, start_frame, levels)
            if result.get("stackFrames"):
                return result

        # Fall back to cached stack frames if backend returned empty
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
        if self._backend is not None:
            result = await self._backend.get_variables(variables_reference, filter_type, start, count)
            if result:
                return result

        # Fall back to cached variables
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
            if self._backend is not None:
                return await self._backend.set_variable(var_ref, name, value)
            return {"value": value, "type": "string", "variablesReference": 0}

        msg = f"Cannot set variable in reference type: {type(ref_info)}"
        raise ValueError(msg)

    async def evaluate(
        self, expression: str, frame_id: int | None = None, context: str | None = None
    ) -> EvaluateResponseBody:
        """Evaluate an expression in a specific context"""
        if self._backend is not None:
            return await self._backend.evaluate(expression, frame_id, context)
        return {
            "result": f"<evaluation of '{expression}' not available>",
            "type": "string",
            "variablesReference": 0,
        }

    async def exception_info(self, thread_id: int) -> ExceptionInfoResponseBody:
        """Get exception information for a thread"""
        if self._backend is not None:
            return await self._backend.exception_info(thread_id)

        exception_details: ExceptionDetails = {
            "message": "Exception information not available",
            "typeName": "Unknown",
            "fullTypeName": "Unknown",
            "source": "Unknown",
            "stackTrace": ["Exception information not available"],
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

        if self._backend is not None:
            await self._backend.configuration_done()

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
        if self._backend is not None:
            await self._backend.terminate()

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
                self.is_terminated = True
                self.program_running = False
            except Exception:
                logger.exception("Error terminating process")

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
                stream = getattr(proc, stream_name, None)
                if stream is not None:
                    stream.close()

            await self.ipc.acleanup()

        # Clear state
        self.var_refs.clear()
        self.threads.clear()
        self.breakpoints.clear()
        self.function_breakpoints.clear()
        self.current_stack_frames.clear()
        self.program_running = False
        self.is_terminated = True


class DebugAdapterServer:
    """Server implementation that handles DAP protocol communication.

    This class provides the server interface expected by PyDebugger and handles
    the Debug Adapter Protocol communication with the client.
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
