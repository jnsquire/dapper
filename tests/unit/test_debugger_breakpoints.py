import unittest
from typing import TYPE_CHECKING
from typing import cast
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from dapper.adapter.external_backend import ExternalProcessBackend

if TYPE_CHECKING:
    from dapper.protocol.requests import FunctionBreakpoint
    from dapper.protocol.structures import SourceBreakpoint

from .test_debugger_base import BaseDebuggerTest


class AsyncCallRecorder:
    def __init__(self, side_effect=None, return_value=None):
        self.calls = []
        self.call_args = None
        self.side_effect = side_effect
        self.return_value = return_value

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        self.call_args = (args, kwargs)

        async def _noop():
            if isinstance(self.side_effect, Exception):
                raise self.side_effect
            if callable(self.side_effect):
                return self.side_effect(*args, **kwargs)
            return self.return_value

        return _noop()

    def assert_called_once(self):
        assert len(self.calls) == 1

    def assert_called_once_with(self, *args, **kwargs):
        self.assert_called_once()
        actual_args, actual_kwargs = self.calls[0]
        assert actual_args == args
        assert actual_kwargs == kwargs


@pytest.mark.asyncio
class TestDebuggerBreakpoints(BaseDebuggerTest):
    """
    Test cases for debugger breakpoint management"""

    async def test_set_breakpoints_no_path(self):
        """Test set_breakpoints with source that has no path"""
        source = {"name": "test.py"}  # No path provided
        breakpoints: list[SourceBreakpoint] = [
            cast("SourceBreakpoint", {"line": 10}),
            cast("SourceBreakpoint", {"line": 20}),
        ]

        result = await self.debugger.set_breakpoints(source, breakpoints)

        # Should return unverified breakpoints with error message
        assert len(result) == 2
        assert not result[0].get("verified")
        assert result[0].get("message") == "Source path is required"
        assert not result[1].get("verified")
        assert result[1].get("message") == "Source path is required"

    async def test_set_breakpoints_with_valid_path(self):
        """Test set_breakpoints with valid path and breakpoint setting"""
        # Set up debugger state
        self.debugger.process = MagicMock()
        self.debugger.is_terminated = False

        source = {"path": "/test/file.py"}
        breakpoints: list[SourceBreakpoint] = [
            cast("SourceBreakpoint", {"line": 10}),
            cast("SourceBreakpoint", {"line": 20}),
        ]

        # Create a mock backend
        mock_backend = MagicMock(spec=ExternalProcessBackend)
        mock_backend.set_breakpoints = AsyncMock(return_value=[
            {"verified": True, "line": 10},
            {"verified": True, "line": 20},
        ])
        self.debugger._external_backend = mock_backend

        result = await self.debugger.set_breakpoints(source, breakpoints)

        # Should call the backend's set_breakpoints
        mock_backend.set_breakpoints.assert_called_once()

        # Should return verified breakpoints
        assert len(result) == 2
        assert result[0].get("verified")
        assert result[1].get("verified")

    async def test_set_function_breakpoints(self):
        """Test setting function breakpoints"""
        breakpoints: list[FunctionBreakpoint] = [
            cast("FunctionBreakpoint", {"name": "main"}),
            cast("FunctionBreakpoint", {"name": "helper"}),
        ]

        result = await self.debugger.set_function_breakpoints(breakpoints)

        # Should return breakpoints with verified status
        assert len(result) == 2
        assert result[0].get("verified")
        assert result[1].get("verified")

    async def test_set_exception_breakpoints(self):
        """Test setting exception breakpoints"""
        filters = ["uncaught", "caught"]

        result = await self.debugger.set_exception_breakpoints(filters)

        # Should return breakpoints for each filter
        assert len(result) == 2
        assert result[0]["verified"]
        assert result[1]["verified"]

    async def test_exception_info_basic(self):
        """Test basic exception info functionality"""
        expected_info = {
            "exceptionId": "ValueError",
            "description": "Test exception",
            "breakMode": "always",
            "details": {
                "message": "Test exception",
                "typeName": "ValueError",
                "fullTypeName": "builtins.ValueError",
                "source": "/test/file.py",
                "stackTrace": "Traceback...",
            },
        }

        # Create a mock backend
        mock_backend = MagicMock(spec=ExternalProcessBackend)
        mock_backend.exception_info = AsyncMock(return_value=expected_info)
        self.debugger._external_backend = mock_backend

        result = await self.debugger.exception_info(thread_id=1)

        # Verify the backend was called
        mock_backend.exception_info.assert_called_once_with(1)

        # Should contain exception details
        assert result.get("exceptionId") == "ValueError"
        assert result.get("description") == "Test exception"
        assert result.get("breakMode") == "always"
        assert "details" in result
        details = result.get("details", {})
        assert details.get("typeName") == "ValueError"
        assert details.get("fullTypeName") == "builtins.ValueError"
        assert details.get("message") == "Test exception"


if __name__ == "__main__":
    unittest.main()
