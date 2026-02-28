"""Comprehensive integration tests for debug_launcher.py handlers.

This module provides extensive test coverage for debug launcher command handlers,
including edge cases, error conditions, and integration scenarios.
"""

from __future__ import annotations

import io
import json
import queue
import threading
from typing import TYPE_CHECKING
from typing import Any
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import PropertyMock

import pytest

from dapper.core.debugger_bdb import DebuggerBDB
from dapper.launcher import debug_launcher
from dapper.shared import breakpoint_handlers
from dapper.shared import command_handler_helpers
from dapper.shared import command_handlers as handlers
from dapper.shared import debug_shared
from dapper.shared import lifecycle_handlers
from dapper.shared import stack_handlers
from dapper.shared import stepping_handlers
from dapper.shared import variable_handlers
from dapper.shared.value_conversion import convert_value_with_context
from tests.dummy_debugger import DummyDebugger

if TYPE_CHECKING:
    from dapper.protocol.requests import FunctionBreakpoint
    from dapper.protocol.requests import SetFunctionBreakpointsArguments


class MockWFile(io.TextIOBase):
    """A mock file-like object that implements TextIOBase interface."""

    def __init__(self):
        super().__init__()
        self.written = []
        self.flushed = False

    def write(self, data: str) -> int:
        self.written.append(data)
        return len(data)

    def flush(self) -> None:
        self.flushed = True

    def close(self) -> None:
        self.flush()

    def writable(self) -> bool:
        return True


class MockCode:
    def __init__(self, name="test_func", filename="<test>", firstlineno=1):
        self.co_name = name
        self.co_filename = filename
        self.co_firstlineno = firstlineno


class MockFrame:
    def __init__(
        self,
        _locals: dict | None = None,
        _globals: dict | None = None,
        name="test_func",
        filename="<test>",
        lineno=1,
    ):
        self.f_locals = dict(_locals or {})
        self.f_globals = dict(_globals or {})
        self.f_code = MockCode(name=name, filename=filename, firstlineno=lineno)
        self.f_lineno = lineno
        self.f_back = None

    def __repr__(self):
        return f"<MockFrame {self.f_code.co_name} at {self.f_code.co_filename}:{self.f_lineno}>"


_CONVERSION_FAILED = object()


def _try_convert(value_str: str, frame: Any | None = None, parent_obj: Any | None = None) -> Any:
    try:
        return convert_value_with_context(value_str, frame, parent_obj)
    except (AttributeError, NameError, SyntaxError, TypeError, ValueError):
        return _CONVERSION_FAILED


def _set_object_member_direct(parent_obj: Any, name: str, value_str: str) -> dict[str, Any]:
    return command_handler_helpers.set_object_member(
        parent_obj,
        name,
        value_str,
        try_custom_convert=_try_convert,
        conversion_failed_sentinel=_CONVERSION_FAILED,
        convert_value_with_context_fn=convert_value_with_context,
        assign_to_parent_member_fn=command_handler_helpers.assign_to_parent_member,
        error_response_fn=handlers._error_response,
        conversion_error_message=handlers._CONVERSION_ERROR_MESSAGE,
        get_state_debugger=lambda: _session().debugger,
        make_variable_fn=_make_variable,
        logger=handlers.logger,
    )


def _set_scope_variable_direct(
    frame: Any,
    scope: str,
    name: str,
    value_str: str,
) -> dict[str, Any]:
    return command_handler_helpers.set_scope_variable(
        frame,
        scope,
        name,
        value_str,
        try_custom_convert=_try_convert,
        conversion_failed_sentinel=_CONVERSION_FAILED,
        evaluate_with_policy_fn=handlers.evaluate_with_policy,
        convert_value_with_context_fn=convert_value_with_context,
        logger=handlers.logger,
        error_response_fn=handlers._error_response,
        conversion_error_message=handlers._CONVERSION_ERROR_MESSAGE,
        get_state_debugger=lambda: _session().debugger,
        make_variable_fn=_make_variable,
    )


def _make_variable(dbg: Any, name: str, value: Any, frame: Any | None) -> dict[str, Any]:
    return command_handler_helpers.make_variable(
        dbg,
        name,
        value,
        frame,
    )


def _resolve_variables_for_reference(dbg: Any, frame_info: Any) -> list[dict[str, Any]]:
    def _extract_from_mapping(
        helper_dbg: Any,
        mapping: dict[str, Any],
        frame: Any,
    ) -> list[dict[str, Any]]:
        return command_handler_helpers.extract_variables_from_mapping(
            helper_dbg,
            mapping,
            frame,
            make_variable_fn=_make_variable,
        )

    return command_handler_helpers.resolve_variables_for_reference(
        dbg,
        frame_info,
        make_variable_fn=_make_variable,
        extract_variables_from_mapping_fn=_extract_from_mapping,
        var_ref_tuple_size=handlers.VAR_REF_TUPLE_SIZE,
    )


