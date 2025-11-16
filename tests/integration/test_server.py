"""
Pytest-style tests for the Debug Adapter Protocol server.
"""

from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import patch

import pytest

from dapper.server import DebugAdapterServer
from tests.mocks import MockConnection


# Simple async call recorder usable in place of AsyncMock
class AsyncCallRecorder:
    def __init__(self, side_effect=None, return_value=None):
        self.calls = []
        self.await_count = 0
        self.side_effect = side_effect
        self.return_value = return_value

    async def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        self.await_count += 1
        if isinstance(self.side_effect, Exception):
            raise self.side_effect
        if callable(self.side_effect):
            return self.side_effect(*args, **kwargs)
        return self.return_value

    def assert_called_once_with(self, *args, **kwargs):
        assert len(self.calls) == 1
        assert self.calls[0] == (args, kwargs)

    def assert_awaited_once(self):
        assert self.await_count == 1


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_connection():
    """Create a mock connection for testing."""
    return MockConnection()


# debug_server fixture removed - was unused and created event loop leaks


# ---------------------------------------------------------------------------
# Server Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("dapper.server.PyDebugger")
async def test_initialization_sequence(mock_debugger_class):
    """Test the initialization sequence"""
    # Setup mocked debugger
    mock_debugger = mock_debugger_class.return_value
    mock_debugger.launch = AsyncCallRecorder(return_value=None)
    mock_debugger.shutdown = AsyncCallRecorder(return_value=None)

    # Create mock connection and server with patched debugger
    with patch("dapper.server.PyDebugger", return_value=mock_debugger):
        mock_connection = MockConnection()
        loop = asyncio.get_event_loop()
        server = DebugAdapterServer(mock_connection, loop)

    # Add initialization and configuration requests
    mock_connection.add_request("initialize")
    mock_connection.add_request("launch", {"program": "test.py"}, seq=2)
    mock_connection.add_request("configurationDone", seq=3)

    # Run the server with timeout
    server_task = asyncio.create_task(server.start())
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(server_task, timeout=1.0)

    # Verify the messages sent back
    assert len(mock_connection.written_messages) >= 3

    # Find the initialize response
    init_response = next(
        (
            m
            for m in mock_connection.written_messages
            if m.get("type") == "response" and m.get("command") == "initialize"
        ),
        None,
    )
    assert init_response is not None
    if init_response:
        assert init_response["request_seq"] == 1
        assert init_response["success"] is True

    # Verify we got an initialized event
    init_event = next(
        (
            m
            for m in mock_connection.written_messages
            if m.get("type") == "event" and m.get("event") == "initialized"
        ),
        None,
    )
    assert init_event is not None

    # Verify the launch request is processed
    launch_response = next(
        (
            m
            for m in mock_connection.written_messages
            if m.get("type") == "response" and m.get("request_seq") == 2
        ),
        None,
    )
    assert launch_response is not None
    if launch_response:
        assert launch_response["command"] == "launch"
        assert launch_response["success"] is True

    # Verify the debugger was called with correct args
    mock_debugger.launch.assert_called_once_with("test.py", [], False, False)


@pytest.mark.asyncio
@patch("dapper.server.PyDebugger")
async def test_attach_request_routed(mock_debugger_class):
    """Attach should be routed to debugger.attach"""
    # Setup mocked debugger
    mock_debugger = mock_debugger_class.return_value
    mock_debugger.attach = AsyncCallRecorder(return_value=None)
    mock_debugger.shutdown = AsyncCallRecorder(return_value=None)

    # Create server with patched debugger
    with patch("dapper.server.PyDebugger", return_value=mock_debugger):
        conn = MockConnection()
        server = DebugAdapterServer(conn, asyncio.get_event_loop())

    # Add attach request with IPC parameters
    conn.add_request(
        "attach",
        {
            "useIpc": True,
            "ipcTransport": "tcp",
            "ipcHost": "127.0.0.1",
            "ipcPort": 5000,
        },
        seq=1,
    )

    task = asyncio.create_task(server.start())
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(task, timeout=0.5)

    # A response for attach should be present
    attach_resp = next(
        (m for m in conn.written_messages if m.get("command") == "attach"),
        None,
    )
    assert attach_resp is not None
    assert attach_resp["success"] is True

    # And debugger.attach should be called with our args
    calls = mock_debugger.attach.calls  # type: ignore[attr-defined]
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert kwargs["use_ipc"] is True
    assert kwargs["ipc_transport"] == "tcp"
    assert kwargs["ipc_host"] == "127.0.0.1"
    assert kwargs["ipc_port"] == 5000


@pytest.mark.asyncio
@patch("dapper.server.PyDebugger")
async def test_error_handling(mock_debugger_class):
    """Test error handling in server"""
    # Setup mocked debugger
    mock_debugger = mock_debugger_class.return_value
    mock_debugger.launch = AsyncCallRecorder(side_effect=RuntimeError("Test error"))
    mock_debugger.shutdown = AsyncCallRecorder(return_value=None)

    # Create mock connection and server with patched debugger
    with patch("dapper.server.PyDebugger", return_value=mock_debugger):
        mock_connection = MockConnection()
        loop = asyncio.get_event_loop()
        server = DebugAdapterServer(mock_connection, loop)

    # Add a request that will fail
    mock_connection.add_request("launch", {"program": "test.py"})

    # Run the server with timeout
    server_task = asyncio.create_task(server.start())
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(server_task, timeout=1.0)

    # Verify the error response
    assert len(mock_connection.written_messages) >= 1

    # Find the launch response
    response = next(
        (
            m
            for m in mock_connection.written_messages
            if m.get("type") == "response" and m.get("command") == "launch"
        ),
        None,
    )
    assert response is not None

    if response:
        assert response["type"] == "response"
        assert response["command"] == "launch"
        assert response["success"] is False
        assert "message" in response
        assert response["message"] == "Test error"


