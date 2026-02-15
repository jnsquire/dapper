from __future__ import annotations

import sys
import types

from dapper.launcher import comm as launcher_comm
from dapper.shared import command_handlers
from dapper.shared import command_handlers as handlers
from dapper.shared import debug_shared
from tests.dummy_debugger import DummyDebugger


def capture_send(monkeypatch):
    messages: list[tuple[str, dict]] = []

    def _send(event, **kwargs):
        messages.append((event, kwargs))

    monkeypatch.setattr(debug_shared, "send_debug_message", _send)
    monkeypatch.setattr(handlers, "send_debug_message", _send)
    # Patch where the function is imported into command_handlers
    monkeypatch.setattr(command_handlers, "send_debug_message", _send)
    # Also patch the launcher comm module as fallback
    monkeypatch.setattr(launcher_comm, "send_debug_message", _send)
    return messages


def test_set_breakpoints_and_state(monkeypatch):
    dbg = DummyDebugger()
    debug_shared.state.debugger = dbg
    messages = capture_send(monkeypatch)

    handlers._cmd_set_breakpoints(
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

    handlers._cmd_set_variable({"variablesReference": 1, "name": "a", "value": "2"})
    assert frame.f_locals["a"] == 2
    assert any(m[0] == "setVariable" and m[1].get("success") for m in messages)


def test_set_variable_on_object(monkeypatch):
    dbg = DummyDebugger()
    debug_shared.state.debugger = dbg
    messages = capture_send(monkeypatch)

    obj = {"x": 1}
    dbg.var_refs[2] = ("object", obj)
    handlers._cmd_set_variable({"variablesReference": 2, "name": "x", "value": "3"})
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

    # Ensure a clean session state for deterministic behaviour
    debug_shared.SessionState.reset()

    messages = capture_send(monkeypatch)

    handlers._cmd_loaded_sources({})

    resp = [m for m in messages if m[0] == "response"]
    assert resp
    body = resp[-1][1].get("body", {})
    sources = body.get("sources", [])
    assert any(s.get("name") == "mymod.py" for s in sources)
