"""Implementation of integrated Python debugger components.

This module contains the debugger orchestration (`PyDebugger`) and helper
managers used by the adapter server core.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
import threading
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from dapper.adapter.debugger.breakpoint_facade import _PyDebuggerBreakpointFacade
from dapper.adapter.debugger.event_router import _PyDebuggerEventRouter
from dapper.adapter.debugger.execution import _PyDebuggerExecutionManager
from dapper.adapter.debugger.lifecycle import _PyDebuggerLifecycleManager
from dapper.adapter.debugger.py_debugger_compat import _PyDebuggerSessionCompatMixin
from dapper.adapter.debugger.runtime import _PyDebuggerRuntimeManager
from dapper.adapter.debugger.session import _PyDebuggerSessionFacade
from dapper.adapter.debugger.state import _PyDebuggerStateManager
from dapper.adapter.hot_reload import HotReloadService
from dapper.adapter.source_tracker import LoadedSourceTracker
from dapper.core.asyncio_task_inspector import AsyncioTaskRegistry
from dapper.core.breakpoint_manager import BreakpointManager
from dapper.core.variable_manager import VariableManager
from dapper.ipc.ipc_manager import IPCManager

try:
    # Optional integration module; may not be present on all platforms.
    from dapper._frame_eval.debugger_integration import integrate_py_debugger
except Exception:  # pragma: no cover - optional feature
    integrate_py_debugger = None


if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Sequence
    import subprocess

    from dapper.adapter.external_backend import ExternalProcessBackend
    from dapper.adapter.inprocess_backend import InProcessBackend
    from dapper.adapter.inprocess_bridge import InProcessBridge
    from dapper.adapter.types import BreakpointDict
    from dapper.adapter.types import BreakpointResponse
    from dapper.adapter.types import CompletionsResponseBody
    from dapper.adapter.types import DebuggerServerProtocol
    from dapper.adapter.types import SourceDict
    from dapper.config import DapperConfig
    from dapper.core.inprocess_debugger import InProcessDebugger
    from dapper.protocol.capabilities import ExceptionFilterOptions
    from dapper.protocol.capabilities import ExceptionOptions
    from dapper.protocol.data_breakpoints import DataBreakpointInfoResponseBody
    from dapper.protocol.debugger_protocol import Variable
    from dapper.protocol.requests import ContinueResponseBody
    from dapper.protocol.requests import EvaluateResponseBody
    from dapper.protocol.requests import ExceptionInfoResponseBody
    from dapper.protocol.requests import FunctionBreakpoint
    from dapper.protocol.requests import HotReloadOptions
    from dapper.protocol.requests import HotReloadResponseBody
    from dapper.protocol.requests import Module
    from dapper.protocol.requests import SetVariableResponseBody
    from dapper.protocol.requests import StackTraceResponseBody
    from dapper.protocol.structures import Breakpoint
    from dapper.protocol.structures import Scope
    from dapper.protocol.structures import Source
    from dapper.protocol.structures import SourceBreakpoint
    from dapper.protocol.structures import Thread


logger = logging.getLogger(__name__)


class PyDebuggerSteppingState:
    """Minimal stepping-controller state usage expected by shared helpers.

    Acts as a lightweight placeholder for stepping state attributes required
    by shared debugger utilities, even if PyDebugger manages execution differently.
    """

    def __init__(self) -> None:
        self.stepping: bool = False
        self.current_frame: Any | None = None


class PyDebuggerDataBreakpointAdapter:
    """Adapter exposing data-breakpoint bookkeeping in protocol form.

    Translates PyDebugger's internal data-watch storage (keyed by dataId)
    into the format expected by shared handlers (watch names and metadata).
    """

    def __init__(self, debugger: PyDebugger) -> None:
        self._debugger = debugger

    _FRAME_DATA_ID_PARTS = 4

    @property
    def watch_names(self) -> set[str]:
        names: set[str] = set()
        for data_id in self._debugger.get_data_watch_keys():
            parts = data_id.split(":")
            if (
                len(parts) >= self._FRAME_DATA_ID_PARTS
                and parts[0] == "frame"
                and parts[2] == "var"
            ):
                names.add(parts[3])
        return names

    @property
    def watch_meta(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for data_id, meta in self._debugger.get_data_watch_items():
            parts = data_id.split(":")
            if (
                len(parts) >= self._FRAME_DATA_ID_PARTS
                and parts[0] == "frame"
                and parts[2] == "var"
            ):
                out[parts[3]] = meta
        return out

    @property
    def data_watches(self) -> dict[str, Any]:
        return self._debugger.get_data_watch_map()

    @property
    def frame_watches(self) -> dict[int, list[str]]:
        return self._debugger.get_frame_watch_map()


class PyDebuggerExceptionConfigAdapter:
    """Adapter exposing exception breakpoint flags via config fields.

    Maps the shared exception handler configuration interface to
    PyDebugger's internal boolean flags.
    """

    def __init__(self, debugger: PyDebugger) -> None:
        self._debugger = debugger

    @property
    def break_on_raised(self) -> bool:
        return self._debugger.exception_breakpoints_raised

    @break_on_raised.setter
    def break_on_raised(self, value: bool) -> None:
        self._debugger.exception_breakpoints_raised = bool(value)

    @property
    def break_on_uncaught(self) -> bool:
        return self._debugger.exception_breakpoints_uncaught

    @break_on_uncaught.setter
    def break_on_uncaught(self, value: bool) -> None:
        self._debugger.exception_breakpoints_uncaught = bool(value)


class PyDebuggerExceptionHandlerAdapter:
    """Adapter exposing exception config via `exception_handler.config`.

    Provides the structure expected by shared exception handling utilities.
    """

    def __init__(self, debugger: PyDebugger) -> None:
        self.config = PyDebuggerExceptionConfigAdapter(debugger)


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


class PyDebugger(_PyDebuggerSessionCompatMixin):
    """Main debugger class that integrates with Python's built-in debugging tools
    and communicates back to the DebugAdapterServer.
    """

    def __init__(
        self,
        server: DebuggerServerProtocol,
        loop: asyncio.AbstractEventLoop | None = None,
        enable_frame_eval: bool = False,
    ):
        """Initialize the PyDebugger.

        Args:
            server: The debug adapter server instance
            loop: Optional event loop to use. If not provided, gets the current event loop.
            enable_frame_eval: Whether to enable frame evaluation optimization.

        """
        self.server: DebuggerServerProtocol = server
        self.loop: asyncio.AbstractEventLoop
        self._owns_loop: bool
        self.loop, self._owns_loop = _acquire_event_loop(loop)

        if enable_frame_eval and integrate_py_debugger is not None:
            # Optional integration - resolved at import time to avoid dynamic
            # imports at runtime. The integration function may be None if the
            # frame-eval module is not available on this platform.
            integrate_py_debugger(self)

        self.lock: threading.RLock = threading.RLock()
        self._session_facade = _PyDebuggerSessionFacade(self.lock, self.loop)

        # Core state
        self.main_thread_id: int | None = None
        self.next_thread_id: int = 1
        self.variable_manager = VariableManager()
        self.breakpoint_manager = BreakpointManager()
        # Exception breakpoint flags (two booleans for clarity)
        self.exception_breakpoints_uncaught: bool = False
        self.exception_breakpoints_raised: bool = False
        self.process: subprocess.Popen | None = None
        self.debugger_thread: threading.Thread | None = None
        self.is_terminated: bool = False
        self.program_running: bool = False
        self.stop_on_entry: bool = False
        self.no_debug: bool = False
        self._source_introspection = LoadedSourceTracker()
        # Use thread-safe Event objects for synchronization. Tests and
        # asyncio code may await these — the helper `_await_event` will
        # bridge the synchronous wait to an awaitable when needed.
        self.stopped_event = threading.Event()
        self.configuration_done = threading.Event()

        # Keep references to background tasks so they don't get GC'd
        self._bg_tasks: set[asyncio.Task] = set()

        # Test mode flag (used by tests to start debuggee in a real thread)
        self._test_mode: bool = False

        # In-process debugging support (optional/opt-in)
        self.in_process: bool = False
        self._inproc_bridge: InProcessBridge | None = None

        # Backend for debugging operations (set in launch/attach)
        self._inproc_backend: InProcessBackend | None = None
        self._external_backend: ExternalProcessBackend | None = None

        # Optional IPC transport context (initialized lazily in launch)
        self._use_ipc: bool = False
        self.ipc: IPCManager = IPCManager()

        # Optional current frame reference for runtime helpers and tests
        # May hold a real frame (types.FrameType) or a frame-like object used in tests
        self.current_frame: Any | None = None

        # Event routing/decomposition
        self._event_router = _PyDebuggerEventRouter(self)
        # Launch/attach lifecycle decomposition
        self._lifecycle_manager = _PyDebuggerLifecycleManager(self)
        # Breakpoint/state-inspection decomposition
        self._state_manager = _PyDebuggerStateManager(self)
        self._breakpoint_facade = _PyDebuggerBreakpointFacade(self)
        # Runtime/process/IPC decomposition
        self._runtime_manager = _PyDebuggerRuntimeManager(self)
        # Execution-control/lifecycle decomposition
        self._execution_manager = _PyDebuggerExecutionManager(self)
        self._hot_reload_service = HotReloadService(self)

        self.stepping_controller = PyDebuggerSteppingState()
        # Direct assignment - VariableManager is already compatible
        self.data_bp_state = PyDebuggerDataBreakpointAdapter(self)
        self.exception_handler = PyDebuggerExceptionHandlerAdapter(self)

        self.var_manager = self.variable_manager
        self.bp_manager = self.breakpoint_manager

        # Asyncio task inspector — exposes live tasks as pseudo-threads.
        self._task_registry: AsyncioTaskRegistry = AsyncioTaskRegistry()

    @property
    def task_registry(self) -> AsyncioTaskRegistry:
        """Return the asyncio task inspector registry for this session.

        Exposes live :class:`asyncio.Task` objects as DAP pseudo-threads and
        provides pre-built coroutine stack-frame summaries for each task.
        The registry is rebuilt on every ``threads`` request and cleared
        automatically when execution resumes.
        """
        return self._task_registry

    @property
    def session_facade(self) -> _PyDebuggerSessionFacade:
        """Return the session facade for debugger state interactions."""
        return self._session_facade

    def get_data_watch_keys(self) -> list[str]:
        """Return a snapshot of data-watch keys."""
        return list(self._session_facade.data_watches.keys())

    def get_data_watch_items(self) -> list[tuple[str, dict[str, Any]]]:
        """Return a snapshot of data-watch metadata entries."""
        return list(self._session_facade.data_watches.items())

    def get_data_watch_map(self) -> dict[str, dict[str, Any]]:
        """Return data-watch metadata mapping."""
        return self._session_facade.data_watches

    def get_frame_watch_map(self) -> dict[int, list[str]]:
        """Return frame-to-data-watch index mapping."""
        return self._session_facade.frame_watches

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
                    task.add_done_callback(self._bg_tasks.discard)

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
            logger.debug("Event introspection failed, trying fallback", exc_info=True)

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
        return self._breakpoint_facade.data_breakpoint_info(name=name, frame_id=frame_id)

    def set_data_breakpoints(self, breakpoints: list[dict[str, Any]]) -> list[Breakpoint]:
        """Register a set of data breakpoints (bookkeeping only)."""
        return self._breakpoint_facade.set_data_breakpoints(breakpoints)

    def _emit_event(self, event_name: str, payload: dict[str, Any]) -> None:
        """Schedule an event to be sent to the DAP client.

        This is the preferred way to send events from synchronous callbacks
        and background threads. The event is scheduled on the event loop
        via spawn_threadsafe.
        """
        self.spawn_threadsafe(lambda: self.server.send_event(event_name, payload))

    async def launch(self, config: DapperConfig) -> None:
        """Launch a new Python program for debugging using centralized configuration."""
        await self._lifecycle_manager.launch(config)

    def _handle_inproc_output(self, category: str, output: str) -> None:
        """Forward output events from in-process debugger to the server."""
        try:
            self._emit_event("output", {"category": category, "output": output})
        except Exception:
            logger.exception("error in on_output callback")

    async def attach(self, config: DapperConfig) -> None:
        """Attach to an already running debuggee via IPC using centralized configuration."""
        await self._lifecycle_manager.attach(config)

    def is_test_mode_enabled(self) -> bool:
        """Return whether test mode is enabled for launch orchestration."""
        return getattr(self, "_test_mode", False)

    def start_ipc_reader(self, *, accept: bool) -> None:
        """Start IPC reader with message handling suitable for selected transport."""
        self._runtime_manager.start_ipc_reader(accept=accept)

    def create_external_backend(self) -> None:
        """Create and register the external-process backend."""
        self._runtime_manager.create_external_backend()

    def get_active_backend(self) -> InProcessBackend | ExternalProcessBackend | None:
        """Return the currently active backend (in-process preferred)."""
        if self._inproc_backend is not None:
            return self._inproc_backend
        return self._external_backend

    def get_inprocess_backend(self) -> InProcessBackend | None:
        """Return in-process backend when active."""
        return self._inproc_backend

    def process_breakpoints(
        self,
        breakpoints: Sequence[SourceBreakpoint],
    ) -> tuple[list[SourceBreakpoint], list[BreakpointDict]]:
        """Public wrapper for breakpoint normalization logic."""
        return self._process_breakpoints(breakpoints)

    def forward_breakpoint_events(self, storage_list: list[BreakpointDict]) -> None:
        """Public wrapper for breakpoint-change event forwarding."""
        self._forward_breakpoint_events(storage_list)

    def start_debuggee_process(self, debug_args: list[str]) -> None:
        """Public wrapper to start the debuggee process for lifecycle components."""
        self._runtime_manager.start_debuggee_process(debug_args)

    def _start_debuggee_process(self, debug_args: list[str]) -> None:
        """Compatibility alias for tests that patch the legacy private method."""
        self.start_debuggee_process(debug_args)

    def schedule_program_exit(self, exit_code: int) -> None:
        """Schedule process-exit handling on the debugger event loop."""
        self.spawn_threadsafe(lambda c=exit_code: self._handle_program_exit(c))

    async def await_stop_event(self) -> None:
        """Await the debugger stopped-event in an asyncio-friendly way."""
        await self._await_event(self.stopped_event)

    def enable_ipc_mode(self) -> None:
        """Enable IPC mode for launch lifecycle orchestration."""
        self._use_ipc = True

    def has_pending_command(self, command_id: int) -> bool:
        """Return whether a command id has a pending response future."""
        return self._session_facade.has_pending_command(command_id)

    def pop_pending_command(self, command_id: int) -> asyncio.Future[dict[str, Any]] | None:
        """Pop and return pending command future for a command id."""
        return self._session_facade.pop_pending_command(command_id)

    def resolve_pending_response(
        self,
        future: asyncio.Future[dict[str, Any]],
        data: dict[str, Any],
    ) -> None:
        """Resolve a pending response on the debugger loop."""
        self._session_facade.resolve_pending_response(future, data)

    def emit_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Public event emission wrapper for extracted components."""
        self._emit_event(event_type, payload)

    def handle_event_stopped(self, data: dict[str, Any]) -> None:
        """Public wrapper for stopped-event handling."""
        self._event_router.handle_event_stopped(data)

    def handle_event_thread(self, data: dict[str, Any]) -> None:
        """Public wrapper for thread-event handling."""
        self._event_router.handle_event_thread(data)

    def handle_event_exited(self, data: dict[str, Any]) -> None:
        """Public wrapper for exited-event handling."""
        self._event_router.handle_event_exited(data)

    def handle_inprocess_output(self, category: str, output: str) -> None:
        """Public wrapper for in-process output forwarding."""
        self._handle_inproc_output(category, output)

    def create_inprocess_bridge(
        self,
        inproc: InProcessDebugger,
        *,
        on_stopped: Callable[[dict[str, Any]], None],
        on_thread: Callable[[dict[str, Any]], None],
        on_exited: Callable[[dict[str, Any]], None],
        on_output: Callable[[str, str], None],
    ) -> None:
        """Create and register the in-process bridge."""
        self._runtime_manager.create_inprocess_bridge(
            inproc,
            on_stopped=on_stopped,
            on_thread=on_thread,
            on_exited=on_exited,
            on_output=on_output,
        )

    def create_inprocess_backend(self) -> None:
        """Create and register the in-process backend."""
        self._runtime_manager.create_inprocess_backend()

    def _handle_debug_message(self, message: str) -> None:
        """Handle a debug protocol message from the debuggee."""
        self._event_router.handle_debug_message(message)

    async def _handle_program_exit(self, exit_code: int) -> None:
        """Handle the debuggee program exit"""
        if self.program_running:
            self.program_running = False
            self.is_terminated = True

            await self.server.send_event("exited", {"exitCode": exit_code})
            await self.server.send_event("terminated")

    async def set_breakpoints(
        self,
        source: SourceDict | str,
        breakpoints: list[SourceBreakpoint],
    ) -> list[BreakpointResponse]:
        """Set breakpoints for a source file."""
        return await self._state_manager.set_breakpoints(source, breakpoints)

    def _process_breakpoints(
        self,
        breakpoints: Sequence[SourceBreakpoint],
    ) -> tuple[list[SourceBreakpoint], list[BreakpointDict]]:
        """Process breakpoints into spec and storage lists."""
        return self._breakpoint_facade.process_breakpoints(breakpoints)

    def _forward_breakpoint_events(self, storage_list: list[BreakpointDict]) -> None:
        """Forward breakpoint-changed events to clients."""
        self._breakpoint_facade.forward_breakpoint_events(storage_list)

    def set_break(
        self,
        filename: str,
        lineno: int,
        *,
        cond: str | None = None,
        **kwargs: Any,
    ) -> bool:
        """Compatibility helper for shared breakpoint handlers."""
        hit_condition = kwargs.get("hit_condition") or kwargs.get("hitCondition")
        if not isinstance(hit_condition, str):
            hit_condition = None
        log_message = kwargs.get("log_message") or kwargs.get("logMessage")
        if not isinstance(log_message, str):
            log_message = None

        self.breakpoint_manager.record_line_breakpoint(
            filename,
            int(lineno),
            condition=cond,
            hit_condition=hit_condition,
            log_message=log_message,
        )
        return True

    def clear_break(self, filename: str, lineno: int = 0) -> bool:
        """Compatibility helper to clear a single breakpoint by file/line."""
        if lineno <= 0:
            self.breakpoint_manager.clear_line_meta_for_file(filename)
            return True

        if self.breakpoint_manager.get_line_meta(filename, lineno) is None:
            return False

        self.breakpoint_manager.line_meta.pop((filename, int(lineno)), None)
        path_meta = self.breakpoint_manager._line_meta_by_path.get(filename)  # noqa: SLF001
        if path_meta:
            path_meta.pop(int(lineno), None)
            if not path_meta:
                self.breakpoint_manager._line_meta_by_path.pop(filename, None)  # noqa: SLF001
        return True

    def clear_breaks_for_file(self, path: str) -> None:
        """Compatibility helper to clear all breakpoints for a file."""
        self.breakpoint_manager.clear_line_meta_for_file(path)

    def clear_break_meta_for_file(self, path: str) -> None:
        """Compatibility helper to clear stored breakpoint metadata for a file."""
        self.breakpoint_manager.clear_line_meta_for_file(path)

    def record_breakpoint(
        self,
        path: str,
        line: int,
        *,
        condition: str | None,
        hit_condition: str | None,
        log_message: str | None,
    ) -> None:
        """Compatibility helper to store breakpoint metadata."""
        self.breakpoint_manager.record_line_breakpoint(
            path,
            line,
            condition=condition,
            hit_condition=hit_condition,
            log_message=log_message,
        )

    def clear_all_function_breakpoints(self) -> None:
        """Compatibility helper to clear function breakpoints and metadata."""
        self.breakpoint_manager.clear_function_breakpoints()

    async def set_function_breakpoints(
        self,
        breakpoints: list[FunctionBreakpoint],
    ) -> list[FunctionBreakpoint]:
        """Set breakpoints for functions."""
        return await self._breakpoint_facade.set_function_breakpoints(breakpoints)

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
        return await self._breakpoint_facade.set_exception_breakpoints(
            filters,
            filter_options,
            exception_options,
        )

    def make_variable_object(
        self,
        name: Any,
        value: Any,
        _frame: Any | None = None,
        *,
        max_string_length: int = 1000,
    ) -> Variable:
        """Create a DAP variable payload compatible with shared helpers."""
        try:
            value_str = repr(value)
        except Exception:
            value_str = "<Error getting value>"
        if len(value_str) > max_string_length:
            value_str = value_str[:max_string_length] + "..."

        var_ref = self.variable_manager.allocate_ref(value)

        presentation_hint: dict[str, Any] = {
            "kind": "data",
            "attributes": [],
            "visibility": "private" if str(name).startswith("_") else "public",
        }

        if self.data_bp_state.watch_names and str(name) in self.data_bp_state.watch_names:
            presentation_hint["attributes"].append("hasDataBreakpoint")

        return cast(
            "Variable",
            {
                "name": str(name),
                "value": value_str,
                "type": type(value).__name__,
                "variablesReference": var_ref,
                "presentationHint": presentation_hint,
            },
        )

    async def continue_execution(self, thread_id: int) -> ContinueResponseBody:
        """Continue execution of the specified thread"""
        return await self._execution_manager.continue_execution(thread_id)

    async def next(self, thread_id: int, *, granularity: str = "line") -> None:
        """Step over to the next line"""
        await self._execution_manager.next(thread_id, granularity=granularity)

    async def step_in(
        self,
        thread_id: int,
        target_id: int | None = None,
        *,
        granularity: str = "line",
    ) -> None:
        """Step into a function.

        Args:
            thread_id: The thread to step in.
            target_id: Optional target ID for stepping into a specific call target.
            granularity: DAP stepGranularity ("line", "statement", "instruction").

        """
        await self._execution_manager.step_in(thread_id, target_id, granularity=granularity)

    async def step_out(self, thread_id: int, *, granularity: str = "line") -> None:
        """Step out of the current function"""
        await self._execution_manager.step_out(thread_id, granularity=granularity)

    async def pause(self, thread_id: int) -> bool:
        """Pause execution of the specified thread"""
        return await self._execution_manager.pause(thread_id)

    async def get_threads(self) -> list[Thread]:
        """Get all threads"""
        return await self._execution_manager.get_threads()

    async def get_loaded_sources(self) -> list[Source]:
        """Get all loaded source files."""
        return self._source_introspection.get_loaded_sources()

    async def get_modules(self) -> list[Module]:
        """Get all loaded Python modules."""
        return self._source_introspection.get_modules()

    async def get_stack_trace(
        self,
        thread_id: int,
        start_frame: int = 0,
        levels: int = 0,
    ) -> StackTraceResponseBody:
        """Get stack trace for a thread."""
        return await self._state_manager.get_stack_trace(thread_id, start_frame, levels)

    async def get_scopes(self, frame_id: int) -> list[Scope]:
        """Get variable scopes for a stack frame."""
        return await self._state_manager.get_scopes(frame_id)

    async def get_variables(
        self,
        variables_reference: int,
        filter_type: str = "",
        start: int = 0,
        count: int = 0,
    ) -> list[Variable]:
        """Get variables for the given reference."""
        return await self._state_manager.get_variables(
            variables_reference,
            filter_type,
            start,
            count,
        )

    async def set_variable(
        self,
        var_ref: int,
        name: str,
        value: str,
    ) -> SetVariableResponseBody:
        """Set a variable value in the specified scope."""
        return await self._state_manager.set_variable(var_ref, name, value)

    async def evaluate(
        self,
        expression: str,
        frame_id: int | None = None,
        context: str | None = None,
    ) -> EvaluateResponseBody:
        """Evaluate an expression in a specific context."""
        return await self._state_manager.evaluate(expression, frame_id, context)

    async def completions(
        self,
        text: str,
        column: int,
        frame_id: int | None = None,
        line: int = 1,
    ) -> CompletionsResponseBody:
        """Get expression completions for the debug console.

        Provides intelligent auto-completions based on runtime frame context
        when stopped at a breakpoint. Falls back to static analysis when
        runtime introspection is not available.

        Args:
            text: The input text to complete (may be multi-line)
            column: Cursor position within the text (1-based, UTF-16 code units)
            frame_id: Stack frame for scope context (None = global scope)
            line: Line number within text (1-based, default 1)

        Returns:
            CompletionsResponseBody with list of completion targets

        """
        backend = self.get_active_backend()
        if backend is not None:
            result = await backend.completions(text, column, frame_id, line)
            return cast("CompletionsResponseBody", result)
        return {"targets": []}

    async def exception_info(self, thread_id: int) -> ExceptionInfoResponseBody:
        """Get exception information for a thread"""
        return await self._execution_manager.exception_info(thread_id)

    async def get_exception_info(self, thread_id: int) -> ExceptionInfoResponseBody:
        """Get exception information for a thread (convenience method)"""
        return await self.exception_info(thread_id)

    async def configuration_done_request(self) -> None:
        """Signal that configuration is done and debugging can start"""
        await self._execution_manager.configuration_done_request()

    async def disconnect(self, terminate_debuggee: bool = False) -> None:
        """Disconnect from the debuggee"""
        await self._execution_manager.disconnect(terminate_debuggee)

    async def terminate(self) -> None:
        """Terminate the debuggee"""
        await self._execution_manager.terminate()

    async def restart(self) -> None:
        """Request a session restart by signaling terminated(restart=true)."""
        await self._execution_manager.restart()

    async def hot_reload(
        self,
        path: str,
        options: HotReloadOptions | None = None,
    ) -> HotReloadResponseBody:
        """Reload a Python module in-place without restarting the session."""
        return await self._hot_reload_service.reload_module(path, options)

    async def evaluate_expression(
        self,
        expression: str,
        frame_id: int,
        context: str = "hover",
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
        await self._execution_manager.send_command_to_debuggee(command)

    async def shutdown(self) -> None:
        """Shut down the debugger and clean up resources."""
        # Cancel background tasks
        for task in list(self._bg_tasks):
            task.cancel()

        shutdown_error = RuntimeError("Debugger shutdown")
        self._session_facade.fail_pending_commands(shutdown_error)

        # Clear runtime state (breakpoints, threads, etc.)
        self.clear_runtime_state()

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

            self.ipc.cleanup()

        # Clear state
        self.clear_runtime_state()
        self.program_running = False
        self.is_terminated = True


__all__ = ["PyDebugger", "_acquire_event_loop"]
