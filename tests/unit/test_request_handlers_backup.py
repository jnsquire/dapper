import asyncio
import unittest
from unittest.mock import MagicMock

from dapper.server import RequestHandler


class TestExecutionFlowHandlers(unittest.IsolatedAsyncioTestCase):
    """

from pathlib import Path

# Add the project root to the Python path
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:

Test execution flow request handlers"""

    async def asyncSetUp(self):
        """Set up for each test"""
        self.mock_server = MagicMock()
        self.mock_server.debugger = MagicMock()
        self.handler = RequestHandler(self.mock_server)

        # Set up common mocked methods
        for method in [
            "continue_execution",
            "step_over",
            "step_in",
            "step_out",
            "pause",
        ]:
            mock_method = MagicMock(return_value=asyncio.Future())
            mock_method.return_value.set_result(None)
            setattr(self.mock_server.debugger, method, mock_method)

    async def test_continue(self):
        """Test continue request handler"""
        request = {
            "seq": 1,
            "type": "request",
            "command": "continue",
            "arguments": {"threadId": 1},
        }

        # Mock the continue response
        continue_future = asyncio.Future()
        continue_future.set_result(True)
        self.mock_server.debugger.continue_execution.return_value = continue_future

        result = await self.handler._handle_continue(request)

        # Check that we called continue_execution with the right arguments
        self.mock_server.debugger.continue_execution.assert_called_once_with(1)

        # Check the response
        assert result["type"] == "response"
        assert result["request_seq"] == 1
        assert result["success"]
        assert result["body"]["allThreadsContinued"]

    async def test_next(self):
        """Test next (step over) request handler"""
        request = {
            "seq": 2,
            "type": "request",
            "command": "next",
            "arguments": {"threadId": 1},
        }

        result = await self.handler._handle_next(request)

        # Check that we called step_over with the right arguments
        self.mock_server.debugger.step_over.assert_called_once_with(1)

        # Check the response
        assert result["type"] == "response"
        assert result["request_seq"] == 2
        assert result["success"]

    async def test_step_in(self):
        """Test stepIn request handler"""
        request = {
            "seq": 3,
            "type": "request",
            "command": "stepIn",
            "arguments": {"threadId": 1, "targetId": 100},
        }

        result = await self.handler._handle_step_in(request)

        # Check that we called step_in with the right arguments
        self.mock_server.debugger.step_in.assert_called_once_with(1, 100)

        # Check the response
        assert result["type"] == "response"
        assert result["request_seq"] == 3
        assert result["success"]

    async def test_step_out(self):
        """Test stepOut request handler"""
        request = {
            "seq": 4,
            "type": "request",
            "command": "stepOut",
            "arguments": {"threadId": 1},
        }

        result = await self.handler._handle_step_out(request)

        # Check that we called step_out with the right arguments
        self.mock_server.debugger.step_out.assert_called_once_with(1)

        # Check the response
        assert result["type"] == "response"
        assert result["request_seq"] == 4
        assert result["success"]

    async def test_disconnect(self):
        """Test disconnect request handler"""
        request = {
            "seq": 5,
            "type": "request",
            "command": "disconnect",
            "arguments": {"terminateDebuggee": True},
        }

        self.mock_server.debugger.shutdown = MagicMock(return_value=asyncio.Future())
        self.mock_server.debugger.shutdown.return_value.set_result(None)

        result = await self.handler._handle_disconnect(request)

        self.mock_server.debugger.shutdown.assert_called_once()
        assert result["type"] == "response"
        assert result["request_seq"] == 5
        assert result["success"]


