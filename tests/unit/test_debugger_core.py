import unittest
from unittest.mock import MagicMock

import pytest

from .test_debugger_base import BaseDebuggerTest


@pytest.mark.asyncio
class TestDebuggerCore(BaseDebuggerTest):
    """
    Test cases for core debugger functionality
    """

    async def test_initialization(self):
        """Test that the debugger initializes correctly"""
        assert self.debugger is not None
        assert self.debugger.server == self.mock_server
        assert self.debugger.process is None

    async def test_shutdown(self):
        """Test the shutdown process of the debugger"""
        # Add some test data
        self.debugger.breakpoints["test.py"] = [{"line": 1}]
        self.debugger.function_breakpoints = [{"name": "test"}]
        self.debugger.threads[1] = MagicMock()
        self.debugger.var_refs[1] = "test"
        self.debugger.current_stack_frames[1] = [{"id": 1}]

        await self.debugger.shutdown()

        # Check that data structures are cleared
        assert len(self.debugger.breakpoints) == 0
        assert len(self.debugger.function_breakpoints) == 0
        assert len(self.debugger.threads) == 0
        assert len(self.debugger.var_refs) == 0
        assert len(self.debugger.current_stack_frames) == 0


if __name__ == "__main__":
    unittest.main()