def _handle_set_variable(session: Any, arguments: dict[str, Any]) -> dict[str, Any]:
    return variable_handlers.handle_set_variable_impl(
        session,
        arguments,
        error_response=handlers._error_response,
        set_object_member=_set_object_member_direct,
        set_scope_variable=_set_scope_variable_direct,
        logger=handlers.logger,
        conversion_error_message=handlers._CONVERSION_ERROR_MESSAGE,
        var_ref_tuple_size=handlers.VAR_REF_TUPLE_SIZE,
    )


@pytest.fixture(autouse=True)
def _isolated_active_session():
    """Run each test with an isolated explicit DebugSession.

    This avoids cross-test mutation of the default module-level session.
    """
    session = debug_shared.DebugSession()
    with debug_shared.use_session(session):
        session.debugger = None
        session.is_terminated = False
        session.ipc_enabled = True
        session.ipc_rfile = None
        session.ipc_wfile = MockWFile()
        session.command_queue = queue.Queue()
        yield session


def _session() -> debug_shared.DebugSession:
    return debug_shared.get_active_session()


def _session_with_debugger(dbg: Any) -> tuple[debug_shared.DebugSession, Any]:
    s = _session()
    s.debugger = dbg
    return s, dbg


def test_handle_set_breakpoints_success(tmp_path):
    """Test successful breakpoint setting with various conditions."""
    s, dbg = _session_with_debugger(DebuggerBDB())

    src = tmp_path / "bp_success.py"
    src.write_text("\n".join(f"x = {i}" for i in range(1, 51)) + "\n", encoding="utf-8")
    src_path = str(src)

    # Test setting breakpoints with conditions
    arguments = {
        "source": {"path": src_path},
        "breakpoints": [
            {
                "line": 10,
                "condition": "x > 5",
                "hitCondition": ">3",
                "logMessage": "Hit breakpoint",
            },
            {"line": 20},
            {"line": 30, "condition": "y == 10"},
        ],
    }

    result = breakpoint_handlers.handle_set_breakpoints_impl(
        s,
        arguments,
        handlers.logger,
    )

    assert result is not None
    assert result["success"] is True
    body = result["body"]
    assert "breakpoints" in body

    breakpoints = body["breakpoints"]
    assert len(breakpoints) == 3
    assert all(bp["verified"] is True for bp in breakpoints)
    assert breakpoints[0]["line"] == 10
    assert breakpoints[1]["line"] == 20
    assert breakpoints[2]["line"] == 30

    # Verify line breakpoint metadata was recorded on the real debugger
    bp_meta_10 = dbg.bp_manager.get_line_meta(src_path, 10)
    bp_meta_20 = dbg.bp_manager.get_line_meta(src_path, 20)
    bp_meta_30 = dbg.bp_manager.get_line_meta(src_path, 30)

    assert bp_meta_10 is not None
    assert bp_meta_20 is not None
    assert bp_meta_30 is not None
    assert bp_meta_10["condition"] == "x > 5"
    assert bp_meta_10["hitCondition"] == ">3"
    assert bp_meta_10["logMessage"] == "Hit breakpoint"
    assert bp_meta_20["condition"] is None
    assert bp_meta_30["condition"] == "y == 10"


def test_handle_set_breakpoints_failure(monkeypatch):
    """Test breakpoint setting when debugger returns False."""
    s, dbg = _session_with_debugger(DebuggerBDB())

    # Create a mock function that will replace set_break
    def mock_set_break(
        self,
        filename: str,
        lineno: int,
        temporary: bool = False,
        cond: Any | None = None,
        funcname: str | None = None,
    ) -> Any | None:
        # This mock always returns False to simulate a failed breakpoint set
        return False

    # Use monkeypatch to replace the method with proper binding
    monkeypatch.setattr(dbg, "set_break", mock_set_break.__get__(dbg, DebuggerBDB))

    arguments = {"source": {"path": "/test/file.py"}, "breakpoints": [{"line": 10}]}

    result = breakpoint_handlers.handle_set_breakpoints_impl(
        s,
        arguments,
        handlers.logger,
    )

    assert result is not None
    assert result["success"] is True
    breakpoints = result["body"]["breakpoints"]
    assert len(breakpoints) == 1
    assert breakpoints[0]["verified"] is False


def test_handle_set_breakpoints_exception_handling(monkeypatch):
    """Test graceful handling when set_break raises an exception."""
    s, dbg = _session_with_debugger(DebuggerBDB())

    # Mock set_break to raise an exception using monkeypatch
    def mock_set_break(self, filename, lineno, temporary=False, cond=None, funcname=None):
        raise ValueError("Test error")

    monkeypatch.setattr(dbg, "set_break", mock_set_break.__get__(dbg, DebuggerBDB))

    arguments = {"source": {"path": "/test/file.py"}, "breakpoints": [{"line": 10}]}

    result = breakpoint_handlers.handle_set_breakpoints_impl(
        s,
        arguments,
        handlers.logger,
    )

    assert result is not None
    assert result["success"] is True
    breakpoints = result["body"]["breakpoints"]
    assert len(breakpoints) == 1
    assert breakpoints[0]["verified"] is False


