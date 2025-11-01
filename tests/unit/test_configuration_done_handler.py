"""

import sys
from pathlib import Path

# Add the project root to the Python path
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)


Test to verify the configurationDone request handler is implemented and working.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest

from dapper.server import PyDebugger
from dapper.server import RequestHandler


@pytest.fixture
def mock_debugger():
    """Create a mock debugger."""
    debugger = Mock(spec=PyDebugger)
    debugger.configuration_done_request = AsyncMock()
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
async def test_configuration_done_handler_exists(request_handler):
    """Test that the configurationDone handler method exists."""
    assert hasattr(request_handler, "_handle_configurationDone")
    assert callable(request_handler._handle_configurationDone)


@pytest.mark.asyncio
async def test_configuration_done_request_success(request_handler, mock_debugger):
    """Test successful configurationDone request."""
    request = {"seq": 1, "type": "request", "command": "configurationDone"}

    response = await request_handler._handle_configurationDone(request)

    # Verify debugger.configuration_done_request was called
    mock_debugger.configuration_done_request.assert_called_once()

    # Verify response format
    assert response["type"] == "response"
    assert response["request_seq"] == 1
    assert response["success"] is True
    assert response["command"] == "configurationDone"


@pytest.mark.asyncio
async def test_configuration_done_request_error(request_handler, mock_debugger):
    """Test configurationDone request when debugger raises an exception."""
    # Make debugger.configuration_done_request raise an exception
    mock_debugger.configuration_done_request.side_effect = RuntimeError("Test error")

    request = {"seq": 2, "type": "request", "command": "configurationDone"}

    response = await request_handler._handle_configurationDone(request)

    # Verify debugger.configuration_done_request was called
    mock_debugger.configuration_done_request.assert_called_once()

    # Verify error response format
    assert response["type"] == "response"
    assert response["request_seq"] == 2
    assert response["success"] is False
    assert response["command"] == "configurationDone"
    assert "message" in response
    assert "Test error" in response["message"]


@pytest.mark.asyncio
async def test_configuration_done_via_handle_request(request_handler, mock_debugger):
    """Test that configurationDone requests are routed to the correct handler."""
    request = {"seq": 3, "type": "request", "command": "configurationDone"}

    response = await request_handler.handle_request(request)

    # Verify debugger.configuration_done_request was called through the routing
    mock_debugger.configuration_done_request.assert_called_once()

    # Verify response
    assert response["success"] is True
    assert response["command"] == "configurationDone"