class TestInformationHandlers(unittest.IsolatedAsyncioTestCase):
    """Test information request handlers"""

    async def asyncSetUp(self):
        """Set up for each test"""
        self.mock_server = MagicMock()
        self.mock_server.debugger = MagicMock()
        self.handler = RequestHandler(self.mock_server)

    async def test_threads(self):
        """Test threads request handler"""
        request = {"seq": 1, "type": "request", "command": "threads"}

        # Mock the threads response
        threads = [
            {"id": 1, "name": "Main Thread"},
            {"id": 2, "name": "Worker Thread"},
        ]
        self.mock_server.debugger.get_threads = MagicMock(return_value=asyncio.Future())
        self.mock_server.debugger.get_threads.return_value.set_result(threads)

        result = await self.handler._handle_threads(request)

        # Check that we called get_threads
        self.mock_server.debugger.get_threads.assert_called_once()

        # Check the response
        assert result["type"] == "response"
        assert result["request_seq"] == 1
        assert result["success"]
        assert result["body"]["threads"] == threads

    async def test_stack_trace(self):
        """Test stackTrace request handler"""
        request = {
            "seq": 2,
            "type": "request",
            "command": "stackTrace",
            "arguments": {"threadId": 1, "startFrame": 0, "levels": 20},
        }

        # Mock the stack trace response
        frames = [
            {
                "id": 1000,
                "name": "main",
                "source": {"path": "test.py"},
                "line": 10,
                "column": 0,
            },
            {
                "id": 1001,
                "name": "helper",
                "source": {"path": "test.py"},
                "line": 5,
                "column": 0,
            },
        ]
        self.mock_server.debugger.get_stack_trace = MagicMock(return_value=asyncio.Future())
        self.mock_server.debugger.get_stack_trace.return_value.set_result(frames)

        result = await self.handler._handle_stack_trace(request)

        # Check that we called get_stack_trace with the right arguments
        self.mock_server.debugger.get_stack_trace.assert_called_once_with(1, 0, 20)

        # Check the response
        assert result["type"] == "response"
        assert result["request_seq"] == 2
        assert result["success"]
        assert result["body"]["stackFrames"] == frames
        assert result["body"]["totalFrames"] == 2

    async def test_scopes(self):
        """Test scopes request handler"""
        request = {
            "seq": 3,
            "type": "request",
            "command": "scopes",
            "arguments": {"frameId": 1000},
        }

        # Mock the scopes response
        scopes = [
            {"name": "Local", "variablesReference": 1, "expensive": False},
            {"name": "Global", "variablesReference": 2, "expensive": True},
        ]
        self.mock_server.debugger.get_scopes = MagicMock(return_value=asyncio.Future())
        self.mock_server.debugger.get_scopes.return_value.set_result(scopes)

        result = await self.handler._handle_scopes(request)

        # Check that we called get_scopes with the right arguments
        self.mock_server.debugger.get_scopes.assert_called_once_with(1000)

        # Check the response
        assert result["type"] == "response"
        assert result["request_seq"] == 3
        assert result["success"]
        assert result["body"]["scopes"] == scopes

    async def test_variables(self):
        """Test variables request handler"""
        request = {
            "seq": 4,
            "type": "request",
            "command": "variables",
            "arguments": {
                "variablesReference": 1,
                "filter": "named",
                "start": 0,
                "count": 100,
            },
        }

        # Mock the variables response
        variables = [
            {
                "name": "x",
                "value": "10",
                "type": "int",
                "variablesReference": 0,
            },
            {
                "name": "y",
                "value": "Hello",
                "type": "str",
                "variablesReference": 0,
            },
        ]
        self.mock_server.debugger.get_variables = MagicMock(return_value=asyncio.Future())
        self.mock_server.debugger.get_variables.return_value.set_result(variables)

        result = await self.handler._handle_variables(request)

        # Check that we called get_variables with the right arguments
        self.mock_server.debugger.get_variables.assert_called_once_with(1, "named", 0, 100)

        # Check the response
        assert result["type"] == "response"
        assert result["request_seq"] == 4
        assert result["success"]
        assert result["body"]["variables"] == variables

    async def test_evaluate(self):
        """Test evaluate request handler"""
        request = {
            "seq": 5,
            "type": "request",
            "command": "evaluate",
            "arguments": {
                "expression": "x + y",
                "frameId": 1000,
                "context": "watch",
            },
        }

        # Mock the evaluate response
        eval_result = {"result": "15", "type": "int", "variablesReference": 0}
        self.mock_server.debugger.evaluate = MagicMock(return_value=asyncio.Future())
        self.mock_server.debugger.evaluate.return_value.set_result(eval_result)

        result = await self.handler._handle_evaluate(request)

        # Check that we called evaluate with the right arguments
        self.mock_server.debugger.evaluate.assert_called_once_with("x + y", 1000, "watch")

        # Check the response
        assert result["type"] == "response"
        assert result["request_seq"] == 5
        assert result["success"]
        assert result["body"] == eval_result


if __name__ == "__main__":
    unittest.main()