def test_handle_set_function_breakpoints():
    """Test setting function breakpoints."""
    s, dbg = _session_with_debugger(DebuggerBDB())

    arguments = cast(
        "SetFunctionBreakpointsArguments",
        {
            "breakpoints": [
                cast(
                    "FunctionBreakpoint",
                    {"name": "test_func1", "condition": "x > 5", "hitCondition": ">3"},
                ),
                cast("FunctionBreakpoint", {"name": "test_func2"}),
                cast("FunctionBreakpoint", {"name": "test_func3", "logMessage": "Function hit"}),
            ],
        },
    )

    result = breakpoint_handlers.handle_set_function_breakpoints_impl(s, arguments)

    assert result is not None
    assert result["success"] is True
    body = result["body"]
    assert "breakpoints" in body

    breakpoints = body["breakpoints"]
    assert len(breakpoints) == 3
    assert all(bp["verified"] is True for bp in breakpoints)

    # Verify function breakpoints were stored
    assert "test_func1" in dbg.bp_manager.function_names
    assert "test_func2" in dbg.bp_manager.function_names
    assert "test_func3" in dbg.bp_manager.function_names

    # Verify metadata was recorded
    meta1 = dbg.bp_manager.function_meta["test_func1"]
    assert meta1["condition"] == "x > 5"
    assert meta1["hitCondition"] == ">3"

    meta3 = dbg.bp_manager.function_meta["test_func3"]
    assert meta3["logMessage"] == "Function hit"


def test_handle_set_function_breakpoints_empty():
    """Test setting function breakpoints with empty list."""
    s, dbg = _session_with_debugger(DebuggerBDB())

    # Add some existing breakpoints first
    dbg.bp_manager.function_names = ["old_func"]
    dbg.bp_manager.function_meta["old_func"] = {"condition": "old"}

    arguments: SetFunctionBreakpointsArguments = {"breakpoints": []}

    result = breakpoint_handlers.handle_set_function_breakpoints_impl(s, arguments)

    assert result is not None
    assert result["success"] is True
    assert len(dbg.bp_manager.function_names) == 0
    assert len(dbg.bp_manager.function_meta) == 0


def test_handle_set_exception_breakpoints():
    """Test setting exception breakpoints."""
    s, dbg = _session_with_debugger(DebuggerBDB())

    # Test with raised and uncaught filters
    arguments = {"filters": ["raised", "uncaught"]}

    result = breakpoint_handlers.handle_set_exception_breakpoints_impl(s, arguments)

    assert result is not None
    assert result["success"] is True
    assert "body" in result
    body = result["body"]
    assert "breakpoints" in body

    breakpoints = body["breakpoints"]
    assert len(breakpoints) == 2
    assert all(bp["verified"] is True for bp in breakpoints)

    # Verify flags were set
    assert dbg.exception_handler.config.break_on_raised is True
    assert dbg.exception_handler.config.break_on_uncaught is True

    # Test with only raised filter
    arguments = {"filters": ["raised"]}
    result = breakpoint_handlers.handle_set_exception_breakpoints_impl(s, arguments)

    assert dbg.exception_handler.config.break_on_raised is True
    assert dbg.exception_handler.config.break_on_uncaught is False


def test_handle_set_exception_breakpoints_invalid_filters():
    """Test exception breakpoints with invalid filter types."""
    s, _dbg = _session_with_debugger(DebuggerBDB())

    # Test with non-list filters
    arguments = {"filters": "invalid"}

    result = breakpoint_handlers.handle_set_exception_breakpoints_impl(s, arguments)

    assert result is not None
    assert result["success"] is True
    assert "body" in result
    body = result["body"]
    assert "breakpoints" in body
    breakpoints = body["breakpoints"]
    assert len(breakpoints) == 0  # Should be empty list for invalid filters


