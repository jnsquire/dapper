import unittest
from unittest.mock import patch

import pytest

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

from pathlib import Path

# Add the project root to the Python path
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:

Test cases for debugger variables and stack trace functionality"""

    async def test_get_stack_trace(self):
        """Test getting stack trace"""
        self.debugger.program_running = True
        self.debugger.is_terminated = False

        # Mock a stack frame
        self.debugger.current_stack_frames[1] = [
            {"id": 1, "name": "main", "line": 10, "column": 5}
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
        self.debugger.var_refs[100] = [
            {"name": "x", "value": "42", "type": "int"},
            {"name": "y", "value": "hello", "type": "str"},
        ]

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

        with patch.object(
            self.debugger,
            "_send_command_to_debuggee",
            new_callable=lambda: AsyncCallRecorder(),
        ) as mock_send:
            result = await self.debugger.evaluate("x + 1", frame_id=1, context="watch")

            # Should send evaluate command
            assert len(mock_send.calls) == 1
            assert mock_send.call_args is not None
            call_args = mock_send.call_args[0][0]
            assert call_args["command"] == "evaluate"
            assert call_args["arguments"]["expression"] == "x + 1"

            # Check the response format (currently returns placeholder)
            assert "result" in result
            assert "variablesReference" in result
            assert result["variablesReference"] == 0


if __name__ == "__main__":
    unittest.main()