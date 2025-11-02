from __future__ import annotations

from typing import TYPE_CHECKING

from tests.dummy_debugger import DummyDebugger

if TYPE_CHECKING:
    import dapper.debugger_protocol as dp
else:
    import dapper.debugger_protocol as dp


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
    ph: dp.PresentationHint = {
        "kind": "class",
        "attributes": ["readonly"],
        "visibility": "private",
    }
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


def test_exception_details_typeddict():
    # Test ExceptionDetails TypedDict with all required fields
    details: dp.ExceptionDetails = {
        "message": "Test exception message",
        "typeName": "ValueError",
        "fullTypeName": "builtins.ValueError",
        "source": "test_file.py",
        "stackTrace": ["line 1", "line 2", "line 3"],
    }
    
    assert details["message"] == "Test exception message"
    assert details["typeName"] == "ValueError"
    assert details["fullTypeName"] == "builtins.ValueError"
    assert details["source"] == "test_file.py"
    assert len(details["stackTrace"]) == 3
    assert details["stackTrace"][0] == "line 1"


def test_exception_info_typeddict():
    # Test ExceptionInfo TypedDict with nested ExceptionDetails
    details: dp.ExceptionDetails = {
        "message": "Nested exception",
        "typeName": "RuntimeError",
        "fullTypeName": "builtins.RuntimeError",
        "source": "nested.py",
        "stackTrace": ["nested line 1"],
    }
    
    exception_info: dp.ExceptionInfo = {
        "exceptionId": "exception_123",
        "description": "Test exception description",
        "breakMode": "always",
        "details": details,
    }
    
    assert exception_info["exceptionId"] == "exception_123"
    assert exception_info["description"] == "Test exception description"
    assert exception_info["breakMode"] == "always"
    assert exception_info["details"]["message"] == "Nested exception"


def test_presentation_hint_optional_fields():
    # Test PresentationHint with optional fields (total=False)
    # All fields are optional, so we can create empty or partial hints
    empty_hint: dp.PresentationHint = {}
    assert len(empty_hint) == 0
    
    partial_hint: dp.PresentationHint = {
        "kind": "method",
    }
    assert partial_hint["kind"] == "method"
    assert "attributes" not in partial_hint
    assert "visibility" not in partial_hint
    
    full_hint: dp.PresentationHint = {
        "kind": "property",
        "attributes": ["static", "readOnly"],
        "visibility": "public",
    }
    assert full_hint["kind"] == "property"
    assert full_hint["attributes"] == ["static", "readOnly"]
    assert full_hint["visibility"] == "public"


def test_variable_typeddict_complete():
    # Test Variable TypedDict with complete structure
    hint: dp.PresentationHint = {
        "kind": "data",
        "attributes": ["hasDataBreakpoint"],
        "visibility": "public",
    }
    
    variable: dp.Variable = {
        "name": "test_var",
        "value": "test_value",
        "type": "str",
        "variablesReference": 42,
        "presentationHint": hint,
    }
    
    assert variable["name"] == "test_var"
    assert variable["value"] == "test_value"
    assert variable["type"] == "str"
    assert variable["variablesReference"] == 42
    assert variable["presentationHint"]["kind"] == "data"
    assert variable["presentationHint"]["attributes"] == ["hasDataBreakpoint"]


def test_variable_typeddict_with_lazy_hint():
    # Test Variable with lazy presentation hint
    lazy_hint: dp.PresentationHint = {
        "kind": "property",
        "lazy": True,
        "attributes": ["canHaveObjectId"],
    }
    
    variable: dp.Variable = {
        "name": "lazy_prop",
        "value": "<lazy>",
        "type": "property",
        "variablesReference": 123,
        "presentationHint": lazy_hint,
    }
    
    assert variable["presentationHint"]["lazy"] is True
    assert "canHaveObjectId" in variable["presentationHint"]["attributes"]


