"""Pytest-style tests for the PyDebugger class.

Converted from unittest.IsolatedAsyncioTestCase to pytest async functions.
"""

from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path
from typing import TypedDict
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

# Add project root to Python path for local imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Import protocol types for type checking

# Type definitions for test mocks
class Source(TypedDict):
    """Mock Source type for testing."""
    path: str
    name: str | None


class SourceBreakpoint(TypedDict, total=False):
    """Mock SourceBreakpoint type for testing."""
    line: int
    condition: str | None
    hitCondition: str | None
    column: int | None
    logMessage: str | None


class FunctionBreakpoint(TypedDict, total=False):
    """Mock FunctionBreakpoint type for testing."""
    name: str
    condition: str | None
    hitCondition: str | None


class BreakpointResponse(TypedDict, total=False):
    """Mock BreakpointResponse type for testing."""
    verified: bool
    line: int | None
    condition: str | None
    hitCondition: str | None
    message: str | None
    source: dict[str, str] | None


# Constants for testing
from dapper.constants import DEFAULT_BREAKPOINT_CONDITION_VALUE
from dapper.constants import DEFAULT_BREAKPOINT_LINE
from dapper.constants import TEST_ALT_LINE_1
from dapper.server import PyDebugger
from dapper.server import PyDebuggerThread

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_server():
    """Create a mock server for testing."""
    server = MagicMock()

    class AsyncRecorder:
        """Minimal async callable that records calls and provides
        basic assert helpers used by tests."""

        def __init__(self):
            self.calls = []

        class _CompletedAwaitable:
            """Small awaitable that only creates an internal coroutine when
            actually awaited. This prevents creating coroutine objects that
            may never be awaited (which triggers RuntimeWarnings).
            """

            def __init__(self, result=None):
                self._result = result

            def __await__(self):
                async def _c():
                    return self._result

                return _c().__await__()

        def __call__(self, *args, **kwargs):
            # Record the call immediately so synchronous test code
            # that invokes the handler can assert against calls.
            self.calls.append((args, kwargs))

            # Return a lightweight awaitable that won't create a coroutine
            # until it's awaited.
            return AsyncRecorder._CompletedAwaitable()

        def assert_called_with(self, *args, **kwargs):
            assert self.calls
            assert self.calls[-1] == (args, kwargs)

        def assert_called_once_with(self, *args, **kwargs):
            assert len(self.calls) == 1
            assert self.calls[0] == (args, kwargs)

        def assert_any_call(self, *args, **kwargs):
            assert (args, kwargs) in self.calls

        def assert_not_called(self):
            assert not self.calls

    server.send_event = AsyncRecorder()
    return server


@pytest.fixture
def debugger(mock_server, event_loop):
    """Create a PyDebugger instance for testing."""
    return PyDebugger(mock_server, event_loop)


# ---------------------------------------------------------------------------
# Initialization and Shutdown Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initialization(debugger, mock_server):
    """Test that the debugger initializes correctly"""
    assert debugger is not None
    assert debugger.server == mock_server
    assert debugger.process is None


@pytest.mark.asyncio
async def test_shutdown(debugger):
    """Test the shutdown process of the debugger"""
    # Add some test data
    debugger.breakpoints["test.py"] = [{"line": 1}]
    debugger.function_breakpoints = [{"name": "test"}]
    debugger.threads[1] = MagicMock()
    debugger.var_refs[1] = "test"
    debugger.current_stack_frames[1] = [{"id": 1}]

    await debugger.shutdown()

    # Check that data structures are cleared
    assert len(debugger.breakpoints) == 0
    assert len(debugger.function_breakpoints) == 0
    assert len(debugger.threads) == 0
    assert len(debugger.var_refs) == 0
    assert len(debugger.current_stack_frames) == 0


@pytest.mark.asyncio
async def test_shutdown_fails_pending_commands(debugger):
    """Pending command futures should be failed when shutdown is called."""
    # Prepare a pending command future created on the debugger's loop
    loop = asyncio.get_running_loop()
    cmd_id = 12345
    fut = loop.create_future()

    # Inject into the debugger pending map
    debugger._pending_commands[cmd_id] = fut

    # Call shutdown
    await debugger.shutdown()

    # Allow loop callbacks to run
    await asyncio.sleep(0)

    # The future should be done and have an exception
    assert fut.done()
    with pytest.raises(RuntimeError):
        fut.result()


