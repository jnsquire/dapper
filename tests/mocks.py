from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Protocol

from dapper.core.breakpoint_manager import BreakpointManager
from dapper.core.data_breakpoint_state import DataBreakpointState
from dapper.core.exception_handler import ExceptionHandler
from dapper.core.stepping_controller import SteppingController
from dapper.core.thread_tracker import ThreadTracker
from dapper.core.variable_manager import VariableManager
from dapper.ipc.connections.base import ConnectionBase

if TYPE_CHECKING:
    from types import FrameType


# Expose names for import convenience in tests
__all__ = [
    "CodeLike",
    "FakeBreakpointDebugger",
    "FakeDataBreakpointDebugger",
    "FakeDebugger",
    "FrameLike",
    "MockCode",
    "MockConnection",
    "MockFrame",
    "make_real_frame",
]

# Keep generators alive so make_real_frame's paused generators keep their frames live
_kept_generators: list = []


class CodeLike(Protocol):
    co_filename: str
    co_firstlineno: int


class FrameLike(Protocol):
    f_code: CodeLike
    f_lineno: int
    # Use a non-recursive type for f_back to avoid recursive invariance issues
    f_back: object | None
    f_locals: dict[str, object] | None
    f_globals: dict[str, object] | None


@dataclass
class MockCode:
    co_filename: str
    co_firstlineno: int


@dataclass
class MockFrame:
    f_code: MockCode
    f_lineno: int
    # use object | None to avoid recursive/invariance typing issues
    f_back: object | None = None
    f_locals: dict[str, object] | None = None
    f_globals: dict[str, object] | None = None


# ---------------------------------------------------------------------------
# Mixin classes — each covers one debugger concern
# ---------------------------------------------------------------------------


class _SteppingMixin:
    """Provides stepping / execution-control state and trace helpers."""

    def __init__(self) -> None:
        self.stepping_controller = SteppingController()
        self._frame_eval_enabled = False
        self._mock_user_line = None
        self.process = None

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
    def current_frame(self) -> FrameType | None:
        """Test shim: current execution frame (optional)."""
        return self.stepping_controller.current_frame

    @current_frame.setter
    def current_frame(self, value: FrameType | None) -> None:
        self.stepping_controller.current_frame = value

    # --- Execution controls ---

    def set_continue(self) -> None:
        self.stepping = False

    def set_next(self, _frame: object) -> None:
        self.stepping = True

    def set_step(self) -> None:
        self.stepping = True

    def set_return(self, _frame: object) -> None:
        self.stepping = True

    # --- Misc / runner ---

    def run(self, _cmd: object, *_args: object, **_kwargs: object) -> object:
        return None

    def user_line(self, _frame: object) -> object | None:
        return None

    def set_trace(self, frame: object | None = None) -> None:
        pass

    def get_trace_function(self) -> object:
        return None

    def set_trace_function(self, trace_func: object) -> None:
        pass


class _VariableMixin:
    """Provides variable-inspection state."""

    def __init__(self) -> None:
        self.var_manager = VariableManager()

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

    def make_variable_object(
        self,
        name: object,
        value: object,
        _frame: object | None = None,
        *,
        max_string_length: int = 1000,
    ) -> dict:
        s = repr(value)
        if len(s) > max_string_length:
            s = s[: max_string_length - 3] + "..."
        return {
            "name": str(name),
            "value": s,
            "type": type(value).__name__,
            "variablesReference": 0,
        }


class _ThreadMixin:
    """Provides thread / frame-tracking state."""

    def __init__(self) -> None:
        self.thread_tracker = ThreadTracker()

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
    def stopped_thread_ids(self) -> set:
        return self.thread_tracker.stopped_thread_ids

    @stopped_thread_ids.setter
    def stopped_thread_ids(self, value: set) -> None:
        self.thread_tracker.stopped_thread_ids = value


class _ExceptionMixin:
    """Provides exception-filter state."""

    def __init__(self) -> None:
        self.exception_handler = ExceptionHandler()

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