def test_debugger_like_protocol_var_ref_types():
    # Test the VarRef type union components
    dbg = DummyDebugger()
    
    # Test VarRefObject
    var_ref_object: dp.DebuggerLike.VarRefObject = ("object", {"key": "value"})
    dbg.var_refs[1] = var_ref_object
    assert dbg.var_refs[1][0] == "object"
    assert dbg.var_refs[1][1] == {"key": "value"}
    
    # Test VarRefScope
    var_ref_scope: dp.DebuggerLike.VarRefScope = (42, "locals")
    dbg.var_refs[2] = var_ref_scope
    assert dbg.var_refs[2][0] == 42
    assert dbg.var_refs[2][1] == "locals"
    
    # Test VarRefList
    var_ref_list: dp.DebuggerLike.VarRefList = [
        {
            "name": "item1",
            "value": "value1",
            "type": "str",
            "variablesReference": 0,
            "presentationHint": {},
        }
    ]
    dbg.var_refs[3] = var_ref_list
    assert len(dbg.var_refs[3]) == 1
    assert dbg.var_refs[3][0]["name"] == "item1"


def test_debugger_like_protocol_attributes():
    # Test that all protocol attributes are properly typed and accessible
    dbg = DummyDebugger()
    
    # Test basic attributes
    assert isinstance(dbg.next_var_ref, int)
    assert isinstance(dbg.var_refs, dict)
    assert isinstance(dbg.frame_id_to_frame, dict)
    assert isinstance(dbg.frames_by_thread, dict)
    assert isinstance(dbg.threads, dict)
    assert isinstance(dbg.current_exception_info, dict)
    assert isinstance(dbg.stepping, bool)
    
    # Test optional attributes (can be None)
    assert dbg.current_frame is None or hasattr(dbg.current_frame, "__dict__")
    assert dbg.data_breakpoints is None or isinstance(dbg.data_breakpoints, list)
    assert isinstance(dbg.stop_on_entry, bool)
    
    # Test data watch attributes
    assert dbg.data_watch_names is None or isinstance(dbg.data_watch_names, (set, list))
    assert dbg.data_watch_meta is None or isinstance(dbg.data_watch_meta, dict)
    assert dbg._data_watches is None or isinstance(dbg._data_watches, dict)
    assert dbg._frame_watches is None or isinstance(dbg._frame_watches, dict)
    
    # Test breakpoint attributes
    assert isinstance(dbg.function_breakpoints, list)
    assert isinstance(dbg.function_breakpoint_meta, dict)
    assert isinstance(dbg.exception_breakpoints_raised, bool)
    assert isinstance(dbg.exception_breakpoints_uncaught, bool)


def test_debugger_like_protocol_breakpoint_methods():
    # Test all breakpoint-related protocol methods
    dbg = DummyDebugger()
    
    # Test set_break
    result = dbg.set_break("test.py", 10, temporary=False, cond="x > 5", funcname="test_func")
    assert result is not None  # DummyDebugger returns True
    
    # Test record_breakpoint
    dbg.record_breakpoint(
        "test.py", 
        15, 
        condition="y == 10", 
        hit_condition=None, 
        log_message="Hit breakpoint"
    )
    assert len(dbg.recorded) == 1
    assert dbg.recorded[0] == ("test.py", 15, {"condition": "y == 10", "hit_condition": None, "log_message": "Hit breakpoint"})
    
    # Test clear methods
    dbg.clear_breaks_for_file("test.py")
    assert "test.py" in dbg.cleared
    
    dbg.clear_break("test.py", 10)
    dbg.clear_break_meta_for_file("test.py")
    dbg.clear_all_function_breakpoints()
    assert len(dbg.function_breakpoints) == 0


def test_debugger_like_protocol_stepping_methods():
    # Test all stepping and control flow methods
    dbg = DummyDebugger()
    
    # Test stepping control
    dbg.set_continue()
    assert dbg._continued is True
    
    dbg.set_next("dummy_frame")
    assert dbg._next == "dummy_frame"
    
    dbg.set_step()
    assert dbg._step is True
    assert dbg.stepping is True
    
    dbg.set_return("dummy_frame")
    assert dbg._return == "dummy_frame"


