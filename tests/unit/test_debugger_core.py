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
        self.debugger.breakpoint_manager.record_line_breakpoint("test.py", 1)
        self.debugger.breakpoint_manager.set_function_breakpoints(["test"], {"test": {}})
        self.debugger._session_facade.threads[1] = MagicMock()
        self.debugger.variable_manager.var_refs[1] = ("object", "test")
        self.debugger._session_facade.current_stack_frames[1] = [{"id": 1}]

        await self.debugger.shutdown()

        # Check that data structures are cleared
        assert len(self.debugger.breakpoint_manager.line_meta) == 0
        assert len(self.debugger.breakpoint_manager.function_names) == 0
        assert len(self.debugger._session_facade.threads) == 0
        assert len(self.debugger.variable_manager.var_refs) == 0
        assert len(self.debugger._session_facade.current_stack_frames) == 0


if __name__ == "__main__":
    unittest.main()