class _BreakpointMixin:
    """Provides line / function-breakpoint state and API."""

    def __init__(self) -> None:
        self.bp_manager = BreakpointManager()
        self.breakpoints: dict[str, list[dict[str, object]]] = {}

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
        _temporary: bool = False,
        cond: object | None = None,
        _funcname: str | None = None,
    ) -> object | None:
        self.breakpoints.setdefault(filename, []).append({"line": int(lineno), "cond": cond})
        return True

    def record_breakpoint(
        self,
        path: str,
        line: int,
        *,
        condition: object | None,
        hit_condition: object | None,
        log_message: object | None,
    ) -> None:
        self.bp_manager.record_line_breakpoint(
            path,
            line,
            condition=condition,
            hit_condition=hit_condition,
            log_message=log_message,
        )

    def clear_breaks_for_file(self, path: str) -> None:
        entries = list(self.breakpoints.get(path, []))
        for entry in entries:
            line_value = entry.get("line") if isinstance(entry, dict) else None
            if line_value is None:
                continue
            try:
                line = int(line_value)
            except Exception:
                continue
            self.clear_break(path, line)
        self.clear_break_meta_for_file(path)

    def clear_break(self, filename: str, lineno: int) -> object | None:
        if filename in self.breakpoints:
            self.breakpoints[filename] = [
                b for b in self.breakpoints[filename] if b.get("line") != int(lineno)
            ]
        return None

    def clear_break_meta_for_file(self, path: str) -> None:
        self.bp_manager.clear_line_meta_for_file(path)

    def clear_all_function_breakpoints(self) -> None:
        self.bp_manager.clear_function_breakpoints()

    def set_breakpoints(
        self, source: str, breakpoints: list[dict[str, object]], **_kwargs: object
    ) -> None:
        self.breakpoints[source] = breakpoints  # pyright: ignore[reportArgumentType]


class _DataBreakpointMixin:
    """Provides data-breakpoint state and helpers."""

    def __init__(self) -> None:
        self.data_bp_state = DataBreakpointState()
        self.data_breakpoints: list[dict[str, object]] | None = None
        self.set_calls: list[tuple[str, str]] = []
        self.register_calls: list[tuple[list[str], list[tuple[str, dict]]]] = []
        self.raise_on_set: bool = False

    @property
    def _data_watches(self) -> dict:
        return self.data_bp_state.data_watches

    @_data_watches.setter
    def _data_watches(self, value: dict) -> None:
        self.data_bp_state.data_watches = value

    @property
    def _frame_watches(self) -> dict:
        return self.data_bp_state.frame_watches

    @_frame_watches.setter
    def _frame_watches(self, value: dict) -> None:
        self.data_bp_state.frame_watches = value

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

    def set_data_breakpoint(self, data_id: str, access_type: str = "write") -> None:
        self.set_calls.append((data_id, access_type))
        if getattr(self, "raise_on_set", False):
            raise RuntimeError("failed")
        self.data_bp_state.data_watches[data_id] = {"accessType": access_type}

    def register_data_watches(
        self, names: list[str], metas: list[tuple[str, dict]] | None = None
    ) -> None:
        self.register_calls.append((list(names), list(metas or [])))
        self.data_bp_state.register_watches(names, metas)

    def clear_all_data_breakpoints(self) -> None:
        self.data_bp_state.data_watches.clear()
        self.data_bp_state.frame_watches.clear()


# ---------------------------------------------------------------------------
# Reusable mock connection for server tests
class MockConnection(ConnectionBase):
    """Simple mock connection implementing the minimal ConnectionBase API
    used by tests. Stores incoming messages (queue) and written messages
    for assertions.
    """

    def __init__(self, _raise_on_set: bool = False):
        self.messages: list[dict] = []
        self._is_connected: bool = True
        self.closed = False
        self.written_messages: list[dict] = []

    async def accept(self):
        self._is_connected = True

    async def close(self):
        self._is_connected = False
        self.closed = True

    async def read_message(self):
        if not self.messages:
            return None
        return self.messages.pop(0)

    async def write_message(self, message):
        self.written_messages.append(message)

    def add_request(self, command, arguments=None, seq=1):
        req = {"seq": seq, "type": "request", "command": command}
        if arguments:
            req["arguments"] = arguments
        self.messages.append(req)


# ---------------------------------------------------------------------------
# Composed fakes
# ---------------------------------------------------------------------------


