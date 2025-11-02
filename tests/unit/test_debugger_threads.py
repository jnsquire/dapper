import unittest

import pytest

from dapper.server import PyDebuggerThread

from .test_debugger_base import BaseDebuggerTest


@pytest.mark.asyncio
class TestDebuggerThreads(BaseDebuggerTest):
    """
Test cases for debugger thread management"""

    async def test_py_debugger_thread_initialization(self):
        """Test PyDebuggerThread initialization"""
        thread = PyDebuggerThread(1, "Main Thread")

        assert thread.id == 1
        assert thread.name == "Main Thread"
        assert not thread.is_stopped
        assert thread.stop_reason == ""

    async def test_get_threads(self):
        """Test getting thread information"""
        # Add some threads
        self.debugger.threads[1] = PyDebuggerThread(1, "Main Thread")
        self.debugger.threads[2] = PyDebuggerThread(2, "Worker Thread")

        result = await self.debugger.get_threads()

        # Should return thread list directly
        assert isinstance(result, list)
        assert len(result) == 2

        # Check thread details
        thread_ids = [t["id"] for t in result]
        assert 1 in thread_ids
        assert 2 in thread_ids

    async def test_thread_stopped_state(self):
        """Test thread stopped state management"""
        thread = PyDebuggerThread(1, "Test Thread")

        # Initially not stopped
        assert not thread.is_stopped

        # Set stopped state
        thread.is_stopped = True
        thread.stop_reason = "breakpoint"

        assert thread.is_stopped
        assert thread.stop_reason == "breakpoint"


if __name__ == "__main__":
    unittest.main()