# ---------------------------------------------------------------------------
# Launch and Process Management Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_launch_success(debugger, mock_server):
    """Test successful launch of a debuggee process"""
    mock_process = MagicMock()
    # Provide an actual awaitable wait method instead of a MagicMock that
    # returns a plain value. This prevents creation of unawaited coroutine
    # warnings when the production code awaits process.wait().

    # Provide a synchronous wait() returning 0 because in test mode
    # the debugger starts the process in a background thread and calls
    # process.wait() directly; supplying an async def here would create
    # an un-awaited coroutine object in that thread.
    def _fake_wait_sync():
        return 0

    mock_process.wait = _fake_wait_sync
    mock_process.pid = 12345

    # Mock stdout and stderr to behave like file objects
    mock_process.stdout = MagicMock()
    mock_process.stderr = MagicMock()

    # Configure readline to return empty strings to stop reading
    mock_process.stdout.readline.return_value = ""
    mock_process.stderr.readline.return_value = ""

    # Mock the _start_debuggee_process method to avoid run_in_executor issues
    debugger._test_mode = True
    with patch("subprocess.Popen", return_value=mock_process) as mock_popen:
        await debugger.launch("test_program.py", [], stop_on_entry=False, no_debug=False)

    mock_popen.assert_called_once()

    assert debugger.process == mock_process
    # Check that process event was sent (not terminated)
    mock_server.send_event.assert_any_call(
        "process",
        {
            "name": "test_program.py",
            "systemProcessId": mock_process.pid,
            "isLocalProcess": True,
            "startMethod": "launch",
        },
    )


@pytest.mark.asyncio
async def test_shutdown_fails_pending_commands_cross_loop(debugger):
    """If a pending Future was created on a different loop (running in
    another thread), shutdown should still cause it to finish with an
    exception. This exercises the cross-loop scheduling path.
    """
    # Create a new event loop running in a background thread
    other_loop_ready = threading.Event()

    def _loop_thread_fn(loop, ready_evt):
        asyncio.set_event_loop(loop)
        ready_evt.set()
        loop.run_forever()

    other_loop = asyncio.new_event_loop()
    thread = threading.Thread(
        target=_loop_thread_fn,
        args=(other_loop, other_loop_ready),
        daemon=True,
    )
    thread.start()

    # Wait for the other loop to be ready
    other_loop_ready.wait(timeout=1.0)

    # Create an asyncio.Future on the other loop by scheduling a small
    # coroutine that returns a fresh future.
    async def _make_future():
        return other_loop.create_future()

    fut_async = asyncio.run_coroutine_threadsafe(_make_future(), other_loop).result()

    # Mark the future as pending by not completing it; inject into pending
    cmd_id = 99999
    debugger._pending_commands[cmd_id] = fut_async

    # Call shutdown on the debugger
    await debugger.shutdown()

    # Allow callbacks to run
    await asyncio.sleep(0)

    # The future should be done and have an exception
    assert fut_async.done()
    # Attempting to get the result should raise the RuntimeError we set
    with pytest.raises(RuntimeError):
        # Use result() from the other loop by scheduling a coroutine that
        # reads the future's result; but since the future is already done
        # we can call result() directly.
        fut_async.result()

    # Clean up the other loop
    other_loop.call_soon_threadsafe(other_loop.stop)
    thread.join(timeout=1.0)
    try:
        other_loop.close()
    except Exception:
        pass


@pytest.mark.asyncio
async def test_launch_already_running_error(debugger):
    """Test launching when already running raises error"""
    debugger.process = MagicMock()
    debugger.program_running = True

    with pytest.raises(RuntimeError) as exc_info:
        await debugger.launch("test.py", [])

    assert "already being debugged" in str(exc_info.value)


