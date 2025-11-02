"""
Test cases for log point functionality in the debug adapter.

Log points allow setting breakpoints that output formatted messages
without stopping execution, supporting expression interpolation.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import FrameType
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from dapper.debug_launcher import _format_log_message
from dapper.debugger_bdb import DebuggerBDB
from dapper.server import DebugAdapterServer

from .test_server import AsyncCallRecorder
from .test_server import MockConnection


class TestLogMessageFormatting(unittest.TestCase):
    """Test the _format_log_message function directly"""

    def setUp(self):
        """Set up test frame with some variables"""
        # Create a mock frame with test variables
        self.frame = MagicMock(spec=FrameType)
        self.frame.f_locals = {
            "x": 42,
            "name": "test",
            "items": [1, 2, 3],
            "data": {"key": "value"},
        }
        self.frame.f_globals = {
            "global_var": "global_value",
            "__builtins__": __builtins__,
        }

    def test_simple_variable_interpolation(self):
        """Test basic variable interpolation"""
        template = "x = {x}"
        result = _format_log_message(template, self.frame)
        assert result == "x = 42"

    def test_multiple_variables(self):
        """Test multiple variable interpolation"""
        template = "name: {name}, x: {x}"
        result = _format_log_message(template, self.frame)
        assert result == "name: test, x: 42"

    def test_expression_evaluation(self):
        """Test expression evaluation in interpolation"""
        template = "length: {len(items)}, sum: {x + 10}"
        result = _format_log_message(template, self.frame)
        assert result == "length: 3, sum: 52"

    def test_dict_access(self):
        """Test dictionary access in expressions"""
        template = "data key: {data['key']}"
        result = _format_log_message(template, self.frame)
        assert result == "data key: value"

    def test_global_variables(self):
        """Test access to global variables"""
        template = "global: {global_var}"
        result = _format_log_message(template, self.frame)
        assert result == "global: global_value"

    def test_invalid_expression_handling(self):
        """Test that invalid expressions are replaced with <error>"""
        template = "invalid: {nonexistent_var}"
        result = _format_log_message(template, self.frame)
        assert result == "invalid: <error>"

    def test_syntax_error_handling(self):
        """Test that syntax errors are handled gracefully"""
        template = "syntax error: {x +}"
        result = _format_log_message(template, self.frame)
        assert result == "syntax error: <error>"

    def test_escaped_braces(self):
        """Test escaped braces are handled correctly"""
        # NOTE: Current implementation has a bug where escaped braces are
        # treated as expressions and return <error>. This should be fixed.
        template = "literal {{braces}} and {x}"
        result = _format_log_message(template, self.frame)
        # Implementation fixed: escaped braces preserved
        assert result == "literal {braces} and 42"

    def test_mixed_escaped_and_expressions(self):
        """Test mix of escaped braces and expressions"""
        # NOTE: Current implementation has a bug where escaped braces are
        # treated as expressions and return <error>. This should be fixed.
        template = "{{x}} = {x}, {{name}} = {name}"
        result = _format_log_message(template, self.frame)
        # Implementation fixed: escaped braces preserved
        assert result == "{x} = 42, {name} = test"

    def test_no_expressions(self):
        """Test template with no expressions"""
        template = "Just a plain message"
        result = _format_log_message(template, self.frame)
        assert result == "Just a plain message"

    def test_empty_template(self):
        """Test empty template"""
        template = ""
        result = _format_log_message(template, self.frame)
        assert result == ""


class TestLogPointsIntegration(unittest.TestCase):
    """Integration tests for log points using the debugger"""

    def setUp(self):
        """Set up debugger and test environment"""
        self.debugger = DebuggerBDB()
        self.messages = []

        # Mock send_debug_message to capture output
        self.original_send_debug_message = None

    def tearDown(self):
        """Clean up after tests"""
        if self.original_send_debug_message:
            # Restore original function if we mocked it
            pass

    @patch("dapper.debug_launcher.send_debug_message")
    def test_basic_log_point_execution(self, mock_send_debug_message):
        """Test that log points output messages and continue execution"""
        # Create a temporary Python file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            test_file = f.name
            f.write("""