def test_handle_set_exception_breakpoints_exception_handling():
    """Test graceful handling when setting exception flags fails."""

    # Create a debugger that will fail when setting exception flags
    class FailingDebugger(DebuggerBDB):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            # Replace exception_handler.config with a mock that raises on set
            mock_config = MagicMock()

            def raise_on_set(_):
                raise AttributeError("Cannot set attribute")

            type(mock_config).break_on_raised = PropertyMock(side_effect=raise_on_set)
            type(mock_config).break_on_uncaught = PropertyMock(side_effect=raise_on_set)
            self.exception_handler.config = mock_config

    s, _failing_dbg = _session_with_debugger(FailingDebugger())

    # Test with one filter that will cause an exception
    arguments = {"filters": ["raised"]}

    result = breakpoint_handlers.handle_set_exception_breakpoints_impl(s, arguments)

    # Verify the response structure
    assert result is not None
    assert result["success"] is True
    assert "body" in result
    body = result["body"]
    assert "breakpoints" in body
    breakpoints = body["breakpoints"]

    # The function should return one breakpoint result per filter
    # Since we're only setting one filter, we expect one result
    assert len(breakpoints) == 1

    # The breakpoint should be marked as not verified because our FailingDebugger
    # raises an AttributeError when setting the attribute
    assert breakpoints[0]["verified"] is False

    # Also test with an empty filters list to ensure it handles that case
    empty_result = breakpoint_handlers.handle_set_exception_breakpoints_impl(
        s,
        {"filters": []},
    )
    assert empty_result is not None
    assert empty_result["success"] is True
    assert "body" in empty_result
    body = empty_result["body"]
    assert "breakpoints" in body
    assert len(body["breakpoints"]) == 0


def test_handle_continue():
    """Test continue command handling."""
    s, dbg = _session_with_debugger(DummyDebugger())

    # Add a stopped thread
    thread_id = 123
    dbg.stopped_thread_ids.add(thread_id)

    arguments = {"threadId": thread_id}

    stepping_handlers.handle_continue_impl(s, arguments)

    assert thread_id not in dbg.stopped_thread_ids
    assert dbg._continued is True


def test_handle_continue_multiple_threads():
    """Test continue with multiple stopped threads."""
    s, dbg = _session_with_debugger(DummyDebugger())

    # Add multiple stopped threads
    thread_id1 = 123
    thread_id2 = 456
    dbg.stopped_thread_ids.update([thread_id1, thread_id2])

    # Continue one thread
    stepping_handlers.handle_continue_impl(s, {"threadId": thread_id1})

    assert thread_id1 not in dbg.stopped_thread_ids
    assert thread_id2 in dbg.stopped_thread_ids
    assert dbg._continued is False  # Should not continue yet

    # Continue second thread
    stepping_handlers.handle_continue_impl(s, {"threadId": thread_id2})

    assert thread_id2 not in dbg.stopped_thread_ids
    assert dbg._continued is True  # Should continue now


def test_handle_step_commands():
    """Test step in/out/next commands."""
    s, dbg = _session_with_debugger(DummyDebugger())

    # Create a mock frame
    frame = MockFrame()
    dbg.current_frame = frame

    # Mock current thread ID
    current_thread_id = threading.get_ident()

    # Test step in
    stepping_handlers.handle_step_in_impl(
        s,
        {"threadId": current_thread_id},
        handlers._get_thread_ident,
        handlers._set_dbg_stepping_flag,
    )
    assert dbg.stepping is True
    assert dbg._step is True

    # Reset
    dbg.stepping = False
    dbg._step = False

    # Test step over (next)
    stepping_handlers.handle_next_impl(
        s,
        {"threadId": current_thread_id},
        handlers._get_thread_ident,
        handlers._set_dbg_stepping_flag,
    )
    assert dbg.stepping is True
    assert dbg._next is frame

    # Reset
    dbg.stepping = False
    dbg._next = None

    # Test step out
    stepping_handlers.handle_step_out_impl(
        s,
        {"threadId": current_thread_id},
        handlers._get_thread_ident,
        handlers._set_dbg_stepping_flag,
    )
    assert dbg.stepping is True
    assert dbg._return is frame


def test_handle_pause():
    """Test pause command handling — thread should be marked stopped."""
    s, dbg = _session_with_debugger(DebuggerBDB())

    # Pause the remote thread id and verify bookkeeping + stopped event
    stepping_handlers.handle_pause_impl(
        s,
        {"threadId": 123},
        handlers._get_thread_ident,
        handlers.logger,
    )

    assert 123 in dbg.thread_tracker.stopped_thread_ids


def test_handle_stack_trace():
    """Test stack trace command handling."""
    s, dbg = _session_with_debugger(DebuggerBDB())

    # Create mock frames
    frame1 = {"id": 1, "name": "func1", "line": 10}
    frame2 = {"id": 2, "name": "func2", "line": 20}
    frame3 = {"id": 3, "name": "func3", "line": 30}

    thread_id = 123
    dbg.thread_tracker.frames_by_thread[thread_id] = [frame1, frame2, frame3]

    # Test full stack trace
    stack_handlers.handle_stack_trace_impl(
        s,
        {"threadId": thread_id},
        get_thread_ident=handlers._get_thread_ident,
    )

    # Test with startFrame and levels
    stack_handlers.handle_stack_trace_impl(
        s,
        {"threadId": thread_id, "startFrame": 1, "levels": 2},
        get_thread_ident=handlers._get_thread_ident,
    )