@pytest.mark.asyncio
async def test_launch_with_args(debugger):
    """Test launching with command line arguments"""
    mock_process = MagicMock()
    mock_process.wait.return_value = 0
    mock_process.pid = 12345
    mock_process.stdout = MagicMock()
    mock_process.stderr = MagicMock()
    mock_process.stdout.readline.return_value = ""
    mock_process.stderr.readline.return_value = ""

    args = ["arg1", "arg2"]
    debugger._test_mode = True
    try:
        with patch("subprocess.Popen", return_value=mock_process) as mock_popen:
            await debugger.launch("test_program.py", args, stop_on_entry=False, no_debug=False)
            # Wait a tiny bit to allow run_coroutine_threadsafe to enqueue exit task
            await asyncio.sleep(0.05)

        call_args = mock_popen.call_args
        assert "test_program.py" in str(call_args[0][0])
        assert "arg1" in str(call_args[0][0])
        assert "arg2" in str(call_args[0][0])
    finally:
        await debugger.shutdown()


# ---------------------------------------------------------------------------
# Execution Control Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pause(debugger):
    """Test pausing the debugger"""
    debugger.process = MagicMock()
    debugger.process.stdin = MagicMock()
    debugger.program_running = True
    debugger.is_terminated = False

    await debugger.pause(thread_id=1)

    # Check that a command was written to stdin
    debugger.process.stdin.write.assert_called_once()
    call_args = debugger.process.stdin.write.call_args[0][0]
    assert "pause" in call_args
    assert "threadId" in call_args


@pytest.mark.asyncio
async def test_continue_execution(debugger):
    """Test continuing execution"""
    debugger.process = MagicMock()
    debugger.process.stdin = MagicMock()
    debugger.program_running = True
    debugger.is_terminated = False
    debugger.stopped_event.set()

    await debugger.continue_execution(thread_id=1)

    # Check that a command was written to stdin
    debugger.process.stdin.write.assert_called_once()
    call_args = debugger.process.stdin.write.call_args[0][0]
    assert "continue" in call_args
    assert "threadId" in call_args


@pytest.mark.asyncio
async def test_continue_execution_not_running(debugger):
    """Test continuing when not running"""
    debugger.program_running = False

    result = await debugger.continue_execution(thread_id=1)

    assert result == {"allThreadsContinued": False}


@pytest.mark.asyncio
async def test_continue_execution_terminated(debugger):
    """Test continuing when terminated"""
    debugger.program_running = True
    debugger.is_terminated = True

    result = await debugger.continue_execution(thread_id=1)

    assert result == {"allThreadsContinued": False}


@pytest.mark.asyncio
async def test_continue_execution_clears_stopped_event(debugger):
    """Test that continue clears the stopped event"""
    debugger.process = MagicMock()
    debugger.process.stdin = MagicMock()
    debugger.program_running = True
    debugger.is_terminated = False
    debugger.stopped_event.set()

    # Verify event is set initially
    assert debugger.stopped_event.is_set()

    await debugger.continue_execution(thread_id=1)

    # Verify event is cleared
    assert not debugger.stopped_event.is_set()


@pytest.mark.asyncio
async def test_next_step(debugger):
    """Test stepping to next line"""
    debugger.process = MagicMock()
    debugger.process.stdin = MagicMock()
    debugger.program_running = True
    debugger.is_terminated = False

    await debugger.next(thread_id=1)

    debugger.process.stdin.write.assert_called_once()
    call_args = debugger.process.stdin.write.call_args[0][0]
    assert "next" in call_args
    assert "threadId" in call_args


@pytest.mark.asyncio
async def test_step_in(debugger):
    """Test stepping into function"""
    debugger.process = MagicMock()
    debugger.process.stdin = MagicMock()
    debugger.program_running = True
    debugger.is_terminated = False

    await debugger.step_in(thread_id=1)

    debugger.process.stdin.write.assert_called_once()
    call_args = debugger.process.stdin.write.call_args[0][0]
    assert "step" in call_args
    assert "threadId" in call_args


@pytest.mark.asyncio
async def test_step_out(debugger):
    """Test stepping out of function"""
    debugger.process = MagicMock()
    debugger.process.stdin = MagicMock()
    debugger.program_running = True
    debugger.is_terminated = False

    await debugger.step_out(thread_id=1)

    debugger.process.stdin.write.assert_called_once()
    call_args = debugger.process.stdin.write.call_args[0][0]
    assert "stepOut" in call_args
    assert "threadId" in call_args


