import unittest
from unittest.mock import MagicMock
from unittest.mock import patch

from .test_debugger_base import BaseDebuggerTest


# Local async recorder
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


class TestDebuggerBreakpoints(BaseDebuggerTest):
    """Test cases for debugger breakpoint management"""

    async def test_set_breakpoints_no_path(self):
        """Test set_breakpoints with source that has no path"""
        source = {"name": "test.py"}  # No path provided
        breakpoints = [{"line": 10}, {"line": 20}]

        result = await self.debugger.set_breakpoints(source, breakpoints)

        # Should return unverified breakpoints with error message
        assert len(result) == 2
        assert not result[0]["verified"]
        assert result[0]["message"] == "Source path is required"
        assert not result[1]["verified"]
        assert result[1]["message"] == "Source path is required"

    async def test_set_breakpoints_with_valid_path(self):
        """Test set_breakpoints with valid path and breakpoint setting"""
        # Set up debugger state
        self.debugger.process = MagicMock()
        self.debugger.is_terminated = False

        source = {"path": "/test/file.py"}
        breakpoints = [{"line": 10}, {"line": 20}]

        # Mock the command sending
        with patch.object(
            self.debugger,
            "_send_command_to_debuggee",
            new_callable=lambda: AsyncCallRecorder(),
        ) as mock_send:
            result = await self.debugger.set_breakpoints(source, breakpoints)

            # Should send setBreakpoints command
            assert len(mock_send.calls) == 1
            call_args = mock_send.call_args[0][0]
            assert call_args["command"] == "setBreakpoints"
            assert "source" in call_args["arguments"]
            assert "breakpoints" in call_args["arguments"]

            # Should return verified breakpoints
            assert len(result) == 2
            assert result[0]["verified"]
            assert result[1]["verified"]

    async def test_set_function_breakpoints(self):
        """Test setting function breakpoints"""
        breakpoints = [{"name": "main"}, {"name": "helper"}]

        result = await self.debugger.set_function_breakpoints(breakpoints)

        # Should return breakpoints with verified status
        assert len(result) == 2
        assert result[0]["verified"]
        assert result[1]["verified"]

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
        # Mock the _send_command_to_debuggee method to return exception info
        expected_response = {
            "body": {
                "exceptionId": "ValueError",
                "description": "Test exception",
                "breakMode": "always",
                "details": {
                    "message": "Test exception",
                    "typeName": "ValueError",
                    "fullTypeName": "builtins.ValueError",
                    "source": "/test/file.py",
                    "stackTrace": [
                        "Traceback (most recent call last):",
                        '  File "/test/file.py", line 1, in <module>',
                        '    raise ValueError("Test exception")',
                        "ValueError: Test exception",
                    ],
                },
            }
        }

        # Mock the debuggee command
        with patch.object(
            self.debugger,
            "_send_command_to_debuggee",
            new_callable=lambda: AsyncCallRecorder(return_value=expected_response),
        ) as mock_send:
            result = await self.debugger.exception_info(thread_id=1)

            # Verify the command was sent correctly
            # Verify the mock was called once with expected args
            assert len(mock_send.calls) == 1
            sent_args, sent_kwargs = mock_send.call_args
            assert sent_args[0] == {
                "command": "exceptionInfo",
                "arguments": {"threadId": 1},
            }
            assert sent_kwargs.get("expect_response") is True

            # Should contain exception details
            assert result["exceptionId"] == "ValueError"
            assert result["description"] == "Test exception"
            assert result["breakMode"] == "always"
            assert "details" in result
            assert result["details"]["typeName"] == "ValueError"
            assert result["details"]["fullTypeName"] == "builtins.ValueError"
            assert result["details"]["message"] == "Test exception"
            assert "stackTrace" in result["details"]


if __name__ == "__main__":
    unittest.main()
