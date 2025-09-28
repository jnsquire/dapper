from __future__ import annotations

import dapper.debugger_protocol as dp
from tests.dummy_debugger import DummyDebugger


def test_runtime_protocol_check():
    dbg = DummyDebugger()
    # Instead of relying on runtime isinstance semantics for Protocols (which
    # can be fragile across typing implementations), assert the concrete
    # attributes and methods used by the protocol exist on our dummy.
    for attr in (
        "next_var_ref",
        "var_refs",
        "frame_id_to_frame",
        "frames_by_thread",
        "threads",
        "current_exception_info",
        "current_frame",
        "stepping",
        "data_breakpoints",
        "stop_on_entry",
        "data_watch_names",
        "data_watch_meta",
        "_data_watches",
        "_frame_watches",
        "function_breakpoints",
        "function_breakpoint_meta",
        "exception_breakpoints_raised",
        "exception_breakpoints_uncaught",
        "stopped_thread_ids",
    ):
        assert hasattr(dbg, attr), f"Missing attribute {attr} on dummy debugger"

    for method in (
        "set_break",
        "record_breakpoint",
        "clear_breaks_for_file",
        "clear_break",
        "clear_break_meta_for_file",
        "clear_all_function_breakpoints",
        "set_continue",
        "set_next",
        "set_step",
        "set_return",
        "run",
        "make_variable_object",
    ):
        assert callable(getattr(dbg, method, None)), f"Missing method {method} on dummy debugger"


def test_make_variable_object_structure():
    dbg = DummyDebugger()
    v = dbg.make_variable_object("x", 123)
    assert v["name"] == "x"
    assert v["value"] == "123"
    assert v["type"] == "int"
    assert isinstance(v["variablesReference"], int)
    assert isinstance(v["presentationHint"], dict)


def test_presentation_hint_and_variable_typeddict():
    # Create concrete typed-dicts and ensure they behave like mappings at runtime
    ph: dp.PresentationHint = {"kind": "class", "attributes": ["readonly"], "visibility": "private"}
    assert ph["kind"] == "class"

    var: dp.Variable = {
        "name": "y",
        "value": "val",
        "type": "str",
        "variablesReference": 0,
        "presentationHint": ph,
    }
    # Access via .get to satisfy static analyzers that mark the key as optional
    assert var["presentationHint"].get("visibility") == "private"
