"""
Test to verify the setVariable request handler is implemented and working.
"""

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
    debugger.set_variable = AsyncMock()
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
async def test_set_variable_request_success(request_handler, mock_debugger):
    """Test successful setVariable request."""
    # Mock debugger response
    mock_debugger.set_variable.return_value = {
        "value": "42",
        "type": "int",
        "variablesReference": 0,
    }

    request = {
        "seq": 1,
        "type": "request",
        "command": "setVariable",
        "arguments": {
            "variablesReference": 123,
            "name": "myVar",
            "value": "42",
        },
    }

    response = await request_handler._handle_set_variable(request)

    # Verify debugger.set_variable was called
    mock_debugger.set_variable.assert_called_once_with(123, "myVar", "42")

    # Verify response format
    assert response["type"] == "response"
    assert response["request_seq"] == 1
    assert response["success"] is True
    assert response["command"] == "setVariable"
    assert response["body"]["value"] == "42"
    assert response["body"]["type"] == "int"


@pytest.mark.asyncio
async def test_set_variable_request_error(request_handler, mock_debugger):
    """Test setVariable request when debugger raises an exception."""
    # Make debugger.set_variable raise an exception
    mock_debugger.set_variable.side_effect = ValueError("Invalid reference")

    request = {
        "seq": 2,
        "type": "request",
        "command": "setVariable",
        "arguments": {
            "variablesReference": 999,
            "name": "invalidVar",
            "value": "test",
        },
    }

    response = await request_handler._handle_set_variable(request)

    # Verify debugger.set_variable was called
    mock_debugger.set_variable.assert_called_once_with(999, "invalidVar", "test")

    # Verify error response format
    assert response["type"] == "response"
    assert response["request_seq"] == 2
    assert response["success"] is False
    assert response["command"] == "setVariable"
    assert "message" in response
    assert "Invalid reference" in response["message"]
    assert response["body"]["error"] == "RequestError"


@pytest.mark.asyncio
async def test_set_variable_via_handle_request(request_handler, mock_debugger):
    """Test that setVariable requests are routed to the correct handler."""
    # Mock debugger response
    mock_debugger.set_variable.return_value = {
        "value": "updated",
        "type": "string",
        "variablesReference": 0,
    }

    request = {
        "seq": 3,
        "type": "request",
        "command": "setVariable",
        "arguments": {
            "variablesReference": 456,
            "name": "testVar",
            "value": "updated",
        },
    }

    response = await request_handler.handle_request(request)

    # Verify debugger.set_variable was called through the routing
    mock_debugger.set_variable.assert_called_once_with(456, "testVar", "updated")

    # Verify response
    assert response["success"] is True
    assert response["command"] == "setVariable"
    assert response["body"]["value"] == "updated"