# ---------------------------------------------------------------------------
# Breakpoint Management Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_breakpoints(debugger: PyDebugger) -> None:
    """Test setting breakpoints in a source file."""
    # Create source using a simple dict that matches the expected structure
    source = {
        "path": "/path/to/test.py"
    }
    
    # Create breakpoints using dicts that match the expected structure
    breakpoint1: SourceBreakpoint = {
        "line": DEFAULT_BREAKPOINT_LINE,
        "condition": f"x > {DEFAULT_BREAKPOINT_CONDITION_VALUE}",
        "column": 1,  # 1-based column number
        "hitCondition": ""
    }
    breakpoint2: SourceBreakpoint = {
        "line": TEST_ALT_LINE_1,
        "condition": "",
        "column": 1,
        "hitCondition": ""
    }
    breakpoints: list[SourceBreakpoint] = [breakpoint1, breakpoint2]

    # Call set_breakpoints directly - no need to patch _create_breakpoint
    result = await debugger.set_breakpoints(source, breakpoints)
    
    # Check that breakpoints were stored
    expected_path = str(Path("/path/to/test.py").resolve())
    assert expected_path in debugger.breakpoints
    assert len(debugger.breakpoints[expected_path]) == 2

    # Check breakpoint properties using dictionary access for TypedDict
    bp1 = debugger.breakpoints[expected_path][0]
    assert bp1["line"] == DEFAULT_BREAKPOINT_LINE
    assert bp1["condition"] == f"x > {DEFAULT_BREAKPOINT_CONDITION_VALUE}"
    assert bp1["verified"] is True

    bp2 = debugger.breakpoints[expected_path][1]
    assert bp2["line"] == TEST_ALT_LINE_1
    assert bp2["verified"] is True

    # Check return value structure
    assert isinstance(result, list)
    assert len(result) == 2
    assert all(isinstance(bp, dict) for bp in result)
    assert all(isinstance(bp.get("verified"), bool) for bp in result)


@pytest.mark.asyncio
async def test_set_breakpoints_no_path(debugger):
    """Test setting breakpoints without path"""
    source = {}
    breakpoints = [{"line": 10}]

    result = await debugger.set_breakpoints(source, breakpoints)

    # Should return error when no path
    assert len(result) == 1
    assert result[0]["verified"] is False
    assert "Source path is required" in result[0]["message"]


@pytest.mark.asyncio
async def test_set_breakpoints_with_valid_path(debugger):
    """Test setting breakpoints with valid path"""
    source = {"path": "/valid/path/test.py"}
    breakpoints = [{"line": 5}, {"line": 15}]

    result = await debugger.set_breakpoints(source, breakpoints)

    assert len(result) == 2
    assert result[0]["verified"] is True
    assert result[1]["verified"] is True
    expected_path = str(Path("/valid/path/test.py").resolve())
    assert expected_path in debugger.breakpoints


@pytest.mark.asyncio
async def test_set_function_breakpoints(debugger):
    """Test setting function breakpoints"""
    breakpoints = [
        FunctionBreakpoint(name="main"),
        FunctionBreakpoint(
            name="helper", 
            condition=f"x > {DEFAULT_BREAKPOINT_CONDITION_VALUE - 5}"
        )
    ]

    result = await debugger.set_function_breakpoints(breakpoints)

    assert len(result) == 2
    assert result[0]["verified"] is True
    assert result[1]["verified"] is True


@pytest.mark.asyncio
async def test_set_exception_breakpoints(debugger):
    """Test setting exception breakpoints"""
    filters = ["RuntimeError", "ValueError"]

    result = await debugger.set_exception_breakpoints(filters)

    assert len(result) == 2
    assert result[0]["verified"] is True
    assert result[1]["verified"] is True


# ---------------------------------------------------------------------------
# Thread and Stack Frame Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_py_debugger_thread_initialization():
    """Test PyDebuggerThread initialization"""
    thread = PyDebuggerThread(1, "MainThread")

    assert thread.id == 1
    assert thread.name == "MainThread"
    assert thread.frames == []
    assert thread.is_stopped is False


