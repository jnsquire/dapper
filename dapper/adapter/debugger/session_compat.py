from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import cast

if TYPE_CHECKING:
    import asyncio
    import subprocess

    from dapper.adapter.debugger.session import _PyDebuggerSessionFacade
    from dapper.adapter.external_backend import ExternalProcessBackend
    from dapper.adapter.inprocess_backend import InProcessBackend
    from dapper.adapter.source_tracker import LoadedSourceTracker
    from dapper.adapter.types import BreakpointDict
    from dapper.adapter.types import PyDebuggerThread
    from dapper.protocol.requests import FunctionBreakpoint


class _PyDebuggerSessionCompatMixin:
    """Compatibility surface for session-backed debugger state.

    This mixin keeps legacy attribute/property behavior while delegating all
    mutable runtime containers to `_PyDebuggerSessionFacade`.
    """

    _source_introspection: LoadedSourceTracker
    _session_facade: _PyDebuggerSessionFacade
    _inproc_backend: InProcessBackend | None
    _external_backend: ExternalProcessBackend | None
    process: subprocess.Popen | None
    is_terminated: bool

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

    @property
    def threads(self) -> dict[int, PyDebuggerThread]:
        """Compatibility wrapper around session facade thread map."""
        return cast("dict[int, PyDebuggerThread]", self._session_facade.threads)

    @threads.setter
    def threads(self, value: dict[int, PyDebuggerThread]) -> None:
        """Compatibility setter for tests that patch thread state directly."""
        self._session_facade.threads = cast("dict[int, Any]", value)

    @property
    def var_refs(self) -> dict[int, object]:
        """Compatibility wrapper around session facade variable references."""
        return self._session_facade.var_refs

    @var_refs.setter
    def var_refs(self, value: dict[int, object]) -> None:
        """Compatibility setter for tests that patch var refs directly."""
        self._session_facade.var_refs = value

    @property
    def breakpoints(self) -> dict[str, list[BreakpointDict]]:
        """Compatibility wrapper around session facade breakpoint storage."""
        return cast("dict[str, list[BreakpointDict]]", self._session_facade.breakpoints)

    @breakpoints.setter
    def breakpoints(self, value: dict[str, list[BreakpointDict]]) -> None:
        """Compatibility setter for tests that patch breakpoints directly."""
        self._session_facade.breakpoints = cast("dict[str, list[dict[str, Any]]]", value)

    @property
    def current_stack_frames(self) -> dict[int, list]:
        """Compatibility wrapper around session facade stack-frame cache."""
        return cast("dict[int, list]", self._session_facade.current_stack_frames)

    @current_stack_frames.setter
    def current_stack_frames(self, value: dict[int, list]) -> None:
        """Compatibility setter for tests that patch stack frames directly."""
        self._session_facade.current_stack_frames = cast("dict[int, list[Any]]", value)

    @property
    def function_breakpoints(self) -> list[FunctionBreakpoint]:
        """Compatibility wrapper around session facade function breakpoints."""
        return cast("list[FunctionBreakpoint]", self._session_facade.function_breakpoints)

    @function_breakpoints.setter
    def function_breakpoints(self, value: list[FunctionBreakpoint]) -> None:
        """Compatibility setter for tests that patch function breakpoints directly."""
        self._session_facade.function_breakpoints = cast("list[dict[str, Any]]", value)

    @property
    def thread_exit_events(self) -> dict[int, object]:
        """Compatibility wrapper around session facade thread-exit bookkeeping."""
        return self._session_facade.thread_exit_events

    @thread_exit_events.setter
    def thread_exit_events(self, value: dict[int, object]) -> None:
        """Compatibility setter for tests that patch thread exit events directly."""
        self._session_facade.thread_exit_events = value

    @property
    def _data_watches(self) -> dict[str, dict[str, Any]]:
        """Compatibility wrapper around session facade data-watch metadata."""
        return self._session_facade.data_watches

    @_data_watches.setter
    def _data_watches(self, value: dict[str, dict[str, Any]]) -> None:
        """Compatibility setter for tests that patch data watches directly."""
        self._session_facade.data_watches = value

    @property
    def _frame_watches(self) -> dict[int, list[str]]:
        """Compatibility wrapper around session facade frame-watch index."""
        return self._session_facade.frame_watches

    @_frame_watches.setter
    def _frame_watches(self, value: dict[int, list[str]]) -> None:
        """Compatibility setter for tests that patch frame watches directly."""
        self._session_facade.frame_watches = value

    @property
    def _pending_commands(self) -> dict[int, asyncio.Future[dict[str, Any]]]:
        """Compatibility wrapper around session facade pending-commands map."""
        return self._session_facade.pending_commands

    @_pending_commands.setter
    def _pending_commands(self, value: dict[int, asyncio.Future[dict[str, Any]]]) -> None:
        """Compatibility setter for tests that patch pending-command map directly."""
        self._session_facade.pending_commands = value

    @property
    def _next_command_id(self) -> int:
        """Compatibility wrapper around session facade command-id counter."""
        return self._session_facade.next_command_id

    @_next_command_id.setter
    def _next_command_id(self, value: int) -> None:
        """Compatibility setter for tests that patch command-id counter."""
        self._session_facade.next_command_id = value

    def _get_next_command_id(self) -> int:
        """Get the next command ID and increment the counter."""
        return self._session_facade.allocate_command_id()

    def get_thread(self, thread_id: int) -> PyDebuggerThread | None:
        """Get thread state by id from session facade."""
        return cast("PyDebuggerThread | None", self._session_facade.get_thread(thread_id))

    def set_thread(self, thread_id: int, thread: PyDebuggerThread) -> None:
        """Store thread state in session facade."""
        self._session_facade.set_thread(thread_id, thread)

    def remove_thread(self, thread_id: int) -> None:
        """Remove thread state from session facade."""
        self._session_facade.remove_thread(thread_id)

    def iter_threads(self) -> list[tuple[int, PyDebuggerThread]]:
        """Return a snapshot of thread-id/thread pairs from session facade."""
        return cast("list[tuple[int, PyDebuggerThread]]", self._session_facade.iter_threads())

    def cache_stack_frames(self, thread_id: int, frames: list[Any]) -> None:
        """Cache stack frames for a thread in session facade."""
        self._session_facade.cache_stack_frames(thread_id, frames)

    def get_cached_stack_frames(self, thread_id: int) -> list[Any] | None:
        """Get cached stack frames for a thread from session facade."""
        return self._session_facade.get_cached_stack_frames(thread_id)

    def cache_var_ref(self, var_ref: int, value: object) -> None:
        """Cache a variable reference payload in session facade."""
        self._session_facade.cache_var_ref(var_ref, value)

    def get_var_ref(self, var_ref: int) -> object | None:
        """Get variable reference payload from session facade."""
        return self._session_facade.get_var_ref(var_ref)

    def has_var_ref(self, var_ref: int) -> bool:
        """Return whether a variable reference exists in session facade."""
        return self._session_facade.has_var_ref(var_ref)

    def set_breakpoints_for_path(self, path: str, breakpoints: list[BreakpointDict]) -> None:
        """Store source breakpoints for a path in session facade."""
        self._session_facade.set_breakpoints_for_path(
            path, cast("list[dict[str, Any]]", breakpoints)
        )

    def clear_data_watch_containers(self) -> None:
        """Clear data-watch bookkeeping containers in session facade."""
        self._session_facade.clear_data_watch_containers()

    def set_data_watch(self, data_id: str, meta: dict[str, Any]) -> None:
        """Store data-watch metadata by dataId in session facade."""
        self._session_facade.set_data_watch(data_id, meta)

    def add_frame_watch(self, frame_id: int, data_id: str) -> None:
        """Index a dataId under a frame id in session facade."""
        self._session_facade.add_frame_watch(frame_id, data_id)

    def clear_runtime_state(self) -> None:
        """Clear mutable runtime session containers in session facade."""
        self._session_facade.clear_runtime_state()

    def _get_process_state(self) -> tuple[subprocess.Popen | None, bool]:
        """Get the current process state for the external backend."""
        return self.process, self.is_terminated
