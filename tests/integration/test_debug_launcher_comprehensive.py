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

import pytest

from dapper.launcher import debug_launcher
from dapper.shared import command_handlers as handlers
from dapper.shared import command_handlers as shared_handlers
from dapper.shared import debug_shared
from tests.dummy_debugger import DummyDebugger

if TYPE_CHECKING:
    from dapper.protocol.requests import FunctionBreakpoint, SetFunctionBreakpointsArguments


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


def setup_function(_func):
    """Reset singleton session state for each test.

    IPC is now mandatory, so we enable it with a mock file by default.
    """
    s = debug_shared.state
    s.debugger = None
    s.is_terminated = False
    s.ipc_enabled = True
    s.ipc_rfile = None
    s.ipc_wfile = MockWFile()  # Use mock file so IPC writes don't fail
    s.command_queue = queue.Queue()


def test_handle_set_breakpoints_success():
    """Test successful breakpoint setting with various conditions."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    # Test setting breakpoints with conditions
    arguments = {
        "source": {"path": "/test/file.py"},
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

    result = handlers.handle_set_breakpoints(dbg, arguments)

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

    # Verify breakpoints were recorded
    assert len(dbg.recorded) == 3
    assert dbg.recorded[0][2]["condition"] == "x > 5"
    assert dbg.recorded[0][2]["hit_condition"] == ">3"
    assert dbg.recorded[0][2]["log_message"] == "Hit breakpoint"


def test_handle_set_breakpoints_failure(monkeypatch):
    """Test breakpoint setting when debugger returns False."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    # Create a mock function that will replace set_break
    def mock_set_break(
        self,  # noqa: ARG001
        filename: str,  # noqa: ARG001
        lineno: int,  # noqa: ARG001
        temporary: bool = False,  # noqa: ARG001
        cond: Any | None = None,  # noqa: ARG001
        funcname: str | None = None,  # noqa: ARG001
    ) -> Any | None:
        # This mock always returns False to simulate a failed breakpoint set
        return False

    # Use monkeypatch to replace the method with proper binding
    monkeypatch.setattr(dbg, "set_break", mock_set_break.__get__(dbg, DummyDebugger))

    arguments = {"source": {"path": "/test/file.py"}, "breakpoints": [{"line": 10}]}

    result = handlers.handle_set_breakpoints(dbg, arguments)

    assert result is not None
    assert result["success"] is True
    breakpoints = result["body"]["breakpoints"]
    assert len(breakpoints) == 1
    assert breakpoints[0]["verified"] is False


def test_handle_set_breakpoints_exception_handling(monkeypatch):
    """Test graceful handling when set_break raises an exception."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    # Mock set_break to raise an exception using monkeypatch
    def mock_set_break(self, filename, lineno, temporary=False, cond=None, funcname=None):  # noqa: ARG001
        raise ValueError("Test error")

    monkeypatch.setattr(DummyDebugger, "set_break", mock_set_break.__get__(dbg, DummyDebugger))

    arguments = {"source": {"path": "/test/file.py"}, "breakpoints": [{"line": 10}]}

    result = handlers.handle_set_breakpoints(dbg, arguments)

    assert result is not None
    assert result["success"] is True
    breakpoints = result["body"]["breakpoints"]
    assert len(breakpoints) == 1
    assert breakpoints[0]["verified"] is False


def test_handle_set_function_breakpoints():
    """Test setting function breakpoints."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

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
            ]
        },
    )

    result = handlers.handle_set_function_breakpoints(dbg, arguments)

    assert result is not None
    assert result["success"] is True
    body = result["body"]
    assert "breakpoints" in body

    breakpoints = body["breakpoints"]
    assert len(breakpoints) == 3
    assert all(bp["verified"] is True for bp in breakpoints)

    # Verify function breakpoints were stored
    assert "test_func1" in dbg.function_breakpoints
    assert "test_func2" in dbg.function_breakpoints
    assert "test_func3" in dbg.function_breakpoints

    # Verify metadata was recorded
    meta1 = dbg.function_breakpoint_meta["test_func1"]
    assert meta1["condition"] == "x > 5"
    assert meta1["hitCondition"] == ">3"

    meta3 = dbg.function_breakpoint_meta["test_func3"]
    assert meta3["logMessage"] == "Function hit"