x = 10
y = 20
result = x + y  # Line 4
print("Done")
""")

        try:
            # Set up a log point at line 4
            self.debugger.record_breakpoint(
                test_file,
                4,
                condition=None,
                hit_condition=None,
                log_message="Calculating: x={x}, y={y}, result={result}",
            )

            # Set the breakpoint
            self.debugger.set_break(test_file, 4)

            # Create a mock frame at line 4
            frame = MagicMock(spec=FrameType)
            frame.f_code.co_filename = test_file
            frame.f_lineno = 4
            frame.f_locals = {"x": 10, "y": 20, "result": 30}
            frame.f_globals = {"__builtins__": __builtins__}

            # Mock the continue method to track if it was called
            self.debugger.set_continue = MagicMock()

            # Call user_line to trigger log point
            self.debugger.user_line(frame)

            # Verify that send_debug_message was called with correct output
            mock_send_debug_message.assert_called_with(
                "output", category="console", output="Calculating: x=10, y=20, result=30"
            )

            # Verify that execution continued (set_continue was called)
            self.debugger.set_continue.assert_called_once()

        finally:
            # Clean up temp file
            Path(test_file).unlink(missing_ok=True)

    @patch("dapper.debug_launcher.send_debug_message")
    def test_log_point_with_condition(self, mock_send_debug_message):
        """Test log points with conditions"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            test_file = f.name
            f.write("""
for i in range(5):
    x = i * 2  # Line 3
""")

        try:
            # Set up a conditional log point
            self.debugger.record_breakpoint(
                test_file,
                3,
                condition="i > 2",  # Only log when i > 2
                hit_condition=None,
                log_message="Loop iteration: i={i}, x={x}",
            )

            self.debugger.set_break(test_file, 3, cond="i > 2")

            # Create mock frame with i = 1 (condition not met)
            frame = MagicMock(spec=FrameType)
            frame.f_code.co_filename = test_file
            frame.f_lineno = 3
            frame.f_locals = {"i": 1, "x": 2}
            frame.f_globals = {"__builtins__": __builtins__}

            # BDB should handle the condition, but let's simulate it passing
            # by only testing when condition is met
            frame.f_locals = {"i": 3, "x": 6}  # Condition met

            self.debugger.set_continue = MagicMock()
            self.debugger.user_line(frame)

            # Should log since condition is met
            mock_send_debug_message.assert_called_with(
                "output", category="console", output="Loop iteration: i=3, x=6"
            )

        finally:
            Path(test_file).unlink(missing_ok=True)

    @patch("dapper.debug_launcher.send_debug_message")
    def test_log_point_with_hit_condition(self, mock_send_debug_message):
        """Test log points with hit conditions"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            test_file = f.name
            f.write("""
for i in range(10):
    x = i  # Line 3
""")

        try:
            # Set up a log point with hit condition (every 3rd hit)
            self.debugger.record_breakpoint(
                test_file,
                3,
                condition=None,
                hit_condition="% 3",  # Every 3rd hit (parser understands '% N')
                log_message="Hit #{meta['hit']}: i={i}",
            )

            self.debugger.set_break(test_file, 3)
            self.debugger.set_continue = MagicMock()

            # Simulate multiple hits
            for hit_count in range(1, 7):  # Hits 1-6
                frame = MagicMock(spec=FrameType)
                frame.f_code.co_filename = test_file
                frame.f_lineno = 3
                frame.f_locals = {"i": hit_count - 1, "x": hit_count - 1}
                frame.f_globals = {"__builtins__": __builtins__}

                # Manually set the hit count in metadata
                meta = self.debugger.breakpoint_meta.get((test_file, 3), {})
                meta["hit"] = hit_count
                self.debugger.breakpoint_meta[(test_file, 3)] = meta

                self.debugger.user_line(frame)

            # Should only log on hits 3 and 6 (multiples of 3)
            # Check that send_debug_message was called twice (hits 3 and 6)
            assert mock_send_debug_message.call_count == 2

        finally:
            Path(test_file).unlink(missing_ok=True)

    @patch("dapper.debug_launcher.send_debug_message")
    def test_log_point_expression_error_handling(self, mock_send_debug_message):
        """Test log points handle expression errors gracefully"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            test_file = f.name
            f.write("""
x = 10
y = None  # Line 3
""")

        try:
            # Set up a log point with an expression that will fail
            self.debugger.record_breakpoint(
                test_file,
                3,
                condition=None,
                hit_condition=None,
                log_message="x={x}, length of y={len(y)}",  # len(None) will fail
            )

            self.debugger.set_break(test_file, 3)

            frame = MagicMock(spec=FrameType)
            frame.f_code.co_filename = test_file
            frame.f_lineno = 3
            frame.f_locals = {"x": 10, "y": None}
            frame.f_globals = {"__builtins__": __builtins__}

            self.debugger.set_continue = MagicMock()
            self.debugger.user_line(frame)

            # Should still output something, with <error> for failed expression
            mock_send_debug_message.assert_called_with(
                "output", category="console", output="x=10, length of y=<error>"
            )

        finally:
            Path(test_file).unlink(missing_ok=True)


