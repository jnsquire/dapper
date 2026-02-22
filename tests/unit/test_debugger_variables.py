import unittest
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from dapper.adapter.external_backend import ExternalProcessBackend
from dapper.adapter.inprocess_backend import InProcessBackend

from .test_debugger_base import BaseDebuggerTest


# Local async recorder to avoid AsyncMock-created orphaned coroutines
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
class TestDebuggerVariables(BaseDebuggerTest):
    """
    Test cases for debugger variables and stack trace functionality
    """

    async def test_get_stack_trace(self):
        """Test getting stack trace"""
        self.debugger.program_running = True
        self.debugger.is_terminated = False

        # Mock a stack frame
        self.debugger._session_facade.current_stack_frames[1] = [
            {"id": 1, "name": "main", "line": 10, "column": 5},
        ]

        result = await self.debugger.get_stack_trace(1, 0, 10)

        # Should return stack frames
        assert "stackFrames" in result
        assert len(result["stackFrames"]) == 1
        assert result["stackFrames"][0]["name"] == "main"
        assert result["stackFrames"][0]["line"] == 10

    async def test_get_variables(self):
        """Test getting variables"""
        # Set up variable reference
        self.debugger.variable_manager.var_refs[100] = (
            "object",
            [
            {"name": "x", "value": "42", "type": "int"},
            {"name": "y", "value": "hello", "type": "str"},
            ],
        )

        result = await self.debugger.get_variables(100)

        # Should return variables list directly
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["name"] == "x"
        assert result[0]["value"] == "42"

    async def test_get_scopes(self):
        """Test getting scopes for a frame"""
        result = await self.debugger.get_scopes(1)

        # Should return scopes list directly
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["name"] == "Local"
        assert not result[0]["expensive"]
        assert result[1]["name"] == "Global"
        assert result[1]["expensive"]

    async def test_evaluate_expression(self):
        """Test expression evaluation"""
        self.debugger.program_running = True

        # Create a mock backend
        mock_backend = MagicMock(spec=ExternalProcessBackend)
        mock_backend.evaluate = AsyncMock(return_value={"result": "2", "variablesReference": 0})
        self.debugger._external_backend = mock_backend

        result = await self.debugger.evaluate("x + 1", frame_id=1, context="watch")

        # Should call the backend's evaluate method
        mock_backend.evaluate.assert_called_once_with("x + 1", 1, "watch")

        # Check the response format
        assert "result" in result
        assert "variablesReference" in result

    async def test_get_variables_sends_command(self):
        """Test that get_variables sends a command to the debuggee when var_ref is not in cache."""
        expected_variables = [{"name": "a", "value": "1", "type": "int", "variablesReference": 0}]

        # Create a mock backend
        mock_backend = MagicMock(spec=ExternalProcessBackend)
        mock_backend.get_variables = AsyncMock(return_value=expected_variables)
        self.debugger._external_backend = mock_backend

        result = await self.debugger.get_variables(123, filter_type="named", start=1, count=10)

        # Verify backend's get_variables was called
        mock_backend.get_variables.assert_called_once_with(123, "named", 1, 10)

        # Verify result
        assert len(result) == 1
        assert result[0]["name"] == "a"
        assert result[0]["value"] == "1"

    async def test_get_variables_in_process(self):
        """Test that get_variables delegates to in-process debugger when enabled."""
        self.debugger.in_process = True
        mock_bridge = MagicMock()
        self.debugger._inproc_bridge = mock_bridge
        self.debugger._inproc_backend = InProcessBackend(mock_bridge)

        expected_variables = [{"name": "ip_a", "value": "99", "variablesReference": 0}]
        mock_bridge.variables.return_value = expected_variables

        result = await self.debugger.get_variables(789, filter_type="indexed", start=5, count=20)

        # Verify in-process call
        mock_bridge.variables.assert_called_once_with(
            789,
            filter_type="indexed",
            start=5,
            count=20,
        )
        assert result == expected_variables


if __name__ == "__main__":
    unittest.main()