def test_handle_set_function_breakpoints_empty():
    """Test setting function breakpoints with empty list."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    # Add some existing breakpoints first
    dbg.function_breakpoints = ["old_func"]
    dbg.function_breakpoint_meta["old_func"] = {"condition": "old"}

    arguments: SetFunctionBreakpointsArguments = {"breakpoints": []}

    result = handlers.handle_set_function_breakpoints(dbg, arguments)

    assert result is not None
    assert result["success"] is True
    assert len(dbg.function_breakpoints) == 0
    assert len(dbg.function_breakpoint_meta) == 0


def test_handle_set_exception_breakpoints():
    """Test setting exception breakpoints."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    # Test with raised and uncaught filters
    arguments = {"filters": ["raised", "uncaught"]}

    result = handlers.handle_set_exception_breakpoints(dbg, arguments)

    assert result is not None
    assert result["success"] is True
    assert "body" in result
    body = result["body"]
    assert "breakpoints" in body

    breakpoints = body["breakpoints"]
    assert len(breakpoints) == 2
    assert all(bp["verified"] is True for bp in breakpoints)

    # Verify flags were set
    assert dbg.exception_breakpoints_raised is True
    assert dbg.exception_breakpoints_uncaught is True

    # Test with only raised filter
    arguments = {"filters": ["raised"]}
    result = handlers.handle_set_exception_breakpoints(dbg, arguments)

    assert dbg.exception_breakpoints_raised is True
    assert dbg.exception_breakpoints_uncaught is False


def test_handle_set_exception_breakpoints_invalid_filters():
    """Test exception breakpoints with invalid filter types."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    # Test with non-list filters
    arguments = {"filters": "invalid"}

    result = handlers.handle_set_exception_breakpoints(dbg, arguments)

    assert result is not None
    assert result["success"] is True
    assert "body" in result
    body = result["body"]
    assert "breakpoints" in body
    breakpoints = body["breakpoints"]
    assert len(breakpoints) == 0  # Should be empty list for invalid filters


def test_handle_set_exception_breakpoints_exception_handling():
    """Test graceful handling when setting exception flags fails."""
    s = debug_shared.state

    # Create a debugger that will fail when setting exception flags
    class FailingDebugger(DummyDebugger):
        def __init__(self, *args, **kwargs):
            # Set a flag to track initialization
            self._initialized = False
            # Initialize the parent class first
            super().__init__(*args, **kwargs)
            # Now set up our internal state for the exception flags
            self._exception_breakpoints_raised = False
            self._exception_breakpoints_uncaught = False
            # Mark initialization as complete
            self._initialized = True

        def __setattr__(self, name, value):
            # Allow setting attributes during initialization
            if not getattr(self, "_initialized", False):
                return object.__setattr__(self, name, value)

            # Intercept attribute setting for exception breakpoint flags
            if name in ("exception_breakpoints_raised", "exception_breakpoints_uncaught"):
                # Store the value in the internal attribute
                object.__setattr__(self, f"_{name}", value)
                # But still raise an error to simulate the failure
                raise AttributeError("Cannot set attribute")
            return object.__setattr__(self, name, value)

        def __getattribute__(self, name):
            # Provide access to the internal values for our exception flags
            if name in ("exception_breakpoints_raised", "exception_breakpoints_uncaught"):
                return object.__getattribute__(self, f"_{name}")
            return object.__getattribute__(self, name)

    failing_dbg = FailingDebugger()
    s.debugger = failing_dbg

    # Test with one filter that will cause an exception
    arguments = {"filters": ["raised"]}

    result = handlers.handle_set_exception_breakpoints(failing_dbg, arguments)

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
    empty_result = handlers.handle_set_exception_breakpoints(failing_dbg, {"filters": []})
    assert empty_result is not None
    assert empty_result["success"] is True
    assert "body" in empty_result
    body = empty_result["body"]
    assert "breakpoints" in body
    assert len(body["breakpoints"]) == 0


def test_handle_continue():
    """Test continue command handling."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    # Add a stopped thread
    thread_id = 123
    dbg.stopped_thread_ids.add(thread_id)

    arguments = {"threadId": thread_id}

    handlers.handle_continue(dbg, arguments)

    assert thread_id not in dbg.stopped_thread_ids
    assert dbg._continued is True