@pytest.mark.asyncio
async def test_send_event():
    """Test sending events from the server"""
    mock_connection = MockConnection()
    loop = asyncio.get_event_loop()
    server = DebugAdapterServer(mock_connection, loop)
    # Send an event
    await server.send_event("stopped", {"reason": "breakpoint", "threadId": 1})
    # Verify the event was sent
    assert len(mock_connection.written_messages) == 1
    event = mock_connection.written_messages[0]
    assert event["type"] == "event"
    assert event["event"] == "stopped"
    assert event["body"]["reason"] == "breakpoint"
    assert event["body"]["threadId"] == 1


@pytest.mark.asyncio
async def test_sequence_numbers():
    """Test that sequence numbers are assigned correctly"""
    mock_connection = MockConnection()
    loop = asyncio.get_event_loop()
    server = DebugAdapterServer(mock_connection, loop)

    # Send multiple messages to check sequence numbering
    await server.send_event("initialized")
    await server.send_event("stopped", {"reason": "entry"})
    await server.send_response({"seq": 5, "command": "test"}, {"result": "ok"})

    # Verify sequence numbers
    assert len(mock_connection.written_messages) == 3

    for i, msg in enumerate(mock_connection.written_messages):
        assert msg["seq"] == i + 1


@pytest.mark.asyncio
@patch("dapper.server.PyDebugger")
async def test_modules_request(mock_debugger_class):
    """Test the modules request handler"""
    # Setup mocked debugger
    mock_debugger = mock_debugger_class.return_value
    mock_debugger.launch = AsyncCallRecorder(return_value=None)
    mock_debugger.shutdown = AsyncCallRecorder(return_value=None)

    # Mock the get_modules method
    mock_modules = [
        {"id": "1", "name": "sys", "isUserCode": False},
        {"id": "2", "name": "os", "isUserCode": False, "path": "/usr/lib/python3.13/os.py"},
        {
            "id": "3",
            "name": "test_module",
            "isUserCode": True,
            "path": "/home/user/test_module.py",
        },
    ]
    mock_debugger.get_modules = AsyncCallRecorder(return_value=mock_modules)

    # Create mock connection and server with patched debugger
    with patch("dapper.server.PyDebugger", return_value=mock_debugger):
        mock_connection = MockConnection()
        loop = asyncio.get_event_loop()
        server = DebugAdapterServer(mock_connection, loop)

    # Add initialization and modules request
    mock_connection.add_request("initialize")
    mock_connection.add_request("launch", {"program": "test.py"}, seq=2)
    mock_connection.add_request("configurationDone", seq=3)
    mock_connection.add_request("modules", {}, seq=4)

    # Run the server with timeout
    server_task = asyncio.create_task(server.start())
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(server_task, timeout=1.0)

    # Find the modules response
    modules_response = next(
        (
            m
            for m in mock_connection.written_messages
            if m.get("type") == "response" and m.get("command") == "modules"
        ),
        None,
    )

    assert modules_response is not None
    if modules_response:
        # Debug output for test failure investigation
        assert modules_response["request_seq"] == 4, (
            f"Expected seq 4, got response: {modules_response}"
        )
        assert modules_response["success"] is True, f"Modules request failed: {modules_response}"
        assert "modules" in modules_response["body"]

        # Should have some modules loaded (at least sys, os, etc.)
        modules = modules_response["body"]["modules"]
        assert isinstance(modules, list)
        assert len(modules) > 0

        # Check first module has required fields
        first_module = modules[0]
        assert "id" in first_module
        assert "name" in first_module
        assert isinstance(first_module.get("isUserCode"), bool)


@pytest.mark.asyncio
async def test_next_seq_and_send_message_behaviour():
    # Ensure next_seq increments and send_message respects connection state
    conn = MockConnection()
    server = DebugAdapterServer(conn, asyncio.get_event_loop())

    # next_seq increments
    n1 = server.next_seq
    n2 = server.next_seq
    assert n2 == n1 + 1

    # When connection is disconnected, send_message should not raise and not write
    conn._is_connected = False
    await server.send_message({"type": "event", "event": "test"})
    assert conn.written_messages == []


@pytest.mark.asyncio
async def test_send_response_and_error_response_with_protocol(monkeypatch):
    conn = MockConnection()
    server = DebugAdapterServer(conn, asyncio.get_event_loop())

    # Patch protocol_handler.create_response to return a predictable dict
    def fake_create_response(request, success, body=None, message=None):
        return {
            "type": "response",
            "command": request.get("command"),
            "success": success,
            "body": body or {},
            "message": message,
        }

    monkeypatch.setattr(
        server,
        "protocol_handler",
        type("PH", (), {"create_response": staticmethod(fake_create_response)}),
    )

    req = {"seq": 99, "type": "request", "command": "doIt"}
    await server.send_response(req, {"ok": True})
    # one message written
    assert conn.written_messages
    resp = conn.written_messages[-1]
    assert resp["command"] == "doIt"
    assert resp["success"] is True

    # error response
    await server.send_error_response(req, "bad")
    resp2 = conn.written_messages[-1]
    assert resp2["success"] is False
    assert resp2.get("message") == "bad"