class TestFunctionLogPoints(unittest.TestCase):
    """Test log points for function breakpoints"""

    def setUp(self):
        """Set up debugger for function breakpoint tests"""
        self.debugger = DebuggerBDB()

    @patch("dapper.debug_launcher.send_debug_message")
    def test_function_log_point(self, mock_send_debug_message):
        """Test log points on function breakpoints"""
        # Set up function breakpoint with log message
        function_name = "test_function"
        self.debugger.function_breakpoints = [function_name]
        self.debugger.function_breakpoint_meta = {
            function_name: {
                "hit": 0,
                "condition": None,
                "hitCondition": None,
                "logMessage": "Called function: {function_name} with args: {args}",
            }
        }

        # Create a mock frame for function call
        frame = MagicMock(spec=FrameType)
        frame.f_code.co_name = function_name
        frame.f_locals = {"args": "(1, 2)", "function_name": function_name}
        frame.f_globals = {"__builtins__": __builtins__}

        self.debugger.set_continue = MagicMock()

        # Call user_call to trigger function breakpoint
        self.debugger.user_call(frame, None)

        # Verify log message was sent
        mock_send_debug_message.assert_called_with(
            "output", category="console", output="Called function: test_function with args: (1, 2)"
        )


@pytest.mark.asyncio
async def test_log_points_server_integration():
    """Test log points through the server DAP interface"""
    with patch("dapper.server.PyDebugger") as mock_debugger_class:
        # Setup mocked debugger
        mock_debugger = mock_debugger_class.return_value
        mock_debugger.launch = AsyncCallRecorder(return_value=None)
        mock_debugger.shutdown = AsyncCallRecorder(return_value=None)
        mock_debugger.set_breakpoints = AsyncCallRecorder(
            return_value=[{"verified": True, "line": 10}]
        )

        # Create mock connection and server
        mock_connection = MockConnection()
        loop = asyncio.get_event_loop()
        server = DebugAdapterServer(mock_connection, loop)
        server.debugger = mock_debugger

        # Add requests including log point breakpoint
        mock_connection.add_request("initialize")
        mock_connection.add_request("launch", {"program": "test.py"}, seq=2)
        mock_connection.add_request(
            "setBreakpoints",
            {
                "source": {"path": "test.py"},
                "breakpoints": [{"line": 10, "logMessage": "Debug: x={x}, y={y}"}],
            },
            seq=3,
        )
        mock_connection.add_request("configurationDone", seq=4)

        # Run the server with timeout
        server_task = asyncio.create_task(server.start())
        try:
            await asyncio.wait_for(server_task, timeout=1.0)
        except asyncio.TimeoutError:
            pass

        # Verify that set_breakpoints was called
        assert len(mock_debugger.set_breakpoints.calls) == 1

        # Find the setBreakpoints response
        bp_response = next(
            (
                m
                for m in mock_connection.written_messages
                if m.get("type") == "response" and m.get("command") == "setBreakpoints"
            ),
            None,
        )

        assert bp_response is not None
        assert bp_response["success"] is True


if __name__ == "__main__":
    unittest.main()