def test_handle_stack_trace_pagination():
    """Test stack trace pagination with startFrame and levels."""
    s, dbg = _session_with_debugger(DebuggerBDB())

    # Create many mock frames
    frames = [{"id": i, "name": f"func{i}", "line": i * 10} for i in range(1, 11)]
    thread_id = 123
    dbg.thread_tracker.frames_by_thread[thread_id] = frames

    # Test pagination
    stack_handlers.handle_stack_trace_impl(
        s,
        {"threadId": thread_id, "startFrame": 2, "levels": 3},
        get_thread_ident=handlers._get_thread_ident,
    )


def test_handle_variables_cached_list():
    """Test variables command with cached list."""
    s, dbg = _session_with_debugger(DummyDebugger())

    # Create cached variables list
    var_ref = 100
    cached_vars = [
        {"name": "x", "value": "1", "type": "int"},
        {"name": "y", "value": "hello", "type": "str"},
    ]
    dbg.var_refs[var_ref] = cached_vars

    variable_handlers.handle_variables_impl(
        s,
        {"variablesReference": var_ref},
        _resolve_variables_for_reference,
    )
    # Should not raise exception and should send message


def test_handle_variables_object_reference():
    """Test variables command with object reference."""
    s, dbg = _session_with_debugger(DummyDebugger())

    # Create object reference
    var_ref = 101
    test_obj = {"key1": "value1", "key2": 42}
    dbg.var_refs[var_ref] = ("object", test_obj)

    variable_handlers.handle_variables_impl(
        s,
        {"variablesReference": var_ref},
        _resolve_variables_for_reference,
    )
    # Should not raise exception and should send message


def test_handle_variables_scope_reference():
    """Test variables command with scope reference."""
    s, dbg = _session_with_debugger(DummyDebugger())

    # Create frame and scope reference
    frame_id = 1
    frame = MockFrame(
        _locals={"local_var": "local_value"},
        _globals={"global_var": "global_value"},
    )
    dbg.frame_id_to_frame[frame_id] = frame

    var_ref = 102
    dbg.var_refs[var_ref] = (frame_id, "locals")

    variable_handlers.handle_variables_impl(
        s,
        {"variablesReference": var_ref},
        _resolve_variables_for_reference,
    )
    # Should not raise exception and should send message


def test_handle_variables_invalid_reference():
    """Test variables command with invalid reference."""
    s, dbg = _session_with_debugger(DummyDebugger())

    # Test with non-existent reference
    variable_handlers.handle_variables_impl(
        s,
        {"variablesReference": 999},
        _resolve_variables_for_reference,
    )
    # Should not raise exception

    # Test with invalid reference type
    var_ref = 103
    dbg.var_refs[var_ref] = "invalid_type"

    variable_handlers.handle_variables_impl(
        s,
        {"variablesReference": var_ref},
        _resolve_variables_for_reference,
    )
    # Should not raise exception


def test_handle_set_variable_object_member():
    """Test setting variable on object."""
    s, dbg = _session_with_debugger(DummyDebugger())

    # Create object reference
    var_ref = 104
    test_obj = {"existing_key": "old_value"}
    dbg.var_refs[var_ref] = ("object", test_obj)

    result = _handle_set_variable(
        s,
        {"variablesReference": var_ref, "name": "existing_key", "value": "new_value"},
    )

    assert result is not None
    assert result["success"] is True
    assert test_obj["existing_key"] == "new_value"


def test_handle_set_variable_list_member():
    """Test setting variable in list."""
    s, dbg = _session_with_debugger(DummyDebugger())

    # Create list reference
    var_ref = 105
    test_list = ["item0", "item1", "item2"]
    dbg.var_refs[var_ref] = ("object", test_list)

    result = _handle_set_variable(
        s,
        {"variablesReference": var_ref, "name": "1", "value": "new_item"},
    )

    assert result is not None
    assert result["success"] is True
    assert test_list[1] == "new_item"


def test_handle_set_variable_list_invalid_index():
    """Test setting variable with invalid list index."""
    s, dbg = _session_with_debugger(DummyDebugger())

    # Create list reference
    var_ref = 106
    test_list = ["item0", "item1"]
    dbg.var_refs[var_ref] = ("object", test_list)

    # Test invalid index
    result = _handle_set_variable(
        s,
        {"variablesReference": var_ref, "name": "invalid", "value": "new_item"},
    )

    assert result is not None
    assert result["success"] is False
    assert "Invalid list index" in result["message"]

    # Test out of range index
    result = _handle_set_variable(
        s,
        {"variablesReference": var_ref, "name": "5", "value": "new_item"},
    )

    assert result is not None
    assert result["success"] is False
    assert "out of range" in result["message"]


def test_handle_set_variable_tuple():
    """Test setting variable on tuple (should fail)."""
    s, dbg = _session_with_debugger(DummyDebugger())

    # Create tuple reference
    var_ref = 107
    test_tuple = ("item0", "item1")
    dbg.var_refs[var_ref] = ("object", test_tuple)

    result = _handle_set_variable(
        s,
        {"variablesReference": var_ref, "name": "0", "value": "new_item"},
    )

    assert result is not None
    assert result["success"] is False
    assert "immutable" in result["message"]


