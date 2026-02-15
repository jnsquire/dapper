from __future__ import annotations

import sys
import types

from dapper.launcher import comm as launcher_comm
from dapper.shared import breakpoint_handlers
from dapper.shared import command_handler_helpers
from dapper.shared import command_handlers
from dapper.shared import command_handlers as handlers
from dapper.shared import debug_shared
from dapper.shared import source_handlers
from dapper.shared import variable_command_runtime
from dapper.shared import variable_handlers
from dapper.shared.value_conversion import convert_value_with_context
from tests.dummy_debugger import DummyDebugger

_CONVERSION_FAILED = object()


def _try_test_convert(value_str, frame=None, parent_obj=None):
    try:
        return convert_value_with_context(value_str, frame, parent_obj)
    except (AttributeError, NameError, SyntaxError, TypeError, ValueError):
        return _CONVERSION_FAILED


def _make_variable_for_tests(dbg, name, value, frame):
    return variable_command_runtime.make_variable_runtime(
        dbg,
        name,
        value,
        frame,
        make_variable_helper=command_handler_helpers.make_variable,
        fallback_make_variable=debug_shared.make_variable_object,
        simple_fn_argcount=handlers.SIMPLE_FN_ARGCOUNT,
    )


def _invoke_set_variable_via_domain(dbg, arguments):
    def _set_object_member_direct(parent_obj, name, value):
        return command_handler_helpers.set_object_member(
            parent_obj,
            name,
            value,
            try_custom_convert=_try_test_convert,
            conversion_failed_sentinel=_CONVERSION_FAILED,
            convert_value_with_context_fn=convert_value_with_context,
            assign_to_parent_member_fn=command_handler_helpers.assign_to_parent_member,
            error_response_fn=handlers._error_response,
            conversion_error_message=handlers._CONVERSION_ERROR_MESSAGE,
            get_state_debugger=lambda: handlers.state.debugger,
            make_variable_fn=_make_variable_for_tests,
            logger=handlers.logger,
        )

    def _set_scope_variable_direct(frame, scope, name, value):
        return command_handler_helpers.set_scope_variable(
            frame,
            scope,
            name,
            value,
            try_custom_convert=_try_test_convert,
            conversion_failed_sentinel=_CONVERSION_FAILED,
            evaluate_with_policy_fn=handlers.evaluate_with_policy,
            convert_value_with_context_fn=convert_value_with_context,
            logger=handlers.logger,
            error_response_fn=handlers._error_response,
            conversion_error_message=handlers._CONVERSION_ERROR_MESSAGE,
            get_state_debugger=lambda: handlers.state.debugger,
            make_variable_fn=_make_variable_for_tests,
        )

    result = variable_handlers.handle_set_variable_impl(
        dbg,
        arguments,
        error_response=handlers._error_response,
        set_object_member=_set_object_member_direct,
        set_scope_variable=_set_scope_variable_direct,
        logger=handlers.logger,
        conversion_error_message=handlers._CONVERSION_ERROR_MESSAGE,
        var_ref_tuple_size=handlers.VAR_REF_TUPLE_SIZE,
    )
    if result:
        handlers._safe_send_debug_message("setVariable", **result)


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

    breakpoint_handlers.handle_set_breakpoints_impl(
        dbg,
        {
            "source": {"path": "./somefile.py"},
            "breakpoints": [{"line": 10}, {"line": 20, "condition": "x>1"}],
        },
        handlers._safe_send_debug_message,
        handlers.logger,
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

    _invoke_set_variable_via_domain(dbg, {"variablesReference": 1, "name": "a", "value": "2"})
    assert frame.f_locals["a"] == 2
    assert any(m[0] == "setVariable" and m[1].get("success") for m in messages)


def test_set_variable_on_object(monkeypatch):
    dbg = DummyDebugger()
    debug_shared.state.debugger = dbg
    messages = capture_send(monkeypatch)

    obj = {"x": 1}
    dbg.var_refs[2] = ("object", obj)
    _invoke_set_variable_via_domain(dbg, {"variablesReference": 2, "name": "x", "value": "3"})
    assert obj["x"] == 3
    assert any(m[0] == "setVariable" and m[1].get("success") for m in messages)


def test_convert_value_with_context_basic():
    assert convert_value_with_context("  123 ") == 123
    assert convert_value_with_context("None") is None
    assert convert_value_with_context("true") is True
    assert convert_value_with_context("'abc'") == "abc"


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

    source_handlers.handle_loaded_sources(debug_shared.state, handlers._safe_send_debug_message)

    resp = [m for m in messages if m[0] == "response"]
    assert resp
    body = resp[-1][1].get("body", {})
    sources = body.get("sources", [])
    assert any(s.get("name") == "mymod.py" for s in sources)