def test_handle_continue_multiple_threads():
    """Test continue with multiple stopped threads."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    # Add multiple stopped threads
    thread_id1 = 123
    thread_id2 = 456
    dbg.stopped_thread_ids.update([thread_id1, thread_id2])

    # Continue one thread
    handlers.handle_continue(dbg, {"threadId": thread_id1})

    assert thread_id1 not in dbg.stopped_thread_ids
    assert thread_id2 in dbg.stopped_thread_ids
    assert dbg._continued is False  # Should not continue yet

    # Continue second thread
    handlers.handle_continue(dbg, {"threadId": thread_id2})

    assert thread_id2 not in dbg.stopped_thread_ids
    assert dbg._continued is True  # Should continue now


def test_handle_step_commands():
    """Test step in/out/next commands."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    # Create a mock frame
    frame = MockFrame()
    dbg.current_frame = frame

    # Mock current thread ID
    current_thread_id = threading.get_ident()

    # Test step in
    handlers.handle_step_in(dbg, {"threadId": current_thread_id})
    assert dbg.stepping is True
    assert dbg._step is True

    # Reset
    dbg.stepping = False
    dbg._step = False

    # Test step over (next)
    handlers.handle_next(dbg, {"threadId": current_thread_id})
    assert dbg.stepping is True
    assert dbg._next is frame

    # Reset
    dbg.stepping = False
    dbg._next = None

    # Test step out
    handlers.handle_step_out(dbg, {"threadId": current_thread_id})
    assert dbg.stepping is True
    assert dbg._return is frame


def test_handle_pause():
    """Test pause command handling (currently no-op)."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    # Pause command should not raise exception even though it's not implemented
    handlers.handle_pause(dbg, {"threadId": 123})
    # No assertions needed - just verify no exception is raised


def test_handle_stack_trace():
    """Test stack trace command handling."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    # Create mock frames
    frame1 = {"id": 1, "name": "func1", "line": 10}
    frame2 = {"id": 2, "name": "func2", "line": 20}
    frame3 = {"id": 3, "name": "func3", "line": 30}

    thread_id = 123
    dbg.frames_by_thread[thread_id] = [frame1, frame2, frame3]

    # Test full stack trace
    handlers.handle_stack_trace(dbg, {"threadId": thread_id})

    # Test with startFrame and levels
    handlers.handle_stack_trace(dbg, {"threadId": thread_id, "startFrame": 1, "levels": 2})


def test_handle_stack_trace_pagination():
    """Test stack trace pagination with startFrame and levels."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    # Create many mock frames
    frames = [{"id": i, "name": f"func{i}", "line": i * 10} for i in range(1, 11)]
    thread_id = 123
    dbg.frames_by_thread[thread_id] = frames

    # Test pagination
    handlers.handle_stack_trace(dbg, {"threadId": thread_id, "startFrame": 2, "levels": 3})


def test_handle_variables_cached_list():
    """Test variables command with cached list."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    # Create cached variables list
    var_ref = 100
    cached_vars = [
        {"name": "x", "value": "1", "type": "int"},
        {"name": "y", "value": "hello", "type": "str"},
    ]
    dbg.var_refs[var_ref] = cached_vars

    handlers.handle_variables(dbg, {"variablesReference": var_ref})
    # Should not raise exception and should send message


