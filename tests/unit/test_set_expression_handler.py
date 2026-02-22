"""Tests for the setExpression request handler."""

from __future__ import annotations

from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest

from dapper.adapter.server import PyDebugger
from dapper.adapter.server import RequestHandler


@pytest.fixture
def mock_debugger():
    """Create a mock debugger."""
    debugger = Mock(spec=PyDebugger)
    debugger.set_expression = AsyncMock()
    return debugger


@pytest.fixture
def mock_server(mock_debugger):
    """Create a mock server with debugger."""
    server = Mock()
    server.debugger = mock_debugger
    return server


@pytest.fixture
def request_handler(mock_server):
    """Create a request handler with mock server."""
    return RequestHandler(mock_server)


@pytest.mark.asyncio
async def test_set_expression_request_success(request_handler, mock_debugger):
    """Test successful setExpression request."""
    mock_debugger.set_expression.return_value = {
        "value": "42",
        "type": "int",
        "variablesReference": 0,
    }

    request = {
        "seq": 1,
        "type": "request",
        "command": "setExpression",
        "arguments": {
            "expression": "x",
            "value": "42",
            "frameId": 123,
        },
    }

    response = await request_handler._handle_set_expression(request)

    mock_debugger.set_expression.assert_called_once_with("x", "42", 123)
    assert response["type"] == "response"
    assert response["request_seq"] == 1
    assert response["success"] is True
    assert response["command"] == "setExpression"
    assert response["body"]["value"] == "42"
    assert response["body"]["type"] == "int"


@pytest.mark.asyncio
async def test_set_expression_request_error(request_handler, mock_debugger):
    """Test setExpression request when debugger raises an exception."""
    mock_debugger.set_expression.side_effect = ValueError("Frame not found")

    request = {
        "seq": 2,
        "type": "request",
        "command": "setExpression",
        "arguments": {
            "expression": "x",
            "value": "99",
            "frameId": 999,
        },
    }

    response = await request_handler._handle_set_expression(request)

    mock_debugger.set_expression.assert_called_once_with("x", "99", 999)
    assert response["type"] == "response"
    assert response["request_seq"] == 2
    assert response["success"] is False
    assert response["command"] == "setExpression"
    assert "message" in response
    assert "Frame not found" in response["message"]
    assert response["body"]["error"] == "RequestError"


@pytest.mark.asyncio
async def test_set_expression_via_handle_request(request_handler, mock_debugger):
    """Test that setExpression requests are routed to the correct handler."""
    mock_debugger.set_expression.return_value = {
        "value": "'ok'",
        "type": "str",
        "variablesReference": 0,
    }

    request = {
        "seq": 3,
        "type": "request",
        "command": "setExpression",
        "arguments": {
            "expression": "obj.name",
            "value": "'ok'",
            "frameId": 456,
        },
    }

    response = await request_handler.handle_request(request)

    mock_debugger.set_expression.assert_called_once_with("obj.name", "'ok'", 456)
    assert response["success"] is True
    assert response["command"] == "setExpression"
    assert response["body"]["value"] == "'ok'"
