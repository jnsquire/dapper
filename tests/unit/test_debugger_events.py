import asyncio
import unittest

from dapper.server import PyDebugger
from dapper.server import PyDebuggerThread

from .test_debugger_base import BaseDebuggerTest


# Run the loop to allow the scheduled event to be sent
def _run_loop_once(debugger: PyDebugger):
    debugger.loop.run_until_complete(asyncio.sleep(0))


class AsyncRecorder:
    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        # Record call synchronously so tests that call handlers
        # synchronously can assert immediately.
        self.calls.append((args, kwargs))

        async def _noop():
            return None

        return _noop()

    def assert_called_once_with(self, *args, **kwargs):
        assert len(self.calls) == 1
        assert self.calls[0] == (args, kwargs)

    def assert_not_called(self):
        assert not self.calls

    def assert_any_call(self, *args, **kwargs):
        assert (args, kwargs) in self.calls


class TestDebuggerEvents(BaseDebuggerTest):
    """

import sys
from pathlib import Path

# Add the project root to the Python path
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

Test cases for debugger debug message event handling"""

    def test_handle_debug_message_output_event(self):
        """Test handling output event"""
        self.debugger.server.send_event = AsyncRecorder()

        message = '{"event": "output", "category": "stdout", "output": "Hello World\\n"}'
        self.debugger._handle_debug_message(message)

        # Run the loop to allow the scheduled event to be sent
        self.debugger.loop.run_until_complete(asyncio.sleep(0))

        # Check that output event was sent
        self.debugger.server.send_event.assert_called_once_with(
            "output",
            {
                "category": "stdout",
                "output": "Hello World\n",
                "source": None,
                "line": None,
                "column": None,
            },
        )

    def test_handle_debug_message_continued_event(self):
        """Test handling continued event"""
        self.debugger.server.send_event = AsyncRecorder()

        message = '{"event": "continued", "threadId": 1, "allThreadsContinued": true}'
        self.debugger._handle_debug_message(message)

        _run_loop_once(self.debugger)

        # Check that continued event was sent
        self.debugger.server.send_event.assert_called_once_with(
            "continued", {"threadId": 1, "allThreadsContinued": True}
        )

    def test_handle_debug_message_exception_event(self):
        """Test handling exception event"""
        self.debugger.server.send_event = AsyncRecorder()

        message = (
            '{"event": "exception", "exceptionId": "ValueError", '
            '"description": "Invalid value", "threadId": 1}'
        )
        self.debugger._handle_debug_message(message)

        _run_loop_once(self.debugger)

        # Check that exception event was sent
        self.debugger.server.send_event.assert_called_once_with(
            "exception",
            {
                "exceptionId": "ValueError",
                "description": "Invalid value",
                "breakMode": "always",
                "threadId": 1,
            },
        )

    def test_handle_debug_message_breakpoint_event(self):
        """Test handling breakpoint event"""
        self.debugger.server.send_event = AsyncRecorder()

        message = (
            '{"event": "breakpoint", "reason": "changed", '
            '"breakpoint": {"id": 1, "verified": true, "line": 10}}'
        )
        self.debugger._handle_debug_message(message)
        _run_loop_once(self.debugger)

        # Check that breakpoint event was sent
        self.debugger.server.send_event.assert_called_once_with(
            "breakpoint",
            {
                "reason": "changed",
                "breakpoint": {"id": 1, "verified": True, "line": 10},
            },
        )

    def test_handle_debug_message_module_event(self):
        """Test handling module event"""
        self.debugger.server.send_event = AsyncRecorder()

        message = (
            '{"event": "module", "reason": "new", '
            '"module": {"id": "test_module", "name": "test", '
            '"path": "/path/to/test.py"}}'
        )
        self.debugger._handle_debug_message(message)
        _run_loop_once(self.debugger)

        # Check that module event was sent
        self.debugger.server.send_event.assert_called_once_with(
            "module",
            {
                "reason": "new",
                "module": {
                    "id": "test_module",
                    "name": "test",
                    "path": "/path/to/test.py",
                },
            },
        )

    def test_handle_debug_message_process_event(self):
        """Test handling process event"""
        self.debugger.server.send_event = AsyncRecorder()

        message = (
            '{"event": "process", "name": "test_process", '
            '"systemProcessId": 1234, "isLocalProcess": true}'
        )
        self.debugger._handle_debug_message(message)
        _run_loop_once(self.debugger)

        # Check that process event was sent
        self.debugger.server.send_event.assert_called_once_with(
            "process",
            {
                "name": "test_process",
                "systemProcessId": 1234,
                "isLocalProcess": True,
                "startMethod": "launch",
            },
        )

    def test_handle_debug_message_loaded_source_event(self):
        """Test handling loadedSource event"""
        self.debugger.server.send_event = AsyncRecorder()

        message = (
            '{"event": "loadedSource", "reason": "new", '
            '"source": {"name": "test.py", '
            '"path": "/path/to/test.py"}}'
        )
        self.debugger._handle_debug_message(message)
        _run_loop_once(self.debugger)

        # Check that loadedSource event was sent
        self.debugger.server.send_event.assert_called_once_with(
            "loadedSource",
            {
                "reason": "new",
                "source": {"name": "test.py", "path": "/path/to/test.py"},
            },
        )

    def test_handle_debug_message_stopped_event(self):
        """Test that stopped event sets the stopped_event"""
        self.debugger.server.send_event = AsyncRecorder()

        # Initially, stopped_event should not be set
        assert not self.debugger.stopped_event.is_set()

        message = '{"event": "stopped", "threadId": 1, "reason": "breakpoint"}'
        self.debugger._handle_debug_message(message)
        _run_loop_once(self.debugger)

        # After handling stopped event, stopped_event should be set
        assert self.debugger.stopped_event.is_set()

    def test_handle_debug_message_thread_exited(self):
        """Test handling thread exited event"""
        self.debugger.server.send_event = AsyncRecorder()

        # Add a thread first
        self.debugger.threads[1] = PyDebuggerThread(1, "Thread 1")

        message = '{"event": "thread", "threadId": 1, "reason": "exited"}'
        self.debugger._handle_debug_message(message)
        _run_loop_once(self.debugger)

        # Check that thread was removed
        assert 1 not in self.debugger.threads

        # Check that event was sent
        self.debugger.server.send_event.assert_called_once_with(
            "thread", {"reason": "exited", "threadId": 1}
        )

    def test_handle_debug_message_thread_started(self):
        """Test handling thread started event"""
        self.debugger.server.send_event = AsyncRecorder()

        message = '{"event": "thread", "threadId": 2, "reason": "started"}'
        self.debugger._handle_debug_message(message)
        _run_loop_once(self.debugger)

        # Check that thread was added
        assert 2 in self.debugger.threads
        assert self.debugger.threads[2].id == 2

        # Check that event was sent
        self.debugger.server.send_event.assert_called_once_with(
            "thread", {"reason": "started", "threadId": 2}
        )

    def test_handle_debug_message_invalid_json(self):
        """Test handling invalid JSON message"""
        # Should not raise exception
        self.debugger._handle_debug_message("invalid json")

    def test_handle_debug_message_unknown_event(self):
        """Test handling unknown event type"""
        self.debugger.server.send_event = AsyncRecorder()

        message = '{"event": "unknown_event", "data": "test"}'
        self.debugger._handle_debug_message(message)
        _run_loop_once(self.debugger)

        # Should not send any event for unknown event types
        self.debugger.server.send_event.assert_not_called()


if __name__ == "__main__":
    unittest.main()
