from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import Callable

from dapper.core.breakpoint_manager import BreakpointManager
from dapper.core.data_breakpoint_state import DataBreakpointState
from dapper.core.exception_handler import ExceptionHandler
from dapper.core.stepping_controller import SteppingController
from dapper.core.thread_tracker import ThreadTracker
from dapper.core.variable_manager import VariableManager
from dapper.shared import debug_shared

if TYPE_CHECKING:
    from dapper.protocol.debugger_protocol import Variable


class _BreaksCollection:
    """A small container that behaves like both a list of (file,line,meta)
    and a dict mapping filename -> list[(line, meta)]. Tests in the repo use
    both styles, so this adapter keeps compatibility.
    """

    def __init__(self) -> None:
        self._by_file: dict[str, list[tuple[int, Any]]] = {}

    def add(self, filename: str, lineno: int, meta: Any | None = None) -> None:
        arr = self._by_file.get(filename)
        if arr is None:
            self._by_file[filename] = [(int(lineno), meta)]
        else:
            arr.append((int(lineno), meta))

    # list-like behaviors
    def __iter__(self):
        for fn, arr in self._by_file.items():
            for ln, meta in arr:
                yield (fn, ln, meta)

    def __contains__(self, item: object) -> bool:
        # allow checks like ("file.py", 10, None) in breaks
        if not isinstance(item, tuple) or len(item) != 3:
            return False
        fn, ln, meta = item
        arr = self._by_file.get(fn)
        if not arr:
            return False
        return any(ln == e[0] and meta == e[1] for e in arr)

    # dict-like access by filename
    def __getitem__(self, filename: str) -> list[tuple[int, Any | None]]:
        return list(self._by_file.get(filename, []))

    def pop(self, filename: str, default: list[tuple[int, Any]] | None = None):
        return self._by_file.pop(filename, default)

    def get(self, filename: str, default: list[tuple[int, Any]] | None = None):
        return self._by_file.get(filename, default)

    def items(self):
        return self._by_file.items()

    def clear(self):
        self._by_file.clear()