def test_handle_set_variable_scope_variable():
    """Test setting variable in frame scope."""
    s, dbg = _session_with_debugger(DummyDebugger())

    # Create frame and scope reference
    frame_id = 2
    frame = MockFrame(_locals={"x": 1, "y": "old"})
    dbg.frame_id_to_frame[frame_id] = frame

    var_ref = 108
    dbg.var_refs[var_ref] = (frame_id, "locals")

    result = _handle_set_variable(
        s,
        {"variablesReference": var_ref, "name": "y", "value": "new_value"},
    )

    assert result is not None
    assert result["success"] is True
    assert frame.f_locals["y"] == "new_value"


def test_handle_set_variable_invalid_reference():
    """Test setting variable with invalid reference."""
    s, _dbg = _session_with_debugger(DummyDebugger())

    result = _handle_set_variable(s, {"variablesReference": 999, "name": "x", "value": "value"})

    assert result is not None
    assert result["success"] is False
    assert "Invalid variable reference" in result["message"]


def test_handle_evaluate():
    """Test evaluate command."""
    s, dbg = _session_with_debugger(DummyDebugger())

    # Create frame
    frame_id = 3
    frame = MockFrame(_locals={"x": 5, "y": 10}, _globals={"z": 15})
    dbg.frame_id_to_frame[frame_id] = frame

    # Test simple expression
    variable_handlers.handle_evaluate_impl(
        s,
        {"expression": "x + y", "frameId": frame_id, "context": "watch"},
        evaluate_with_policy=handlers.evaluate_with_policy,
        format_evaluation_error=variable_handlers.format_evaluation_error,
        logger=handlers.logger,
    )

    # Test expression that creates variable reference
    variable_handlers.handle_evaluate_impl(
        s,
        {"expression": "{'a': 1}", "frameId": frame_id, "context": "watch"},
        evaluate_with_policy=handlers.evaluate_with_policy,
        format_evaluation_error=variable_handlers.format_evaluation_error,
        logger=handlers.logger,
    )

    # Test expression with error
    variable_handlers.handle_evaluate_impl(
        s,
        {"expression": "undefined_var", "frameId": frame_id, "context": "watch"},
        evaluate_with_policy=handlers.evaluate_with_policy,
        format_evaluation_error=variable_handlers.format_evaluation_error,
        logger=handlers.logger,
    )


def test_handle_evaluate_no_frame():
    """Test evaluate command without frame."""
    s, _dbg = _session_with_debugger(DummyDebugger())

    variable_handlers.handle_evaluate_impl(
        s,
        {"expression": "1 + 1", "context": "watch"},
        evaluate_with_policy=handlers.evaluate_with_policy,
        format_evaluation_error=variable_handlers.format_evaluation_error,
        logger=handlers.logger,
    )
    # Should not raise exception


def test_handle_evaluate_invalid_expression():
    """Test evaluate command with invalid expression type."""
    s, dbg = _session_with_debugger(DummyDebugger())

    frame_id = 4
    frame = MockFrame()
    dbg.frame_id_to_frame[frame_id] = frame

    # Test with non-string expression
    try:
        variable_handlers.handle_evaluate_impl(
            s,
            {
                "expression": 123,  # Not a string
                "frameId": frame_id,
                "context": "watch",
            },
            evaluate_with_policy=handlers.evaluate_with_policy,
            format_evaluation_error=variable_handlers.format_evaluation_error,
            logger=handlers.logger,
        )
        raise AssertionError("Should have raised TypeError")
    except TypeError:
        pass  # Expected


def test_handle_exception_info():
    """Test exception info command."""
    s, dbg = _session_with_debugger(DummyDebugger())

    # Create exception info
    thread_id = 123
    exception_info = {
        "exceptionId": "ValueError",
        "description": "Test error",
        "breakMode": "always",
        "details": {"stackTrace": "line1\nline2"},
    }
    dbg.current_exception_info[thread_id] = exception_info

    lifecycle_handlers.handle_exception_info_impl(dbg, {"threadId": thread_id}, handlers.logger)
    # Should send exception info message

    # Test with missing threadId
    lifecycle_handlers.handle_exception_info_impl(dbg, {}, handlers.logger)
    # Should send error message

    # Test with no debugger
    s.debugger = None
    lifecycle_handlers.handle_exception_info_impl(dbg, {"threadId": thread_id}, handlers.logger)
    # Should send error message


def test_handle_configuration_done():
    """Test configuration done command."""
    _s, _dbg = _session_with_debugger(DummyDebugger())

    lifecycle_handlers.handle_configuration_done_impl()
    # Should not raise exception and return None (no-op)