def test_handle_variables_object_reference():
    """Test variables command with object reference."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    # Create object reference
    var_ref = 101
    test_obj = {"key1": "value1", "key2": 42}
    dbg.var_refs[var_ref] = ("object", test_obj)

    handlers.handle_variables(dbg, {"variablesReference": var_ref})
    # Should not raise exception and should send message


def test_handle_variables_scope_reference():
    """Test variables command with scope reference."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    # Create frame and scope reference
    frame_id = 1
    frame = MockFrame(
        _locals={"local_var": "local_value"}, _globals={"global_var": "global_value"}
    )
    dbg.frame_id_to_frame[frame_id] = frame

    var_ref = 102
    dbg.var_refs[var_ref] = (frame_id, "locals")

    handlers.handle_variables(dbg, {"variablesReference": var_ref})
    # Should not raise exception and should send message


def test_handle_variables_invalid_reference():
    """Test variables command with invalid reference."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    # Test with non-existent reference
    handlers.handle_variables(dbg, {"variablesReference": 999})
    # Should not raise exception

    # Test with invalid reference type
    var_ref = 103
    dbg.var_refs[var_ref] = "invalid_type"

    handlers.handle_variables(dbg, {"variablesReference": var_ref})
    # Should not raise exception


def test_handle_set_variable_object_member():
    """Test setting variable on object."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    # Create object reference
    var_ref = 104
    test_obj = {"existing_key": "old_value"}
    dbg.var_refs[var_ref] = ("object", test_obj)

    result = handlers.handle_set_variable(
        dbg, {"variablesReference": var_ref, "name": "existing_key", "value": "new_value"}
    )

    assert result is not None
    assert result["success"] is True
    assert test_obj["existing_key"] == "new_value"


def test_handle_set_variable_list_member():
    """Test setting variable in list."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    # Create list reference
    var_ref = 105
    test_list = ["item0", "item1", "item2"]
    dbg.var_refs[var_ref] = ("object", test_list)

    result = handlers.handle_set_variable(
        dbg, {"variablesReference": var_ref, "name": "1", "value": "new_item"}
    )

    assert result is not None
    assert result["success"] is True
    assert test_list[1] == "new_item"


def test_handle_set_variable_list_invalid_index():
    """Test setting variable with invalid list index."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    # Create list reference
    var_ref = 106
    test_list = ["item0", "item1"]
    dbg.var_refs[var_ref] = ("object", test_list)

    # Test invalid index
    result = handlers.handle_set_variable(
        dbg, {"variablesReference": var_ref, "name": "invalid", "value": "new_item"}
    )

    assert result is not None
    assert result["success"] is False
    assert "Invalid list index" in result["message"]

    # Test out of range index
    result = handlers.handle_set_variable(
        dbg, {"variablesReference": var_ref, "name": "5", "value": "new_item"}
    )

    assert result is not None
    assert result["success"] is False
    assert "out of range" in result["message"]


def test_handle_set_variable_tuple():
    """Test setting variable on tuple (should fail)."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    # Create tuple reference
    var_ref = 107
    test_tuple = ("item0", "item1")
    dbg.var_refs[var_ref] = ("object", test_tuple)

    result = handlers.handle_set_variable(
        dbg, {"variablesReference": var_ref, "name": "0", "value": "new_item"}
    )

    assert result is not None
    assert result["success"] is False
    assert "immutable" in result["message"]


def test_handle_set_variable_scope_variable():
    """Test setting variable in frame scope."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    # Create frame and scope reference
    frame_id = 2
    frame = MockFrame(_locals={"x": 1, "y": "old"})
    dbg.frame_id_to_frame[frame_id] = frame

    var_ref = 108
    dbg.var_refs[var_ref] = (frame_id, "locals")

    result = handlers.handle_set_variable(
        dbg, {"variablesReference": var_ref, "name": "y", "value": "new_value"}
    )

    assert result is not None
    assert result["success"] is True
    assert frame.f_locals["y"] == "new_value"


