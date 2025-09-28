"""Pytest-style tests for request handlers.

Converted from unittest.IsolatedAsyncioTestCase to pytest async functions.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from dapper import debug_shared
from dapper.server import RequestHandler


# Simple async recorder used in tests
class AsyncCallRecorder:
    """Small replacement for AsyncMock used within these tests.

    Records calls synchronously and returns a noop coroutine so callers can
    await the result without creating orphaned coroutine warnings. Provides
    minimal assert helpers used by the tests.
    """

    def __init__(self, side_effect=None, return_value=None):
        self.calls: list[tuple[tuple, dict]] = []
        self.side_effect = side_effect
        self.return_value = return_value

    async def __call__(self, *args, **kwargs):
        # Record the call and return the configured return_value (or run
        # side_effect) inside a coroutine so the caller can await it.
        self.calls.append((args, kwargs))

        if isinstance(self.side_effect, Exception):
            raise self.side_effect
        if callable(self.side_effect):
            return self.side_effect(*args, **kwargs)
        return self.return_value

    def assert_called_once(self):
        assert len(self.calls) == 1, f"expected 1 call, got {len(self.calls)}"

    def assert_called_once_with(self, *args, **kwargs):
        self.assert_called_once()
        actual_args, actual_kwargs = self.calls[0]
        assert actual_args == args
        assert actual_kwargs == kwargs


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_server():
    """Create a mock server with debugger for testing."""
    server = MagicMock()
    server.debugger = MagicMock()

    # Set up common mocked methods as AsyncCallRecorder-like async functions
    methods = [
        "continue_execution",
        "step_over",
        "step_in",
        "step_out",
        "pause",
        "get_threads",
        "get_stack_trace",
        "get_scopes",
        "get_variables",
        "evaluate",
    ]
    for method in methods:
        # Use AsyncCallRecorder instances so tests can set .return_value and
        # assert calls without creating AsyncMock coroutines.
        setattr(server.debugger, method, AsyncCallRecorder())

    return server


@pytest.fixture
def handler(mock_server):
    """Create a request handler instance."""
    return RequestHandler(mock_server)


# ---------------------------------------------------------------------------
# Execution Flow Handler Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_continue(handler, mock_server):
    """Test continue request handler"""
    request = {
        "seq": 1,
        "type": "request",
        "command": "continue",
        "arguments": {"threadId": 1},
    }

    # Mock the continue response
    mock_server.debugger.continue_execution.return_value = True

    result = await handler._handle_continue(request)

    # Check that we called continue_execution with the right arguments
    assert len(mock_server.debugger.continue_execution.calls) == 1
    called_args, called_kwargs = mock_server.debugger.continue_execution.calls[0]
    assert called_args == (1,)

    # Check the response
    assert result["type"] == "response"
    assert result["request_seq"] == 1
    assert result["success"] is True
    assert result["body"]["allThreadsContinued"] is True


@pytest.mark.asyncio
async def test_next(handler, mock_server):
    """Test next (step over) request handler"""
    request = {
        "seq": 2,
        "type": "request",
        "command": "next",
        "arguments": {"threadId": 1},
    }

    result = await handler._handle_next(request)

    # Check that we called step_over with the right arguments
    assert len(mock_server.debugger.step_over.calls) == 1
    called_args, called_kwargs = mock_server.debugger.step_over.calls[0]
    assert called_args == (1,)

    # Check the response
    assert result["type"] == "response"
    assert result["request_seq"] == 2
    assert result["success"] is True


@pytest.mark.asyncio
async def test_step_in(handler, mock_server):
    """Test step in request handler"""
    request = {
        "seq": 3,
        "type": "request",
        "command": "stepIn",
        "arguments": {"threadId": 1, "targetId": 100},
    }

    result = await handler._handle_step_in(request)

    # Check that we called step_in with the right arguments
    assert len(mock_server.debugger.step_in.calls) == 1
    called_args, called_kwargs = mock_server.debugger.step_in.calls[0]
    assert called_args == (1, 100)

    # Check the response
    assert result["type"] == "response"
    assert result["request_seq"] == 3
    assert result["success"] is True


@pytest.mark.asyncio
async def test_step_out(handler, mock_server):
    """Test step out request handler"""
    request = {
        "seq": 4,
        "type": "request",
        "command": "stepOut",
        "arguments": {"threadId": 1},
    }

    result = await handler._handle_step_out(request)

    # Check that we called step_out with the right arguments
    assert len(mock_server.debugger.step_out.calls) == 1
    called_args, called_kwargs = mock_server.debugger.step_out.calls[0]
    assert called_args == (1,)

    # Check the response
    assert result["type"] == "response"
    assert result["request_seq"] == 4
    assert result["success"] is True


@pytest.mark.asyncio
async def test_disconnect(handler, mock_server):
    """Test disconnect request handler"""
    request = {
        "seq": 5,
        "type": "request",
        "command": "disconnect",
        "arguments": {"terminateDebuggee": True},
    }

    mock_server.debugger.shutdown = AsyncCallRecorder(return_value=None)

    result = await handler._handle_disconnect(request)

    mock_server.debugger.shutdown.assert_called_once()
    assert result["type"] == "response"
    assert result["request_seq"] == 5
    assert result["success"] is True


# ---------------------------------------------------------------------------
# Information Handler Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_threads(handler, mock_server):
    """Test threads request handler"""
    request = {"seq": 1, "type": "request", "command": "threads"}

    # Mock the threads response
    mock_threads = [
        {"id": 1, "name": "MainThread"},
        {"id": 2, "name": "WorkerThread"},
    ]
    mock_server.debugger.get_threads.return_value = mock_threads

    result = await handler._handle_threads(request)

    # Check that we called get_threads
    mock_server.debugger.get_threads.assert_called_once()

    # Check the response
    assert result["type"] == "response"
    assert result["request_seq"] == 1
    assert result["success"] is True
    assert result["body"]["threads"] == mock_threads


@pytest.mark.asyncio
async def test_stack_trace(handler, mock_server):
    """Test stackTrace request handler"""
    request = {
        "seq": 2,
        "type": "request",
        "command": "stackTrace",
        "arguments": {"threadId": 1, "startFrame": 0, "levels": 20},
    }

    # Mock the stack trace response
    mock_stack_frames = [
        {"id": 1, "name": "main", "line": 10, "column": 1},
        {"id": 2, "name": "helper", "line": 5, "column": 1},
    ]
    stack_trace_response = {
        "stackFrames": mock_stack_frames,
        "totalFrames": len(mock_stack_frames),
    }
    mock_server.debugger.get_stack_trace.return_value = stack_trace_response

    result = await handler._handle_stack_trace(request)

    # Check that we called get_stack_trace with right arguments
    mock_server.debugger.get_stack_trace.assert_called_once_with(1, 0, 20)

    # Check the response
    assert result["type"] == "response"
    assert result["request_seq"] == 2
    assert result["success"] is True
    assert result["body"]["stackFrames"] == stack_trace_response


@pytest.mark.asyncio
async def test_handle_source_prefers_debugger_helper_and_falls_back(handler, mock_server, monkeypatch, tmp_path):
    """RequestHandler._handle_source should prefer debugger helper then fallback to state."""
    # prepare a temp file path
    p = tmp_path / "f.py"
    p.write_text("print(42)\n")

    # Case A: debugger provides get_source_content_by_path (async)
    mock_server.debugger.get_source_content_by_path = AsyncCallRecorder(return_value="dbg-content")

    req = {"seq": 100, "type": "request", "command": "source", "arguments": {"source": {"path": str(p)}}}
    res = await handler._handle_source(req)
    assert res["success"] is True
    assert res["body"]["content"] == "dbg-content"

    # Case B: debugger helper absent -> fallback to debug_shared.state
    delattr(mock_server.debugger, "get_source_content_by_path")

    def state_getter(path):
        return "state-content"

    monkeypatch.setattr(debug_shared.state, "get_source_content_by_path", state_getter)

    res2 = await handler._handle_source(req)
    assert res2["success"] is True
    assert res2["body"]["content"] == "state-content"


@pytest.mark.asyncio
async def test_handle_module_source_reads_module_file(handler, tmp_path):
    """RequestHandler._handle_module_source should read module.__file__ and return content."""
    p = tmp_path / "mymod.py"
    p.write_text("# hello\n")
    m = types.ModuleType("__unit_mymod__")
    m.__file__ = str(p)
    sys.modules["__unit_mymod__"] = m

    req = {"seq": 200, "type": "request", "command": "moduleSource", "arguments": {"moduleId": "__unit_mymod__"}}
    res = await handler._handle_module_source(req)
    assert res["success"] is True
    assert "hello" in res["body"]["content"]

    # cleanup
    del sys.modules["__unit_mymod__"]


@pytest.mark.asyncio
async def test_scopes(handler, mock_server):
    """Test scopes request handler"""
    request = {
        "seq": 3,
        "type": "request",
        "command": "scopes",
        "arguments": {"frameId": 1},
    }

    # Mock the scopes response
    mock_scopes = [
        {"name": "Local", "variablesReference": 1001, "expensive": False},
        {"name": "Global", "variablesReference": 1002, "expensive": False},
    ]
    mock_server.debugger.get_scopes.return_value = mock_scopes

    result = await handler._handle_scopes(request)

    # Check that we called get_scopes with right arguments
    mock_server.debugger.get_scopes.assert_called_once_with(1)

    # Check the response
    assert result["type"] == "response"
    assert result["request_seq"] == 3
    assert result["success"] is True
    assert result["body"]["scopes"] == mock_scopes


@pytest.mark.asyncio
async def test_variables(handler, mock_server):
    """Test variables request handler"""
    request = {
        "seq": 4,
        "type": "request",
        "command": "variables",
        "arguments": {
            "variablesReference": 1001,
            "filter": "named",
            "start": 0,
            "count": 100,
        },
    }

    # Mock the variables response
    mock_variables = [
        {"name": "x", "value": "42", "type": "int", "variablesReference": 0},
        {
            "name": "y",
            "value": "hello",
            "type": "str",
            "variablesReference": 0,
        },
    ]
    mock_server.debugger.get_variables.return_value = mock_variables

    result = await handler._handle_variables(request)

    # Check that we called get_variables with right arguments
    mock_server.debugger.get_variables.assert_called_once_with(1001, "named", 0, 100)

    # Check the response
    assert result["type"] == "response"
    assert result["request_seq"] == 4
    assert result["success"] is True
    assert result["body"]["variables"] == mock_variables


@pytest.mark.asyncio
async def test_evaluate(handler, mock_server):
    """Test evaluate request handler"""
    request = {
        "seq": 5,
        "type": "request",
        "command": "evaluate",
        "arguments": {"expression": "x + 1", "frameId": 1, "context": "watch"},
    }

    # Mock the evaluate response
    mock_result = {"result": "43", "type": "int", "variablesReference": 0}
    mock_server.debugger.evaluate.return_value = mock_result

    result = await handler._handle_evaluate(request)

    # Check that we called evaluate with right arguments
    mock_server.debugger.evaluate.assert_called_once_with("x + 1", 1, "watch")

    # Check the response
    assert result["type"] == "response"
    assert result["request_seq"] == 5
    assert result["success"] is True
    assert result["body"]["result"] == "43"
    assert result["body"]["type"] == "int"
    assert result["body"]["variablesReference"] == 0