def test_handle_terminate():
    """Test terminate command."""
    s, _dbg = _session_with_debugger(DummyDebugger())

    # Test that the command sets termination flag
    # Note: We can't test os._exit without actually exiting
    # Inject a test-friendly exit function so we don't kill the test runner.
    orig_exit = s.exit_func

    def fake_exit(code: int):
        raise SystemExit(code)

    s.set_exit_func(fake_exit)
    try:
        # handle_terminate_impl now returns a success dict rather than
        # calling exit_func directly (exit_func is called by the command
        # wrapper after the response is sent).
        result = lifecycle_handlers.handle_terminate_impl(
            state=s,
        )
        assert result == {"success": True}
        assert s.is_terminated is True
    finally:
        # Restore original behavior
        s.set_exit_func(orig_exit)


def test_handle_restart():
    """Test restart command and ensure session resources are cleaned up."""
    s, _dbg = _session_with_debugger(DummyDebugger())

    # Ensure IPC is active at the start (setup_function already sets ipc_wfile)
    assert s.ipc_wfile is not None

    # Add a fake pipe_conn to validate it is closed during restart
    class FakePipe:
        def __init__(self):
            self.closed = False
            self.sent_bytes: list[bytes] = []
            self.sent_values: list[object] = []

        def send_bytes(self, payload: bytes) -> None:
            self.sent_bytes.append(payload)

        def send(self, value: object) -> None:
            self.sent_values.append(value)

        def close(self):
            self.closed = True

    fake_pipe = FakePipe()
    s.ipc_pipe_conn = fake_pipe

    # Override exec behavior so we don't replace the test process.
    orig_exec = s.exec_func

    def fake_exec(path: str, args: list[str]):
        # Verify cleanup has already occurred by the time exec is invoked
        assert s.is_terminated is True
        assert s.ipc_wfile is None
        assert s.ipc_pipe_conn is None
        # Signal via exception so test can assert restart was attempted
        raise SystemExit(("exec_called", path, tuple(args)))

    s.set_exec_func(fake_exec)
    try:
        with pytest.raises(SystemExit) as excinfo:
            lifecycle_handlers.handle_restart_impl(
                state=s,
                logger=handlers.logger,
            )

        # The exit code should be a tuple with our test data
        exit_code = excinfo.value.code
        assert isinstance(exit_code, tuple)
        assert len(exit_code) >= 1
        assert exit_code[0] == "exec_called"

        # fake_pipe.close() should have been called and pipe cleared
        assert fake_pipe.closed is True
    finally:
        s.set_exec_func(orig_exec)


def test_handle_threads_with_data():
    """Test threads command with actual thread data."""
    s, dbg = _session_with_debugger(DebuggerBDB())

    # Add thread data
    dbg.thread_tracker.threads = {1: "MainThread", 2: "WorkerThread"}

    result = stack_handlers.handle_threads_impl(s, {})

    assert result is not None
    assert result["success"] is True
    body = result["body"]
    assert "threads" in body

    threads = body["threads"]
    assert len(threads) == 2
    assert any(t["id"] == 1 and t["name"] == "MainThread" for t in threads)
    assert any(t["id"] == 2 and t["name"] == "WorkerThread" for t in threads)


def test_handle_debug_command_no_debugger():
    """Test debug command handling when debugger is not initialized."""
    s = _session()
    s.debugger = None

    # Command should be queued without error
    handlers.handle_debug_command({"command": "initialize", "arguments": {}})

    # Should not raise exception


def test_handle_debug_command_unsupported():
    """Test debug command handling for unsupported commands."""
    _s, _dbg = _session_with_debugger(DebuggerBDB())

    # Test that unsupported command doesn't crash
    handlers.handle_debug_command({"command": "unsupportedCommand", "arguments": {}, "id": 1})
    # Should not raise exception


def test_handle_debug_command_with_response():
    """Test debug command handling that returns a response."""
    _s, _dbg = _session_with_debugger(DebuggerBDB())

    # Test that command with ID works without crashing
    handlers.handle_debug_command({"command": "initialize", "arguments": {}, "id": 1})
    # Should not raise exception


def test_handle_debug_command_exception():
    """Test debug command handling when handler raises exception."""
    _s, _dbg = _session_with_debugger(DummyDebugger())

    # Mock a handler to raise exception
    def failing_handler():
        raise ValueError("Test handler error")

    original_handler = lifecycle_handlers.handle_initialize_impl
    lifecycle_handlers.handle_initialize_impl = failing_handler

    try:
        # Test that exception handling doesn't crash
        handlers.handle_debug_command({"command": "initialize", "arguments": {}, "id": 1})
    except Exception:
        pass  # Expected to be handled internally

    # Restore original handler
    lifecycle_handlers.handle_initialize_impl = original_handler