def test_handle_set_variable_invalid_reference():
    """Test setting variable with invalid reference."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    result = handlers.handle_set_variable(
        dbg, {"variablesReference": 999, "name": "x", "value": "value"}
    )

    assert result is not None
    assert result["success"] is False
    assert "Invalid variable reference" in result["message"]


def test_handle_evaluate():
    """Test evaluate command."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    # Create frame
    frame_id = 3
    frame = MockFrame(_locals={"x": 5, "y": 10}, _globals={"z": 15})
    dbg.frame_id_to_frame[frame_id] = frame

    # Test simple expression
    handlers.handle_evaluate(
        dbg, {"expression": "x + y", "frameId": frame_id, "context": "watch"}
    )

    # Test expression that creates variable reference
    handlers.handle_evaluate(
        dbg, {"expression": "{'a': 1}", "frameId": frame_id, "context": "watch"}
    )

    # Test expression with error
    handlers.handle_evaluate(
        dbg, {"expression": "undefined_var", "frameId": frame_id, "context": "watch"}
    )


def test_handle_evaluate_no_frame():
    """Test evaluate command without frame."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    handlers.handle_evaluate(dbg, {"expression": "1 + 1", "context": "watch"})
    # Should not raise exception


def test_handle_evaluate_invalid_expression():
    """Test evaluate command with invalid expression type."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    frame_id = 4
    frame = MockFrame()
    dbg.frame_id_to_frame[frame_id] = frame

    # Test with non-string expression
    try:
        handlers.handle_evaluate(
            dbg,
            {
                "expression": 123,  # Not a string
                "frameId": frame_id,
                "context": "watch",
            },
        )
        raise AssertionError("Should have raised TypeError")
    except TypeError:
        pass  # Expected


def test_handle_exception_info():
    """Test exception info command."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    # Create exception info
    thread_id = 123
    exception_info = {
        "exceptionId": "ValueError",
        "description": "Test error",
        "breakMode": "always",
        "details": {"stackTrace": "line1\nline2"},
    }
    dbg.current_exception_info[thread_id] = exception_info

    handlers.handle_exception_info(dbg, {"threadId": thread_id})
    # Should send exception info message

    # Test with missing threadId
    handlers.handle_exception_info(dbg, {})
    # Should send error message

    # Test with no debugger
    s.debugger = None
    handlers.handle_exception_info(dbg, {"threadId": thread_id})
    # Should send error message


def test_handle_configuration_done():
    """Test configuration done command."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    handlers.handle_configuration_done(dbg, {})
    # Should not raise exception and return None (no-op)


def test_handle_terminate():
    """Test terminate command."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    # Test that the command sets termination flag
    # Note: We can't test os._exit without actually exiting
    # Inject a test-friendly exit function so we don't kill the test runner.
    orig_exit = debug_shared.state.exit_func

    def fake_exit(code: int):
        raise SystemExit(code)

    debug_shared.state.set_exit_func(fake_exit)
    try:
        with pytest.raises(SystemExit):
            handlers.handle_terminate(dbg, {})

        assert s.is_terminated is True
    finally:
        # Restore original behavior
        debug_shared.state.set_exit_func(orig_exit)


def test_handle_restart():
    """Test restart command."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    # Override exec behavior so we don't replace the test process.
    orig_exec = debug_shared.state.exec_func

    def fake_exec(path: str, args: list[str]):
        # Signal via exception so test can assert restart was attempted
        raise SystemExit(("exec_called", path, tuple(args)))

    debug_shared.state.set_exec_func(fake_exec)
    try:
        with pytest.raises(SystemExit) as excinfo:
            handlers.handle_restart(dbg, {})

        # The exit code should be a tuple with our test data
        exit_code = excinfo.value.code
        assert isinstance(exit_code, tuple)
        assert len(exit_code) >= 1
        assert exit_code[0] == "exec_called"
    finally:
        debug_shared.state.set_exec_func(orig_exec)


def test_handle_threads_with_data():
    """Test threads command with actual thread data."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    # Add thread data
    dbg.threads = {1: "MainThread", 2: "WorkerThread"}

    result = handlers.handle_threads(dbg, {})

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
    s = debug_shared.state
    s.debugger = None

    # Command should be queued without error
    handlers.handle_debug_command({"command": "initialize", "arguments": {}})

    # Should not raise exception


def test_handle_debug_command_unsupported():
    """Test debug command handling for unsupported commands."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    # Test that unsupported command doesn't crash
    handlers.handle_debug_command(
        {"command": "unsupportedCommand", "arguments": {}, "id": 1}
    )
    # Should not raise exception


