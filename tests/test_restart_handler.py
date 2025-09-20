"""
Tests for the restart request handler.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest

from dapper.server import PyDebugger
from dapper.server import RequestHandler


@pytest.fixture
def mock_debugger():
    dbg = Mock(spec=PyDebugger)
    dbg.restart = AsyncMock()
    return dbg


@pytest.fixture
def mock_server(mock_debugger):
    server = Mock()
    server.debugger = mock_debugger
    return server


@pytest.fixture
def handler(mock_server):
    return RequestHandler(mock_server)


@pytest.mark.asyncio
async def test_restart_handler_exists(handler):
    assert hasattr(handler, "_handle_restart")
    assert callable(handler._handle_restart)


@pytest.mark.asyncio
async def test_restart_success(handler, mock_debugger):
    request = {"seq": 1, "type": "request", "command": "restart"}

    resp = await handler._handle_restart(request)

    mock_debugger.restart.assert_called_once()
    assert resp["type"] == "response"
    assert resp["request_seq"] == 1
    assert resp["success"] is True
    assert resp["command"] == "restart"


@pytest.mark.asyncio
async def test_restart_routing(handler, mock_debugger):
    request = {"seq": 2, "type": "request", "command": "restart"}

    resp = await handler.handle_request(request)

    mock_debugger.restart.assert_called_once()
    assert resp["success"] is True
    assert resp["command"] == "restart"


@pytest.mark.asyncio
async def test_restart_error(handler, mock_debugger):
    mock_debugger.restart.side_effect = RuntimeError("boom")

    request = {"seq": 3, "type": "request", "command": "restart"}

    resp = await handler._handle_restart(request)

    mock_debugger.restart.assert_called_once()
    assert resp["success"] is False
    assert resp["command"] == "restart"
    assert "boom" in resp["message"]
