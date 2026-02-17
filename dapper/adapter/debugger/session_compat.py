from __future__ import annotations

from collections.abc import MutableMapping
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
    from dapper.core.breakpoint_manager import BreakpointManager
    from dapper.core.variable_manager import VariableManager
    from dapper.protocol.requests import FunctionBreakpoint


class _VarRefProxy(MutableMapping):
    def __init__(self, variable_manager: Any) -> None:
        self._variable_manager = variable_manager

    def __getitem__(self, key: int) -> Any:
        value = self._variable_manager.var_refs[key]
        if isinstance(value, tuple) and len(value) == 2 and value[0] == "object":  # noqa: PLR2004
            return value[1]
        return value

    def __setitem__(self, key: int, value: Any) -> None:
        self._variable_manager.var_refs[key] = ("object", value)

    def __delitem__(self, key: int) -> None:
        del self._variable_manager.var_refs[key]

    def __iter__(self):
        return iter(self._variable_manager.var_refs)

    def __len__(self) -> int:
        return len(self._variable_manager.var_refs)

    def __contains__(self, key: object) -> bool:
        return key in self._variable_manager.var_refs


class _PyDebuggerSessionCompatMixin:
    """Compatibility surface for session-backed debugger state.

    This mixin keeps legacy attribute/property behavior while delegating all
    mutable runtime containers to `_PyDebuggerSessionFacade`.
    """

    variable_manager: VariableManager
    breakpoint_manager: BreakpointManager
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
    def var_refs(self) -> MutableMapping[int, Any]:
        """Compatibility wrapper around session facade variable references.

        Note: VariableManager stores (type, value) tuples, while legacy SessionFacade
        stored just the value. This property attempts to return the underlying value
        when possible to satisfy legacy tests.
        """
        return _VarRefProxy(self.variable_manager)

    @var_refs.setter
    def var_refs(self, value: dict[int, object]) -> None:
        """Compatibility setter for tests that patch var refs directly.

        Note: Takes raw objects and wraps them in ("object", value) tuples
        for VariableManager storage.
        """
        # Convert raw objects to VariableManager internal format
        new_refs = {}
        for ref_id, obj in value.items():
            new_refs[ref_id] = ("object", obj)
        self.variable_manager.var_refs = new_refs

    @property
    def breakpoints(self) -> dict[str, list[BreakpointDict]]:
        """Compatibility wrapper around session facade breakpoint storage."""
        result: dict[str, list[BreakpointDict]] = {}
        # Access internal structure directly as this is a compat mixin
        # intended to bridge legacy state access patterns.
        # pylint: disable=protected-access
        for path, lines_meta in self.breakpoint_manager._line_meta_by_path.items():  # noqa: SLF001
            result[path] = []
            for line, meta in lines_meta.items():
                # Construct BreakpointDict from internal metadata
                bp_dict = {"line": int(line), **meta}  # Ensure line is int
                result[path].append(cast("BreakpointDict", bp_dict))
        return result

    @breakpoints.setter
    def breakpoints(self, value: dict[str, list[BreakpointDict]]) -> None:
        """Compatibility setter for tests that patch breakpoints directly."""
        # Clear all existing line breakpoints first.
        # We iterate over a copy of keys because clear_line_meta_for_file modifies the dictionary.
        for path in list(self.breakpoint_manager._line_meta_by_path.keys()):  # noqa: SLF001
            self.breakpoint_manager.clear_line_meta_for_file(path)

        for path, bps in value.items():
            for bp in bps:
                # Map BreakpointDict fields to internal API arguments
                # Note: 'line' is required in BreakpointDict for storage
                line = bp.get("line")
                if line is not None:
                    # Extract known fields
                    condition = bp.get("condition")
                    hit_condition = bp.get("hitCondition")
                    log_message = bp.get("logMessage")

                    # Pass all other fields as kwargs to preserve metadata like 'verified', 'id', etc.
                    extra_meta = {
                        k: v
                        for k, v in bp.items()
                        if k not in ("line", "condition", "hitCondition", "logMessage")
                    }

                    self.breakpoint_manager.record_line_breakpoint(
                        path,
                        int(line),
                        condition=condition,
                        hit_condition=hit_condition,
                        log_message=log_message,
                        **extra_meta,
                    )

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
        result: list[FunctionBreakpoint] = []
        for name in self.breakpoint_manager.function_names:
            meta = self.breakpoint_manager.get_function_meta(name)
            # Construct FunctionBreakpoint from name and meta
            fbp = {"name": name, **meta}
            result.append(cast("FunctionBreakpoint", fbp))
        return result

    @function_breakpoints.setter
    def function_breakpoints(self, value: list[FunctionBreakpoint]) -> None:
        """Compatibility setter for tests that patch function breakpoints directly."""
        self.breakpoint_manager.clear_function_breakpoints()

        names: list[str] = []
        metas: dict[str, dict[str, Any]] = {}

        for fbp in value:
            name = fbp.get("name")
            if name:
                names.append(name)
                # Extract meta fields: all excluding 'name'
                meta = {k: v for k, v in fbp.items() if k != "name"}
                metas[name] = meta

        self.breakpoint_manager.set_function_breakpoints(names, metas)

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
        """Cache a variable reference payload in session facade.

        Wraps the value in ("object", value) tuple to match VariableManager format.
        """
        self.variable_manager.var_refs[var_ref] = ("object", value)

    def get_var_ref(self, var_ref: int) -> object | None:
        """Get variable reference payload from session facade.

        Unwraps ("object", value) tuple from VariableManager.
        """
        ref_data = self.variable_manager.var_refs.get(var_ref)
        if isinstance(ref_data, tuple) and len(ref_data) == 2 and ref_data[0] == "object":  # noqa: PLR2004
            return ref_data[1]
        return ref_data

    def has_var_ref(self, var_ref: int) -> bool:
        """Return whether a variable reference exists in session facade."""
        return var_ref in self.variable_manager.var_refs

    def set_breakpoints_for_path(self, path: str, breakpoints: list[BreakpointDict]) -> None:
        """Store source breakpoints for a path in session facade."""
        self.breakpoint_manager.clear_line_meta_for_file(path)
        for bp in breakpoints:
            line = bp.get("line")
            if line is None:
                continue

            # Extract known fields
            condition = bp.get("condition")
            hit_condition = bp.get("hitCondition")
            log_message = bp.get("logMessage")

            # Pass all other fields as kwargs to preserve metadata like 'verified', 'id', etc.
            extra_meta = {
                k: v
                for k, v in bp.items()
                if k not in ("line", "condition", "hitCondition", "logMessage")
            }

            self.breakpoint_manager.record_line_breakpoint(
                path,
                int(line),
                condition=condition,
                hit_condition=hit_condition,
                log_message=log_message,
                **extra_meta,
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
        """Clear mutable runtime session containers in session facade.

        Clears both legacy session facade state and core managers.
        """
        self._session_facade.clear_runtime_state()
        if hasattr(self, "variable_manager"):
            self.variable_manager.var_refs.clear()
            self.variable_manager.next_var_ref = self.variable_manager.DEFAULT_START_REF
        if hasattr(self, "breakpoint_manager"):
            self.breakpoint_manager.line_meta.clear()
            self.breakpoint_manager._line_meta_by_path.clear()  # noqa: SLF001
            self.breakpoint_manager.function_names.clear()
            self.breakpoint_manager.function_meta.clear()
            self.breakpoint_manager.custom.clear()

    def _get_process_state(self) -> tuple[subprocess.Popen | None, bool]:
        """Get the current process state for the external backend."""
        return self.process, self.is_terminated
