from __future__ import annotations

from dataclasses import dataclass
import json
from typing import TYPE_CHECKING
from typing import Any
from typing import ClassVar
from typing import Protocol

from dapper.ipc.connections.base import ConnectionBase

if TYPE_CHECKING:
    from types import FrameType

    from dapper.protocol.debugger_protocol import DebuggerLike
    from dapper.protocol.debugger_protocol import ExceptionInfo


# Expose names for import convenience in tests
__all__ = ["CodeLike", "FrameLike", "MockCode", "MockConnection", "MockFrame", "make_real_frame"]

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

    async def read_dbgp_message(self) -> str | None:
        """Return a stringified version of the next DAP message for DBGP tests."""
        msg = await self.read_message()
        if msg is None:
            return None
        try:
            return json.dumps(msg)
        except Exception:
            return str(msg)

    async def write_dbgp_message(self, message: str) -> None:
        # Store raw DBGP writes separately so tests can assert
        self.written_messages.append({"dbgp": message})

    def add_request(self, command, arguments=None, seq=1):
        req = {"seq": seq, "type": "request", "command": command}
        if arguments:
            req["arguments"] = arguments
        self.messages.append(req)


class FakeDebugger:
    # match the DebuggerLike ClassVar
    custom_breakpoints: ClassVar[dict[str, Any]] = {}
    """Lightweight Fake debugger implementing the DebuggerLike protocol surface
    used by many unit tests. This doesn't attempt to emulate bdb fully — just
    the attributes and behaviours that command handlers and tests expect.
    """

    def __init__(self, raise_on_set: bool = False):
        # Basic bookkeeping
        self.next_var_ref: int = 1000
        # The real DebuggerLike expects var_refs to map to VarRef shapes; annotate
        # more precisely for static checks.
        self.var_refs: dict[int, DebuggerLike.VarRef] = {}
        self.frame_id_to_frame: dict[int, object] = {}
        self.frames_by_thread: dict[int, list] = {}
        self.threads: dict[int, str] = {}
        self.current_exception_info: dict[int, ExceptionInfo] = {}
        self._data_watches: dict[str, object] = {}
        self._frame_watches: dict[int, list[str]] = {}
        # current_frame is a test-only attribute; expose a real stdlib FrameType
        self._current_frame: FrameType | None = None
        self.stepping = False

        # record calls for test assertions
        self.set_calls: list[tuple[str, str]] = []
        self.register_calls: list[tuple[list[str], list[tuple[str, dict]]]] = []

        # data breakpoint bookkeeping
        self.data_breakpoints: list[dict[str, object]] | None = None
        self.raise_on_set = raise_on_set
        self.stop_on_entry = False
        self.data_watch_names: set[str] | list[str] | None = None
        self.data_watch_meta: dict[str, list[dict[str, object]]] | None = None

        # breakpoint / function bookkeeping
        self.function_breakpoints: list[str] = []
        self.function_breakpoint_meta: dict[str, dict] = {}
        self.exception_breakpoints_raised = False
        self.exception_breakpoints_uncaught = False

        # stopped thread tracking
        self.stopped_thread_ids: set[int] = set()

        # breakpoint structures and frame-eval helpers
        self.breakpoints: dict[str, list[dict[str, object]]] = {}
        self._frame_eval_enabled = False
        self._mock_user_line = None

        # simple flags & state for test convenience
        self.process = None

    # --- Breakpoint API ---
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
        # store metadata for tests
        meta = self.function_breakpoint_meta.setdefault(path, {})
        meta[line] = {
            "condition": condition,
            "hitCondition": hit_condition,
            "logMessage": log_message,
        }

    def clear_breaks_for_file(self, path: str) -> None:
        self.breakpoints.pop(path, None)

    def clear_break(self, filename: str, lineno: int) -> object | None:
        if filename in self.breakpoints:
            self.breakpoints[filename] = [
                b for b in self.breakpoints[filename] if b.get("line") != int(lineno)
            ]
        return None

    def clear_break_meta_for_file(self, path: str) -> None:
        self.function_breakpoint_meta.pop(path, None)

    def clear_all_function_breakpoints(self) -> None:
        self.function_breakpoints.clear()
        self.function_breakpoint_meta.clear()

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

    # --- PyDebugger convenience methods ---
    def set_breakpoints(
        self, source: str, breakpoints: list[dict[str, object]], **_kwargs: object
    ) -> None:
        self.breakpoints[source] = breakpoints  # pyright: ignore[reportArgumentType]

    def user_line(self, _frame: object) -> object | None:
        # simple change detection helper: call into data watches if present
        # tests can set current_frame and rely on other logic
        return None

    def set_trace(self, frame: object | None = None) -> None:
        pass

    def get_trace_function(self):
        return None

    def set_trace_function(self, trace_func):
        pass

    @property
    def current_frame(self) -> FrameType | None:
        """Test shim: current execution frame (optional)."""
        return self._current_frame

    @current_frame.setter
    def current_frame(self, value: FrameType | None) -> None:
        # Expect a real stdlib FrameType in tests
        self._current_frame = value

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

    # --- Data breakpoint helpers used by adapter tests ---
    def set_data_breakpoint(self, data_id: str, access_type: str = "write") -> None:
        # record call and optionally simulate failure
        self.set_calls.append((data_id, access_type))
        if getattr(self, "raise_on_set", False):
            raise RuntimeError("failed")
        # store a simple entry
        self._data_watches[data_id] = {"accessType": access_type}

    def register_data_watches(
        self, names: list[str], metas: list[tuple[str, dict]] | None = None
    ) -> None:
        self.register_calls.append((list(names), list(metas or [])))
        self.data_watch_names = set(names)
        if metas:
            self.data_watch_meta = {n: [] for n in names}
            for name, meta in metas:
                if name in self.data_watch_meta:
                    self.data_watch_meta[name].append(meta)

    def clear_all_data_breakpoints(self) -> None:
        self._data_watches.clear()
        self._frame_watches.clear()


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