def test_handle_debug_command_with_response():
    """Test debug command handling that returns a response."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    # Test that command with ID works without crashing
    handlers.handle_debug_command({"command": "initialize", "arguments": {}, "id": 1})
    # Should not raise exception


def test_handle_debug_command_exception():
    """Test debug command handling when handler raises exception."""
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    # Mock a handler to raise exception
    def failing_handler(_dbg, _args):
        raise ValueError("Test handler error")

    original_handler = handlers.handle_initialize
    handlers.handle_initialize = failing_handler

    try:
        # Test that exception handling doesn't crash
        handlers.handle_debug_command({"command": "initialize", "arguments": {}, "id": 1})
    except Exception:
        pass  # Expected to be handled internally

    # Restore original handler
    handlers.handle_initialize = original_handler


def test_convert_value_with_context():
    """Test the _convert_value_with_context function."""
    # Test special values
    assert shared_handlers._convert_value_with_context("None") is None
    assert shared_handlers._convert_value_with_context("True") is True
    assert shared_handlers._convert_value_with_context("False") is False

    # Test literal evaluation
    assert shared_handlers._convert_value_with_context("42") == 42
    assert shared_handlers._convert_value_with_context("3.14") == 3.14
    assert shared_handlers._convert_value_with_context("'hello'") == "hello"
    assert shared_handlers._convert_value_with_context("[1, 2, 3]") == [1, 2, 3]

    # Test with frame context
    frame = MockFrame(_locals={"x": 10}, _globals={"PI": 3.14159})

    result = shared_handlers._convert_value_with_context("x * 2", frame)
    assert result == 20

    result = shared_handlers._convert_value_with_context("PI", frame)
    assert result == 3.14159

    # Test with parent object for type inference
    parent_list = [1, 2, 3]
    result = shared_handlers._convert_value_with_context("42", None, parent_list)
    assert result == 42  # Should convert to int to match list element type

    parent_dict = {"key": "value"}
    result = shared_handlers._convert_value_with_context("new", None, parent_dict)
    assert result == "new"  # Should convert to str to match dict value type

    # Test fallback to string
    result = shared_handlers._convert_value_with_context("invalid python code")
    assert result == "invalid python code"


def test_convert_string_to_value():
    """Test the legacy _convert_string_to_value function."""
    # This should delegate to _convert_value_with_context
    result = shared_handlers._convert_string_to_value("42")
    assert result == 42

    result = shared_handlers._convert_string_to_value("hello")
    assert result == "hello"


def test_extract_variables():
    """Test the extract_variables function."""
    variables = []

    # Test with dict
    test_dict = {"a": 1, "b": "hello"}
    handlers.extract_variables(None, variables, test_dict)
    assert len(variables) == 2
    assert any(v["name"] == "a" and v["value"] == "1" for v in variables)
    assert any(v["name"] == "b" and v["value"] == "'hello'" for v in variables)

    # Test with list
    variables = []
    test_list = ["item1", "item2"]
    handlers.extract_variables(None, variables, test_list)
    assert len(variables) == 2
    assert any(v["name"] == "0" for v in variables)
    assert any(v["name"] == "1" for v in variables)

    # Test with object
    variables = []
    test_obj = MockFrame()
    handlers.extract_variables(None, variables, test_obj)
    # Should extract public attributes (non-underscore)
    assert len(variables) > 0


def test_send_debug_message_requires_ipc():
    """Test send_debug_message requires IPC to be enabled."""
    s = debug_shared.state
    s.ipc_enabled = False

    # Should raise RuntimeError when IPC is not enabled
    with pytest.raises(RuntimeError, match="IPC is required"):
        debug_launcher.send_debug_message("test", data="value")


def test_send_debug_message_ipc_binary():
    """Test send_debug_message with binary IPC (the default mode)."""
    s = debug_shared.state
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
    s = debug_shared.state
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
    s = debug_shared.state

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