class FakeDebugger(
    _SteppingMixin,
    _VariableMixin,
    _ThreadMixin,
    _ExceptionMixin,
    _BreakpointMixin,
    _DataBreakpointMixin,
):
    """Lightweight fake debugger implementing the DebuggerLike protocol surface
    used by many unit tests.  Composes all six concern mixins so every part of
    the protocol is available.

    For new tests that exercise only one subsystem, prefer the focused fakes
    ``FakeBreakpointDebugger`` or ``FakeDataBreakpointDebugger`` so that
    changes to an unrelated mixin cannot cascade into those tests.
    """

    def __init__(self, raise_on_set: bool = False) -> None:
        _SteppingMixin.__init__(self)
        _VariableMixin.__init__(self)
        _ThreadMixin.__init__(self)
        _ExceptionMixin.__init__(self)
        _BreakpointMixin.__init__(self)
        _DataBreakpointMixin.__init__(self)
        # `raise_on_set` overrides the default set in _DataBreakpointMixin
        self.raise_on_set = raise_on_set


class FakeBreakpointDebugger(_SteppingMixin, _BreakpointMixin):
    """Focused fake for tests that only exercise line / function breakpoints
    and execution control.  Excludes variable, thread, exception, and
    data-breakpoint state so changes to those mixins cannot affect these tests.
    """

    def __init__(self) -> None:
        _SteppingMixin.__init__(self)
        _BreakpointMixin.__init__(self)


class FakeDataBreakpointDebugger(_SteppingMixin, _DataBreakpointMixin):
    """Focused fake for tests that only exercise data breakpoints.  Includes
    ``_SteppingMixin`` to expose ``current_frame`` (needed when frame locals
    are inspected), but omits thread, variable, exception, and line-breakpoint
    state.
    """

    def __init__(self, raise_on_set: bool = False) -> None:
        _SteppingMixin.__init__(self)
        _DataBreakpointMixin.__init__(self)
        self.raise_on_set = raise_on_set


def make_real_frame(
    locals_map: dict[str, object] | None = None,
    filename: str | None = None,
    lineno: int | None = None,
    func_name: str | None = None,
    globals_map: dict[str, object] | None = None,
) -> FrameType:
    """Create a real Python frame containing the given local variables.

    This constructs a tiny generator function that binds the provided
    locals and yields once. The generator is advanced so it's paused at the
    yield and its frame (gen.gi_frame) contains the locals for inspection
    and remains alive while we keep a reference to the generator.
    """
    locals_map = locals_map or {}
    # allow tests to request a specific filename/lineno for the frame
    if filename is None:
        filename = "<string>"
    fname = func_name or "__frame__"
    lines = [f"def {fname}():"]
    # place some blank lines so the yield appears at the requested lineno
    if lineno is not None and lineno > 1:
        # we want the code's yield line to have the requested lineno.
        # The function header counts as one line, and each local assignment
        # we add will consume one line as well; compute how many blanks we
        # must insert so the final `yield` lands on `lineno`.
        # We write locals as a single physical line if present, so treat
        # the locals region as occupying 1 line (or 0 if no locals).
        num_loc_lines = 1 if locals_map else 0
        blanks = lineno - num_loc_lines - 2
        blanks = max(blanks, 0)
        if blanks:
            lines.extend([""] * blanks)
    # Write locals in a single physical line so the yield can be positioned
    # at the requested lineno regardless of the number of locals.
    if locals_map:
        assigns = "; ".join(f"{k} = {v!r}" for k, v in locals_map.items())
        lines.append(f"    {assigns}")
    lines.append("    yield locals()")
    src = "\n".join(lines)
    ns: dict = {}
    # compile with a custom filename so the returned frame's f_code.co_filename
    # matches what tests expect
    code_obj = compile(src, filename, "exec")
    exec(code_obj, {"__builtins__": __builtins__}, ns)
    gen = ns[fname]()
    next(gen)
    _kept_generators.append(gen)
    # optionally update globals mapping on the paused frame
    if globals_map:
        frame = gen.gi_frame
        frame.f_globals.clear()
        frame.f_globals.update(globals_map)
    return gen.gi_frame
