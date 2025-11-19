"""

Pytest-style tests for the DAP connection classes.

Converted from unittest.TestCase to plain pytest functions with
fixtures to reduce boilerplate and align with modern pytest patterns.
"""

from __future__ import annotations

import asyncio
import json
import os
from unittest import mock

import pytest

from dapper.ipc.connections.pipe import NamedPipeServerConnection
from dapper.ipc.connections.tcp import TCPServerConnection

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pipe_name():
    """Generate a unique pipe name for testing."""
    return f"test-pipe-{os.getpid()}"


# Helpers removed: inlined logic now lives directly inside the test.


# ---------------------------------------------------------------------------
# TCP Connection Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tcp_connection_initialization():
    """Test TCP connection initialization."""
    conn = TCPServerConnection(port=0)
    try:
        assert conn.host == "localhost"
        assert conn.port == 0
        assert not conn.is_connected
    finally:
        # Always attempt to close connection/server to avoid socket leaks
        if conn.is_connected:
            await conn.close()
        else:
            srv = getattr(conn, "server", None)
            if srv is not None:
                srv.close()
                await srv.wait_closed()
        # Allow transport close callbacks to run before test ends
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_tcp_accept_message_flow():
    """Test TCP connection accept, message sending and receiving using an
    OS-assigned ephemeral port to avoid race conditions."""
    conn = TCPServerConnection(port=0)

    try:
        # Start listening but don't wait for a client yet
        await conn.start_listening()
        port = conn.port  # updated after start_listening (ephemeral resolved)

        # Connect client and send request while server waits in parallel
        wait_task = asyncio.create_task(conn.wait_for_client())
        reader, writer = await asyncio.open_connection("localhost", port)
        request = {"seq": 1, "type": "request", "command": "test"}
        content = json.dumps(request).encode("utf-8")
        header = f"Content-Length: {len(content)}\r\n\r\n".encode()
        writer.write(header + content)
        await writer.drain()

        # Ensure server registered the client
        await wait_task
        assert conn.is_connected

        # Server reads the message
        msg = await conn.read_message()
        assert msg == request

        # Server responds
        response = {
            "seq": 2,
            "type": "response",
            "request_seq": 1,
            "success": True,
            "command": "test",
        }
        await conn.write_message(response)

        # Client reads response headers
        headers = {}
        while True:
            line = await reader.readline()
            line = line.decode("utf-8").strip()
            if not line:
                break
            key, value = line.split(":", 1)
            headers[key.strip()] = value.strip()

        content_length = int(headers["Content-Length"])
        content = await reader.readexactly(content_length)
        got_response = json.loads(content.decode("utf-8"))
        assert got_response == response

        writer.close()
        await writer.wait_closed()
        # Allow server-side reader/handler tasks to observe EOF before closing
        await asyncio.sleep(0)
    finally:
        # Always attempt to close connection/server to avoid socket leaks
        try:
            if conn.is_connected:
                await conn.close()
            else:
                srv = getattr(conn, "server", None)
                if srv is not None:
                    srv.close()
                    await srv.wait_closed()
        except Exception:
            pass  # Best effort cleanup
        # Allow transport close callbacks to run before test ends
        await asyncio.sleep(0.01)  # Slightly longer to ensure cleanup


# ---------------------------------------------------------------------------
# Named Pipe Connection Tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.name != "nt",
    reason=("Named pipe tests only run on Windows"),
)
def test_named_pipe_initialization(pipe_name):
    """Test named pipe initialization."""
    conn = NamedPipeServerConnection(pipe_name=pipe_name)
    assert conn.pipe_name == pipe_name
    assert conn.pipe_path.endswith(pipe_name)
    assert not conn.is_connected


@pytest.mark.skipif(
    os.name != "nt",
    reason=("Named pipe tests only run on Windows"),
)
@mock.patch("asyncio.start_server")
def test_named_pipe_mocked_initialization(mock_start_server, pipe_name):
    """Test named pipe initialization with mocked server."""
    # Mock the asyncio.start_server so we don't actually create a pipe
    mock_server = mock.MagicMock()
    mock_start_server.return_value = mock_server

    conn = NamedPipeServerConnection(pipe_name=pipe_name)

    # Verify connection properties
    assert conn.pipe_name == pipe_name
    assert conn.pipe_path.endswith(pipe_name)
    assert not conn.is_connected