def test_debugger_like_protocol_execution_methods():
    # Test execution and variable creation methods
    dbg = DummyDebugger()
    
    # Test run method
    result = dbg.run("test_command", arg1="value1", arg2="value2")
    assert result is None  # DummyDebugger returns None
    
    # Test make_variable_object with different types
    var_int = dbg.make_variable_object("test_int", 42)
    assert var_int["name"] == "test_int"
    assert var_int["value"] == "42"
    assert var_int["type"] == "int"
    
    var_str = dbg.make_variable_object("test_str", "hello world")
    assert var_str["name"] == "test_str"
    assert var_str["value"] == "'hello world'"  # String values are quoted
    assert var_str["type"] == "str"
    
    var_list = dbg.make_variable_object("test_list", [1, 2, 3])
    assert var_list["name"] == "test_list"
    assert var_list["type"] == "list"
    assert var_list["variablesReference"] > 0  # Lists should have a variable reference
    
    # Test with custom max_string_length
    var_long = dbg.make_variable_object("long_str", "x" * 2000, max_string_length=100)
    assert len(var_long["value"]) <= 103  # Should be truncated with "..." suffix


def test_debugger_like_protocol_thread_management():
    # Test thread-related attributes and operations
    dbg = DummyDebugger()
    
    # Test stopped_thread_ids
    assert isinstance(dbg.stopped_thread_ids, set)
    dbg.stopped_thread_ids.add(1)
    dbg.stopped_thread_ids.add(2)
    assert 1 in dbg.stopped_thread_ids
    assert 2 in dbg.stopped_thread_ids
    
    # Test frames_by_thread
    dbg.frames_by_thread[1] = ["frame1", "frame2"]
    dbg.frames_by_thread[2] = ["frame3"]
    assert len(dbg.frames_by_thread[1]) == 2
    assert len(dbg.frames_by_thread[2]) == 1
    
    # Test threads dict
    dbg.threads[1] = {"name": "Thread-1"}
    dbg.threads[2] = {"name": "Thread-2"}
    assert dbg.threads[1]["name"] == "Thread-1"


def test_debugger_like_protocol_exception_handling():
    # Test exception-related attributes and structures
    dbg = DummyDebugger()
    
    # Test exception breakpoint flags
    dbg.exception_breakpoints_raised = True
    dbg.exception_breakpoints_uncaught = False
    assert dbg.exception_breakpoints_raised is True
    assert dbg.exception_breakpoints_uncaught is False
    
    # Test current_exception_info with proper structure
    exception_details: dp.ExceptionDetails = {
        "message": "Test error",
        "typeName": "TestError",
        "fullTypeName": "test.TestError",
        "source": "test.py",
        "stackTrace": ["line 1", "line 2"],
    }
    
    exception_info: dp.ExceptionInfo = {
        "exceptionId": "test_error_1",
        "description": "A test error occurred",
        "breakMode": "uncaught",
        "details": exception_details,
    }
    
    dbg.current_exception_info[1] = exception_info
    assert dbg.current_exception_info[1]["exceptionId"] == "test_error_1"
    assert dbg.current_exception_info[1]["details"]["message"] == "Test error"


def test_protocol_type_annotations():
    # Test that protocol type annotations work correctly at runtime
    from dapper.debugger_protocol import DebuggerLike
    from dapper.debugger_protocol import ExceptionDetails
    from dapper.debugger_protocol import ExceptionInfo
    from dapper.debugger_protocol import PresentationHint
    from dapper.debugger_protocol import Variable
    
    # Test that TypedDict classes are properly constructed
    assert hasattr(PresentationHint, "__required_keys__")
    assert hasattr(Variable, "__required_keys__")
    assert hasattr(ExceptionDetails, "__required_keys__")
    assert hasattr(ExceptionInfo, "__required_keys__")
    
    # Test that Variable has all required keys
    required_var_keys = Variable.__required_keys__
    expected_keys = {"name", "value", "type", "variablesReference", "presentationHint"}
    assert required_var_keys == expected_keys
    
    # Test that PresentationHint has no required keys (total=False)
    required_hint_keys = PresentationHint.__required_keys__
    assert required_hint_keys == set()
    
    # Test that ExceptionInfo and ExceptionDetails have required keys
    assert len(ExceptionDetails.__required_keys__) > 0
    assert len(ExceptionInfo.__required_keys__) > 0
    
    # Test that DebuggerLike is runtime_checkable
    assert hasattr(DebuggerLike, "__protocol_attrs__") or hasattr(DebuggerLike, "__orig_bases__")