def test_convert_value_with_context():
    """Test the _convert_value_with_context function."""
    # Test special values
    assert convert_value_with_context("None") is None
    assert convert_value_with_context("True") is True
    assert convert_value_with_context("False") is False

    # Test literal evaluation
    assert convert_value_with_context("42") == 42
    assert convert_value_with_context("3.14") == 3.14
    assert convert_value_with_context("'hello'") == "hello"
    assert convert_value_with_context("[1, 2, 3]") == [1, 2, 3]

    # Test with frame context
    frame = MockFrame(_locals={"x": 10}, _globals={"PI": 3.14159})

    result = convert_value_with_context("x * 2", frame)
    assert result == 20

    result = convert_value_with_context("PI", frame)
    assert result == 3.14159

    # Test with parent object for type inference
    parent_list = [1, 2, 3]
    result = convert_value_with_context("42", None, parent_list)
    assert result == 42  # Should convert to int to match list element type

    parent_dict = {"key": "value"}
    result = convert_value_with_context("new", None, parent_dict)
    assert result == "new"  # Should convert to str to match dict value type

    # Test fallback to string
    result = convert_value_with_context("invalid python code")
    assert result == "invalid python code"


def test_convert_string_to_value():
    """Test the legacy _convert_string_to_value function."""
    # This should align with convert_value_with_context behavior
    result = convert_value_with_context("42")
    assert result == 42

    result = convert_value_with_context("hello")
    assert result == "hello"


def test_extract_variables():
    """Test the extract_variables function."""
    variables = []

    # Test with dict
    test_dict = {"a": 1, "b": "hello"}
    command_handler_helpers.extract_variables(
        None,
        variables,
        test_dict,
        make_variable_fn=_make_variable,
    )
    assert len(variables) == 2
    assert any(v["name"] == "a" and v["value"] == "1" for v in variables)
    assert any(v["name"] == "b" and v["value"] == "'hello'" for v in variables)

    # Test with list
    variables = []
    test_list = ["item1", "item2"]
    command_handler_helpers.extract_variables(
        None,
        variables,
        test_list,
        make_variable_fn=_make_variable,
    )
    assert len(variables) == 2
    assert any(v["name"] == "0" for v in variables)
    assert any(v["name"] == "1" for v in variables)

    # Test with object
    variables = []
    test_obj = MockFrame()
    command_handler_helpers.extract_variables(
        None,
        variables,
        test_obj,
        make_variable_fn=_make_variable,
    )
    # Should extract public attributes (non-underscore)
    assert len(variables) > 0


def test_send_debug_message_requires_ipc():
    """Test send_debug_message requires IPC to be enabled."""
    s = _session()
    s.ipc_enabled = False

    # Should raise RuntimeError when IPC is not enabled
    with pytest.raises(RuntimeError, match="IPC is required"):
        debug_launcher.send_debug_message("test", data="value")


def test_send_debug_message_ipc_binary():
    """Test send_debug_message with binary IPC (the default mode)."""
    s = _session()
    s.ipc_enabled = True

    # Need a bytes-capable mock file that satisfies TextIOBase
    class MockBytesFile(io.TextIOBase):
        def __init__(self):
            super().__init__()
            self.written: list[bytes] = []
            self.flushed = False

        def write(self, data):
            self.written.append(data)
            return len(data)

        def flush(self) -> None:
            self.flushed = True

        def writable(self) -> bool:
            return True

    mock_wfile = MockBytesFile()
    s.ipc_wfile = mock_wfile

    debug_launcher.send_debug_message("test", data="value")

    # Should write binary frame to wfile
    assert len(mock_wfile.written) > 0
    assert mock_wfile.flushed is True
    # The frame should be bytes
    assert isinstance(mock_wfile.written[0], bytes)


def test_send_debug_message_ipc_pipe():
    """Test send_debug_message with IPC pipe connection."""
    s = _session()
    s.ipc_enabled = True
    s.ipc_binary = True

    # Create a simple mock pipe connection
    class MockConn:
        def __init__(self):
            self.sent = []

        def send_bytes(self, data):
            self.sent.append(data)

    mock_conn = MockConn()
    s.ipc_pipe_conn = mock_conn

    debug_launcher.send_debug_message("test", data="value")

    # Should send bytes through pipe
    assert len(mock_conn.sent) > 0


def test_handle_command_bytes():
    """Test _handle_command_bytes function."""
    s = _session()

    # Mock the queue
    class MockQueue(queue.Queue):
        def __init__(self):
            super().__init__()
            self.items = []

        def put(self, item, block=True, timeout=None):
            _ = block, timeout  # Unused parameters
            self.items.append(item)

    mock_queue = MockQueue()
    s.command_queue = mock_queue
    s.debugger = DummyDebugger()

    # Test valid command
    command_data = json.dumps({"command": "initialize", "arguments": {}}).encode("utf-8")

    debug_launcher._handle_command_bytes(command_data)

    # Should put command in queue
    assert len(mock_queue.items) > 0


def test_handle_command_bytes_invalid_json():
    """Test _handle_command_bytes with invalid JSON."""
    # Test that invalid JSON doesn't crash
    try:
        debug_launcher._handle_command_bytes(b"invalid json")
    except Exception:
        pass  # Expected to handle error gracefully