@pytest.mark.asyncio
async def test_get_threads(debugger):
    """Test getting thread information"""
    # Add some mock threads
    thread1 = MagicMock()
    thread1.thread_id = 1
    thread1.name = "MainThread"

    thread2 = MagicMock()
    thread2.thread_id = 2
    thread2.name = "WorkerThread"

    debugger.threads = {1: thread1, 2: thread2}

    result = await debugger.get_threads()

    assert len(result) == 2
    assert result[0]["id"] == 1
    assert result[0]["name"] == "MainThread"
    assert result[1]["id"] == 2
    assert result[1]["name"] == "WorkerThread"


@pytest.mark.asyncio
async def test_thread_stopped_state():
    """Test thread stopped state management"""
    thread = PyDebuggerThread(1, "MainThread")

    # Initially not stopped
    assert not thread.is_stopped

    # Set stopped
    thread.is_stopped = True
    assert thread.is_stopped

    # Clear stopped
    thread.is_stopped = False
    assert not thread.is_stopped


@pytest.mark.asyncio
async def test_get_stack_trace(debugger):
    """Test getting stack trace"""
    # Add mock thread and stack frames
    thread = PyDebuggerThread(1, "MainThread")
    debugger.threads = {1: thread}
    debugger.current_stack_frames = {
        1: [
            {"id": 1, "name": "main", "line": 10, "column": 1},
            {"id": 2, "name": "helper", "line": 5, "column": 1},
        ]
    }

    result = await debugger.get_stack_trace(thread_id=1, start_frame=0, levels=20)

    assert "stackFrames" in result
    assert "totalFrames" in result
    assert len(result["stackFrames"]) == 2
    assert result["totalFrames"] == 2


# ---------------------------------------------------------------------------
# Variable Management Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_scopes(debugger):
    """Test getting scopes for a frame"""
    # Add mock thread with frames
    thread = PyDebuggerThread(1, "MainThread")
    thread.frames = [{"id": 1, "name": "main", "line": 10}]
    debugger.threads = {1: thread}

    result = await debugger.get_scopes(frame_id=1)

    assert len(result) == 2  # Local and Global scopes
    assert result[0]["name"] == "Local"
    assert result[1]["name"] == "Global"


@pytest.mark.asyncio
async def test_get_variables(debugger):
    """Test getting variables from a scope"""
    # Mock the variable reference
    debugger.var_refs[1001] = [
        {"name": "x", "value": "42", "type": "int"},
        {"name": "y", "value": "hello", "type": "str"},
    ]

    result = await debugger.get_variables(1001, filter_type="named", start=0, count=100)

    assert len(result) == 2
    assert result[0]["name"] == "x"
    assert result[0]["value"] == "42"
    assert result[1]["name"] == "y"
    assert result[1]["value"] == "hello"


@pytest.mark.asyncio
async def test_evaluate_expression(debugger):
    """Test evaluating an expression"""
    # Mock the frame and thread
    thread = PyDebuggerThread(1, "MainThread")
    thread.frames = [{"id": 1, "name": "main", "line": 10}]
    debugger.threads = {1: thread}

    result = await debugger.evaluate_expression("x + 1", frame_id=1, context="watch")

    # Should return a result dict
    assert isinstance(result, dict)
    assert "result" in result
    assert "type" in result


# ---------------------------------------------------------------------------
# Event Handling Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_debug_message_stopped_event(debugger, mock_server):
    """Test handling stopped event from debuggee"""
    message = {
        "type": "event",
        "event": "stopped",
        "body": {
            "reason": "breakpoint",
            "threadId": 1,
            "allThreadsStopped": True,
        },
    }

    await debugger.handle_debug_message(message)

    # Check that stopped event was set
    assert debugger.stopped_event.is_set()

    # Check that server event was sent
    mock_server.send_event.assert_called_with(
        "stopped",
        {"reason": "breakpoint", "threadId": 1, "allThreadsStopped": True},
    )


@pytest.mark.asyncio
async def test_handle_debug_message_thread_started(debugger, mock_server):
    """Test handling thread started event"""
    message = {"event": "thread", "reason": "started", "threadId": 2}

    await debugger.handle_debug_message(message)

    # Check that thread was added
    assert 2 in debugger.threads
    assert isinstance(debugger.threads[2], PyDebuggerThread)

    # Check that server event was sent
    mock_server.send_event.assert_called_with("thread", {"reason": "started", "threadId": 2})


