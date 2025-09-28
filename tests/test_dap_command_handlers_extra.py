from __future__ import annotations

import sys
import types
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from dapper import dap_command_handlers as handlers
from dapper import debug_shared

if TYPE_CHECKING:
    from dapper.debugger_protocol import Variable


class DummyDebugger:
    def __init__(self) -> None:
        self.next_var_ref: int = 1
        self.var_refs: dict[int, Any] = {}
        self.frame_id_to_frame: dict[int, Any] = {}

        # thread/frame mappings
        self.frames_by_thread: dict[int, list] = {}
        self.threads: dict[int, Any] = {}
        self.current_exception_info: dict[str, Any] = {}
        self.current_frame: Any | None = None
        self.stepping: bool = False

        # optional data breakpoint storage
        self.data_breakpoints: list[dict[str, Any]] | None = []

        # breakpoint bookkeeping
        self.breakpoint_meta: dict[tuple[str, int], dict[str, Any]] = {}
        self.function_breakpoints: list[str] = []
        self.function_breakpoint_meta: dict[str, dict[str, Any]] = {}

        # exception flags
        self.exception_breakpoints_raised: bool = False
        self.exception_breakpoints_uncaught: bool = False

        # misc
        self.cleared: list[str] = []
        self.breaks: dict[str, list[tuple[int, Any | None]]] = {}
        self.recorded: list[tuple[str, int, dict]] = []
        self.stopped_thread_ids: set[int] = set()
    
    def set_break(
        self,
        filename: str,
        lineno: int,
        temporary: bool = False,
        cond: Any | None = None,
        funcname: str | None = None,
    ) -> Any | None:  # type: ignore[override]
        _ = temporary, funcname
        arr = self.breaks.get(filename)
        if arr is None:
            self.breaks[filename] = [(int(lineno), cond)]
        else:
            arr.append((int(lineno), cond))
        return None

    def record_breakpoint(
        self,
        path: str,
        line: int,
        *,
        condition: Any | None = None,
        hit_condition: Any | None = None,
        log_message: Any | None = None,
    ) -> None:
        self.recorded.append(
            (
                path,
                line,
                {
                    "condition": condition,
                    "hit_condition": hit_condition,
                    "log_message": log_message,
                },
            )
        )

    def clear_breaks_for_file(self, path: str) -> None:
        # Record that clear was requested (tests assert this) and remove any breaks
        self.cleared.append(path)
        self.breaks.pop(path, None)

    def clear_break(self, filename: str, lineno: int) -> Any | None:
        # remove a specific breakpoint if present
        arr = self.breaks.get(filename)
        if arr:
            self.breaks[filename] = [b for b in arr if b[0] != int(lineno)]
        return None

    def clear_break_meta_for_file(self, path: str) -> None:
        to_del = [k for k in list(self.breakpoint_meta.keys()) if k[0] == path]
        for k in to_del:
            self.breakpoint_meta.pop(k, None)

    def clear_all_function_breakpoints(self) -> None:
        self.function_breakpoints = []
        self.function_breakpoint_meta.clear()

    def set_continue(self) -> None:
        pass

    def set_next(self, frame: Any) -> None:
        _ = frame

    def set_step(self) -> None:
        pass

    def set_return(self, frame: Any) -> None:
        _ = frame

    def run(self, cmd: Any, *args: Any, **kwargs: Any) -> Any:
        _ = cmd, args, kwargs
        return None

    def make_variable_object(
        self, name: Any, value: Any, frame: Any | None = None, *, max_string_length: int = 1000
    ) -> Variable:
        # Delegate to shared helper to produce a realistic variable object
        from dapper import debug_shared  # noqa: PLC0415

        return cast("Variable", debug_shared.make_variable_object(name, value, self, frame, max_string_length=max_string_length))

    def create_variable_object(
        self, name: Any, value: Any, frame: Any | None = None, *, max_string_length: int = 1000
    ) -> Variable:
        # Backwards-compatible alias used by some callers
        return cast("Variable", self.make_variable_object(name, value, frame, max_string_length=max_string_length))


def capture_send(monkeypatch):
    messages: list[tuple[str, dict]] = []

    def _send(event, **kwargs):
        messages.append((event, kwargs))

    monkeypatch.setattr(debug_shared, "send_debug_message", _send)
    monkeypatch.setattr(handlers, "send_debug_message", _send)
    return messages


def test_set_breakpoints_and_state(monkeypatch):
    dbg = DummyDebugger()
    debug_shared.state.debugger = dbg
    messages = capture_send(monkeypatch)

    handlers.handle_set_breakpoints(
        {
            "source": {"path": "./somefile.py"},
            "breakpoints": [{"line": 10}, {"line": 20, "condition": "x>1"}],
        }
    )

    assert "./somefile.py" in dbg.cleared
    assert any(b[0] == 10 for b in dbg.breaks["./somefile.py"])  # line 10
    assert any(b[0] == 20 for b in dbg.breaks["./somefile.py"])  # line 20
    assert any(m[0] == "breakpoints" for m in messages)


def test_create_variable_object_and_set_variable_scope(monkeypatch):
    dbg = DummyDebugger()
    debug_shared.state.debugger = dbg
    messages = capture_send(monkeypatch)

    class Frame:
        def __init__(self):
            self.f_locals = {"a": 1}
            self.f_globals = {}

    frame = Frame()
    dbg.frame_id_to_frame[42] = frame
    dbg.var_refs[1] = (42, "locals")

    handlers.handle_set_variable({"variablesReference": 1, "name": "a", "value": "2"})
    assert frame.f_locals["a"] == 2
    assert any(m[0] == "setVariable" and m[1].get("success") for m in messages)


def test_set_variable_on_object(monkeypatch):
    dbg = DummyDebugger()
    debug_shared.state.debugger = dbg
    messages = capture_send(monkeypatch)

    obj = {"x": 1}
    dbg.var_refs[2] = ("object", obj)
    handlers.handle_set_variable({"variablesReference": 2, "name": "x", "value": "3"})
    assert obj["x"] == 3
    assert any(m[0] == "setVariable" and m[1].get("success") for m in messages)


def test_convert_value_with_context_basic():
    assert handlers._convert_value_with_context("  123 ") == 123
    assert handlers._convert_value_with_context("None") is None
    assert handlers._convert_value_with_context("true") is True
    assert handlers._convert_value_with_context("'abc'") == "abc"


def test_loaded_sources_collect(monkeypatch, tmp_path):
    mod_path = tmp_path / "mymod.py"
    mod_path.write_text("print('hello')\n")

    fake_mod = types.ModuleType("mymod")
    fake_mod.__file__ = str(mod_path)
    fake_mod.__package__ = "my.pkg"

    monkeypatch.setitem(sys.modules, "mymod", fake_mod)

    debug_shared.state.source_references.clear()
    debug_shared.state._path_to_ref.clear()

    messages = capture_send(monkeypatch)

    handlers.handle_loaded_sources()

    resp = [m for m in messages if m[0] == "response"]
    assert resp
    body = resp[-1][1].get("body", {})
    sources = body.get("sources", [])
    assert any(s.get("name") == "mymod.py" for s in sources)
