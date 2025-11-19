from __future__ import annotations

import sys
import types

from dapper.adapter import dap_command_handlers as handlers
from dapper.shared import debug_shared
from tests.dummy_debugger import DummyDebugger


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