@pytest.mark.asyncio
async def test_handle_debug_message_thread_exited(debugger, mock_server):
    """Test handling thread exited event"""
    # Add a thread first
    debugger.threads[1] = PyDebuggerThread(1, "MainThread")

    message = {"event": "thread", "reason": "exited", "threadId": 1}

    await debugger.handle_debug_message(message)

    # Check that thread was removed
    assert 1 not in debugger.threads

    # Check that server event was sent
    mock_server.send_event.assert_called_with("thread", {"reason": "exited", "threadId": 1})


@pytest.mark.asyncio
async def test_handle_debug_message_exited_event(debugger):
    """Test handling process exited event"""
    message = {"event": "exited", "exitCode": 0}

    await debugger.handle_debug_message(message)

    # Allow the event loop to process the coroutine
    await asyncio.sleep(0.01)

    # Check that terminated flag was set
    assert debugger.is_terminated


@pytest.mark.asyncio
async def test_handle_debug_message_stack_trace_event(debugger):
    """Test handling stack trace event"""
    message = {
        "event": "stackTrace",
        "threadId": 1,
        "stackFrames": [
            {"id": 1, "name": "main", "line": 10},
            {"id": 2, "name": "helper", "line": 5},
        ],
    }

    await debugger.handle_debug_message(message)

    # Check that stack frames were stored
    assert 1 in debugger.current_stack_frames
    assert len(debugger.current_stack_frames[1]) == 2


@pytest.mark.asyncio
async def test_handle_debug_message_variables_event(debugger):
    """Test handling variables event"""
    message = {
        "type": "event",
        "event": "variables",
        "variablesReference": 1001,
        "variables": [
            {"name": "x", "value": "42"},
            {"name": "y", "value": "hello"},
        ],
    }

    await debugger.handle_debug_message(message)

    # Check that variables were stored
    assert 1001 in debugger.var_refs
    assert len(debugger.var_refs[1001]) == 2


@pytest.mark.asyncio
async def test_handle_debug_message_invalid_json(debugger):
    """Test handling invalid JSON message"""
    # Missing closing brace
    invalid_json = '{"type": "event", "event": "stopped"'

    # Should not raise exception
    await debugger.handle_debug_message(invalid_json)


@pytest.mark.asyncio
async def test_handle_debug_message_unknown_event(debugger):
    """Test handling unknown event type"""
    message = {"type": "event", "event": "unknown_event", "body": {}}

    # Should not raise exception
    await debugger.handle_debug_message(message)


@pytest.mark.asyncio
async def test_handle_program_exit(debugger):
    """Test handling program exit"""
    debugger.process = MagicMock()
    debugger.process.returncode = 0
    debugger.program_running = True

    await debugger.handle_program_exit(0)

    # Check that terminated flag was set
    assert debugger.is_terminated
    assert not debugger.program_running


# ---------------------------------------------------------------------------
# Command Sending Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_command_to_debuggee_no_process(debugger):
    """Test sending command when no process exists"""
    debugger.process = None

    with pytest.raises(RuntimeError) as exc_info:
        await debugger.send_command_to_debuggee("test_command")

    assert "No debuggee process" in str(exc_info.value)


@pytest.mark.asyncio
async def test_send_command_to_debuggee_terminated(debugger):
    """Test sending command when process is terminated"""
    debugger.process = MagicMock()
    debugger.is_terminated = True

    with pytest.raises(RuntimeError) as exc_info:
        await debugger.send_command_to_debuggee("test_command")

    assert "No debuggee process" in str(exc_info.value)


@pytest.mark.asyncio
async def test_terminate_functionality(debugger):
    """Test terminating the debugger"""
    debugger.process = MagicMock()
    debugger.program_running = True

    await debugger.terminate()

    # Check that process terminate was called
    debugger.process.terminate.assert_called_once()
    assert not debugger.program_running


@pytest.mark.asyncio
async def test_terminate_when_not_running(debugger):
    """Test terminating when not running"""
    debugger.program_running = False

    # Should not raise exception
    await debugger.terminate()


@pytest.mark.asyncio
async def test_terminate_without_process(debugger):
    """Test terminating without a process"""
    debugger.process = None
    debugger.program_running = True

    # Should not raise exception
    await debugger.terminate()