class DummyDebugger:
    """Unified dummy debugger used by tests.

    This class combines the behaviors seen across several test-local
    DummyDebugger copies in the codebase. It intentionally keeps a thin
    surface: bookkeeping for breaks, frames/vars, and a small set of
    control methods consumed by handlers.
    """

    def __init__(self) -> None:
        # --- Delegate objects (ground truth for state) ---
        self.stepping_controller = SteppingController()
        self.exception_handler = ExceptionHandler()
        self.var_manager = VariableManager(start_ref=1)
        self.thread_tracker = ThreadTracker()
        self.data_bp_state = DataBreakpointState()
        self.bp_manager = BreakpointManager()

        # optional data breakpoint storage
        self.data_breakpoints: list[dict[str, Any]] | None = []

        # breakpoint bookkeeping
        self.breakpoint_meta: dict[tuple[str, int], dict[str, Any]] = {}

        # misc
        self.cleared: list[Any] = []
        self.recorded: list[tuple[str, int, dict[str, Any]]] = []

        # provide breaks as a compat container used by tests
        self.breaks = _BreaksCollection()
        # some tests expect a program_path attribute
        self.program_path: Any | None = None
        # stack trace (DebuggerLike protocol — None means "use thread_tracker")
        self.stack: list[Any] | None = None

        # debugging frames sometimes referenced directly
        self.botframe: Any | None = None

        # Frame evaluation attributes (DebuggerLike protocol)
        self.breakpoints: dict[str, list[Any]] = {}
        self._frame_eval_enabled: bool = False
        self._mock_user_line: Any = None
        self._trace_func: Callable[[Any, str | None, Any], Any] | None = None

        # compatibility flags used by some tests
        self._continued: bool = False
        self._next: Any | None = None
        self._step: bool = False
        self._return: Any | None = None

    # --- Convenience properties for backward-compat with test code ---

    @property
    def stepping(self) -> bool:
        return self.stepping_controller.stepping

    @stepping.setter
    def stepping(self, value: bool) -> None:
        self.stepping_controller.stepping = value

    @property
    def stop_on_entry(self) -> bool:
        return self.stepping_controller.stop_on_entry

    @stop_on_entry.setter
    def stop_on_entry(self, value: bool) -> None:
        self.stepping_controller.stop_on_entry = value

    @property
    def current_frame(self) -> Any:
        return self.stepping_controller.current_frame

    @current_frame.setter
    def current_frame(self, value: Any) -> None:
        self.stepping_controller.current_frame = value

    @property
    def next_var_ref(self) -> int:
        return self.var_manager.next_var_ref

    @next_var_ref.setter
    def next_var_ref(self, value: int) -> None:
        self.var_manager.next_var_ref = value

    @property
    def var_refs(self) -> dict:
        return self.var_manager.var_refs

    @var_refs.setter
    def var_refs(self, value: dict) -> None:
        self.var_manager.var_refs = value

    @property
    def frame_id_to_frame(self) -> dict:
        return self.thread_tracker.frame_id_to_frame

    @frame_id_to_frame.setter
    def frame_id_to_frame(self, value: dict) -> None:
        self.thread_tracker.frame_id_to_frame = value

    @property
    def frames_by_thread(self) -> dict:
        return self.thread_tracker.frames_by_thread

    @frames_by_thread.setter
    def frames_by_thread(self, value: dict) -> None:
        self.thread_tracker.frames_by_thread = value

    @property
    def threads(self) -> dict:
        return self.thread_tracker.threads

    @threads.setter
    def threads(self, value: dict) -> None:
        self.thread_tracker.threads = value

    @property
    def current_exception_info(self) -> dict:
        return self.exception_handler.exception_info_by_thread

    @current_exception_info.setter
    def current_exception_info(self, value: dict) -> None:
        self.exception_handler.exception_info_by_thread = value

    @property
    def exception_breakpoints_raised(self) -> bool:
        return self.exception_handler.config.break_on_raised

    @exception_breakpoints_raised.setter
    def exception_breakpoints_raised(self, value: bool) -> None:
        self.exception_handler.config.break_on_raised = value

    @property
    def exception_breakpoints_uncaught(self) -> bool:
        return self.exception_handler.config.break_on_uncaught

    @exception_breakpoints_uncaught.setter
    def exception_breakpoints_uncaught(self, value: bool) -> None:
        self.exception_handler.config.break_on_uncaught = value

    @property
    def stopped_thread_ids(self) -> set:
        return self.thread_tracker.stopped_thread_ids

    @stopped_thread_ids.setter
    def stopped_thread_ids(self, value: set) -> None:
        self.thread_tracker.stopped_thread_ids = value

    @property
    def data_watch_names(self) -> set | list | None:
        return self.data_bp_state.watch_names or None

    @data_watch_names.setter
    def data_watch_names(self, value: set | list | None) -> None:
        if value is None:
            self.data_bp_state.watch_names = set()
        elif isinstance(value, set):
            self.data_bp_state.watch_names = value
        else:
            self.data_bp_state.watch_names = set(value)

    @property
    def data_watch_meta(self) -> dict | None:
        return self.data_bp_state.watch_meta or None

    @data_watch_meta.setter
    def data_watch_meta(self, value: dict | None) -> None:
        if value is None:
            self.data_bp_state.watch_meta = {}
        else:
            self.data_bp_state.watch_meta = value

    @property
    def _data_watches(self) -> dict | None:
        return self.data_bp_state.data_watches

    @_data_watches.setter
    def _data_watches(self, value: dict | None) -> None:
        if value is None:
            self.data_bp_state.data_watches = {}
        else:
            self.data_bp_state.data_watches = value

    @property
    def _frame_watches(self) -> dict | None:
        return self.data_bp_state.frame_watches

    @_frame_watches.setter
    def _frame_watches(self, value: dict | None) -> None:
        if value is None:
            self.data_bp_state.frame_watches = {}
        else:
            self.data_bp_state.frame_watches = value

    @property
    def function_breakpoints(self) -> list:
        return self.bp_manager.function_names

    @function_breakpoints.setter
    def function_breakpoints(self, value: list) -> None:
        self.bp_manager.function_names = value

    @property
    def function_breakpoint_meta(self) -> dict:
        return self.bp_manager.function_meta

    @function_breakpoint_meta.setter
    def function_breakpoint_meta(self, value: dict) -> None:
        self.bp_manager.function_meta = value

    def set_break(
        self,
        filename: str,
        lineno: int,
        temporary: bool = False,
        cond: Any | None = None,
        funcname: str | None = None,
    ) -> Any | None:
        _ = temporary, funcname
        self.breaks.add(filename, int(lineno), cond)
        # Return True to indicate the breakpoint was successfully set.
        return True

    def record_breakpoint(
        self,
        path: str,
        line: int,
        *,
        condition: Any | None = None,
        hit_condition: Any | None = None,
        log_message: Any | None = None,
    ) -> None:
        meta = {"condition": condition, "hit_condition": hit_condition, "log_message": log_message}
        # keep both a meta map and the breaks collection for compatibility
        self.breakpoint_meta[(path, int(line))] = meta
        self.recorded.append((path, int(line), meta))
        self.breaks.add(path, int(line), meta)

    def clear_breaks_for_file(self, path: str) -> None:
        self.cleared.append(path)
        try:
            entries = list(self.breaks.get(path, []))
        except Exception:
            entries = []

        for entry in entries:
            line: int | None = None
            if isinstance(entry, tuple) and entry:
                try:
                    line = int(entry[0])
                except Exception:
                    line = None
            else:
                try:
                    line = int(entry)
                except Exception:
                    line = None

            if line is None:
                continue

            try:
                self.clear_break(path, line)
            except Exception:
                pass

        try:
            self.clear_break_meta_for_file(path)
        except Exception:
            pass

    def clear_break(self, filename: str, lineno: int) -> Any | None:
        # remove a specific breakpoint if present
        arr = self.breaks.get(filename)
        if arr:
            # reconstruct file entries without the lineno
            self.breaks._by_file[filename] = [b for b in arr if b[0] != int(lineno)]
        return None

    def clear_break_meta_for_file(self, path: str) -> None:
        to_del = [k for k in list(self.breakpoint_meta.keys()) if k[0] == path]
        for k in to_del:
            self.breakpoint_meta.pop(k, None)

    def clear_all_function_breakpoints(self) -> None:
        self.bp_manager.clear_function_breakpoints()

    def set_continue(self) -> None:
        # Historic tests expect an attribute to be set when continue is
        # requested.
        self._continued = True

    def set_next(self, frame: Any) -> None:
        self._next = frame

    def set_step(self) -> None:
        self._step = True
        self.stepping = True

    def set_return(self, frame: Any) -> None:
        self._return = frame

    def run(self, cmd: Any, *args: Any, **kwargs: Any) -> Any:
        _ = cmd, args, kwargs
        return None

    def make_variable_object(
        self, name: Any, value: Any, frame: Any | None = None, *, max_string_length: int = 1000
    ) -> Variable:
        # Use the internal implementation to avoid recursion: calling the
        # public debug_shared.make_variable_object would call back into
        # this method. _make_variable_object_impl is the safe internal
        # builder that accepts a debugger object for var-ref allocation.
        return debug_shared._make_variable_object_impl(
            name, value, self, frame, max_string_length=max_string_length
        )

    def create_variable_object(
        self, name: Any, value: Any, frame: Any | None = None, *, max_string_length: int = 1000
    ) -> Variable:
        # Backwards-compatible alias used by some callers/tests
        return self.make_variable_object(name, value, frame, max_string_length=max_string_length)

    # DebuggerLike protocol: frame evaluation methods

    def set_breakpoints(
        self, source: str, breakpoints: list[dict[str, Any]], **kwargs: Any
    ) -> None:
        """Set breakpoints for the given source file."""
        _ = kwargs
        self.breakpoints[source] = breakpoints

    def user_line(self, frame: Any) -> Any | None:
        """Called when execution stops at a line."""
        _ = frame
        return None

    def set_trace(self, frame: Any = None) -> None:
        """Start tracing from the given frame."""
        _ = frame

    def get_trace_function(
        self,
    ) -> Callable[[Any | None, str | None, Any | None], Any | None] | None:
        """Get the current trace function."""
        return self._trace_func

    def set_trace_function(
        self, trace_func: Callable[[Any | None, str | None, Any | None], Any | None] | None
    ) -> None:
        """Set a new trace function."""
        self._trace_func = trace_func
