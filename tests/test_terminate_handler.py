"""
Test to verify the terminate request handler is implemented and working.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest

from dapper.debugger import PyDebugger
from dapper.server import RequestHandler


@pytest.fixture
def mock_debugger():
    """Create a mock debugger."""
    debugger = Mock(spec=PyDebugger)
    debugger.terminate = AsyncMock()
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
async def test_terminate_handler_exists(request_handler):
    """Test that the terminate handler method exists."""
    assert hasattr(request_handler, "_handle_terminate")
    assert callable(request_handler._handle_terminate)


@pytest.mark.asyncio
async def test_terminate_request_success(request_handler, mock_debugger):
    """Test successful terminate request."""
    request = {"seq": 1, "type": "request", "command": "terminate"}

    response = await request_handler._handle_terminate(request)

    # Verify debugger.terminate was called
    mock_debugger.terminate.assert_called_once()

    # Verify response format
    assert response["type"] == "response"
    assert response["request_seq"] == 1
    assert response["success"] is True
    assert response["command"] == "terminate"


@pytest.mark.asyncio
async def test_terminate_request_error(request_handler, mock_debugger):
    """Test terminate request when debugger raises an exception."""
    # Make debugger.terminate raise an exception
    mock_debugger.terminate.side_effect = RuntimeError("Test error")

    request = {"seq": 2, "type": "request", "command": "terminate"}

    response = await request_handler._handle_terminate(request)

    # Verify debugger.terminate was called
    mock_debugger.terminate.assert_called_once()

    # Verify error response format
    assert response["type"] == "response"
    assert response["request_seq"] == 2
    assert response["success"] is False
    assert response["command"] == "terminate"
    assert "message" in response
    assert "Test error" in response["message"]


@pytest.mark.asyncio
async def test_terminate_via_handle_request(request_handler, mock_debugger):
    """Test that terminate requests are routed to the correct handler."""
    request = {"seq": 3, "type": "request", "command": "terminate"}

    response = await request_handler.handle_request(request)

    # Verify debugger.terminate was called through the routing
    mock_debugger.terminate.assert_called_once()

    # Verify response
    assert response["success"] is True
    assert response["command"] == "terminate"
