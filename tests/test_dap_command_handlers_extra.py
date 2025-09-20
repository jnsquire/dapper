import sys
import types

from dapper import dap_command_handlers as handlers
from dapper import debug_shared


class DummyDebugger:
    def __init__(self):
        self.cleared = []
        self.breaks = {}
        self.recorded = []
        self.next_var_ref = 1
        self.var_refs = {}
        self.frame_id_to_frame = {}

    def clear_break(self, path):
        self.cleared.append(path)

    def set_break(self, path, line, cond=None):
        self.breaks.setdefault(path, []).append((int(line), cond))

    def record_breakpoint(self, path, line, **meta):
        self.recorded.append((path, line, meta))


def capture_send(monkeypatch):
    messages = []

    def _send(event, **kwargs):
        messages.append((event, kwargs))

    # Patch both the shared module and the handlers module (handlers imported the function)
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

    # verify debugger cleared and breaks set
    assert "./somefile.py" in dbg.cleared
    assert any(b[0] == 10 for b in dbg.breaks["./somefile.py"])  # line 10
    assert any(b[0] == 20 for b in dbg.breaks["./somefile.py"])  # line 20

    # verify a breakpoints response message was sent
    assert any(m[0] == "breakpoints" for m in messages)


def test_create_variable_object_and_set_variable_scope(monkeypatch):
    dbg = DummyDebugger()
    debug_shared.state.debugger = dbg
    messages = capture_send(monkeypatch)

    class Frame:
        def __init__(self):
            self.f_locals = {"a": 1}
            self.f_globals = {}

    # register a frame
    frame = Frame()
    dbg.frame_id_to_frame[42] = frame
    dbg.var_refs[1] = (42, "locals")

    # setVariable should update the frame locals
    handlers.handle_set_variable({"variablesReference": 1, "name": "a", "value": "2"})
    assert frame.f_locals["a"] == 2

    # verify send_debug_message was called with success True
    assert any(m[0] == "setVariable" and m[1].get("success") for m in messages)


def test_set_variable_on_object(monkeypatch):
    dbg = DummyDebugger()
    debug_shared.state.debugger = dbg
    messages = capture_send(monkeypatch)

    # object var ref
    obj = {"x": 1}
    dbg.var_refs[2] = ("object", obj)
    handlers.handle_set_variable({"variablesReference": 2, "name": "x", "value": "3"})
    assert obj["x"] == 3
    assert any(m[0] == "setVariable" and m[1].get("success") for m in messages)


def test_convert_value_with_context_basic():
    # numeric
    assert handlers._convert_value_with_context("  123 ") == 123
    assert handlers._convert_value_with_context("None") is None
    assert handlers._convert_value_with_context("true") is True
    assert handlers._convert_value_with_context("'abc'") == "abc"


def test_loaded_sources_collect(monkeypatch, tmp_path):
    # create a dummy module file and add to sys.modules
    mod_path = tmp_path / "mymod.py"
    mod_path.write_text("print('hello')\n")

    fake_mod = types.ModuleType("mymod")
    fake_mod.__file__ = str(mod_path)
    fake_mod.__package__ = "my.pkg"

    monkeypatch.setitem(sys.modules, "mymod", fake_mod)

    # ensure state mapping starts empty
    debug_shared.state.source_references.clear()
    debug_shared.state._path_to_ref.clear()

    messages = capture_send(monkeypatch)

    handlers.handle_loaded_sources()

    # a response message should have been sent
    resp = [m for m in messages if m[0] == "response"]
    assert resp
    body = resp[-1][1].get("body", {})
    sources = body.get("sources", [])
    assert any(s.get("name") == "mymod.py" for s in sources)
