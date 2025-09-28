from __future__ import annotations

import asyncio
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from dapper.server import DebugAdapterServer
from dapper.server import PyDebugger
from tests.test_server import AsyncCallRecorder
from tests.test_server import MockConnection


def test_write_command_to_channel_ipc_pipe_text():
    p = PyDebugger(server=None)
    calls = []

    class PipeConn:
        def send(self, s):
            calls.append(("send", s))

    p.enable_ipc_pipe_connection(PipeConn(), binary=False)

    p._write_command_to_channel("abc")
    # Break down assertion (PT018): verify list populated, action name, and payload marker
    assert calls, "Expected at least one call to pipe send"
    assert calls[0][0] == "send", f"Unexpected method {calls[0][0]!r}"
    assert "DBGCMD:abc" in calls[0][1], f"Missing DBGCMD marker in {calls[0][1]!r}"


def test_write_command_to_channel_ipc_pipe_binary():
    p = PyDebugger(server=None)
    calls = []

    class PipeConn:
        def send_bytes(self, b):
            calls.append(("send_bytes", b))

    # Use new PyDebugger helper to enable pipe-style binary IPC
    p.enable_ipc_pipe_connection(PipeConn(), binary=True)

    p._write_command_to_channel("xyz")
    assert calls, "Expected at least one call to pipe send_bytes"
    assert calls[0][0] == "send_bytes", f"Unexpected method {calls[0][0]!r}"


def test_write_command_to_channel_ipc_wfile_text():
    p = PyDebugger(server=None)
    calls = []

    class WFile:
        def write(self, s):
            calls.append(("write", s))

        def flush(self):
            calls.append(("flush", None))

    # Use the new helper to register a writer-only transport for tests
    p.enable_ipc_wfile(WFile(), binary=False)

    p._write_command_to_channel("bbb")
    assert any("DBGCMD:bbb" in c[1] for c in calls if c[0] == "write")


def test_write_command_to_channel_fallback_to_stdin():
    p = PyDebugger(server=None)

    class Stdin:
        def __init__(self):
            self.written = []

        def write(self, s):
            self.written.append(s)

        def flush(self):
            pass

    class Proc:
        def __init__(self):
            self.stdin = Stdin()

    p.disable_ipc()
    mock_stdin = Mock()
    p.process = Mock()
    p.process.stdin = mock_stdin

    p._write_command_to_channel("kkk")

    # Verify that stdin.write was called with a string containing the DBGCMD marker
    assert any("DBGCMD:kkk" in call.args[0] for call in mock_stdin.write.call_args_list)


@pytest.mark.asyncio
@patch("dapper.server.PyDebugger")
async def test_launch_forwards_ipc_pipe_kwargs(mock_debugger_class):
    mock_debugger = mock_debugger_class.return_value
    mock_debugger.launch = AsyncCallRecorder(return_value=None)
    mock_debugger.shutdown = AsyncCallRecorder(return_value=None)

    mock_connection = MockConnection()
    loop = asyncio.get_event_loop()
    server = DebugAdapterServer(mock_connection, loop)
    server.debugger = mock_debugger

    mock_connection.add_request(
        "launch",
        {
            "program": "test.py",
            "useIpc": True,
            "ipcTransport": "pipe",
            "ipcPipeName": r"\\.\pipe\dapper-test-pipe",
        },
        seq=1,
    )

    server_task = asyncio.create_task(server.start())
    await asyncio.wait_for(server_task, timeout=1.0)

    # Verify the debugger was called with the expected kwargs
    # Positional args are program, args (list), stop_on_entry, no_debug
    assert len(mock_debugger.launch.calls) == 1
    args, kwargs = mock_debugger.launch.calls[0]
    assert args == ("test.py", [], False, False)
    assert kwargs.get("use_ipc") is True
    assert kwargs.get("ipc_transport") == "pipe"
    assert kwargs.get("ipc_pipe_name") == r"\\.\pipe\dapper-test-pipe"


@pytest.mark.asyncio
@patch("dapper.server.PyDebugger")
async def test_launch_forwards_binary_ipc_flag(mock_debugger_class):
    """Server should forward useBinaryIpc to debugger.launch as use_binary_ipc."""
    mock_debugger = mock_debugger_class.return_value
    mock_debugger.launch = AsyncCallRecorder(return_value=None)
    mock_debugger.shutdown = AsyncCallRecorder(return_value=None)

    mock_connection = MockConnection()
    loop = asyncio.get_event_loop()
    server = DebugAdapterServer(mock_connection, loop)
    server.debugger = mock_debugger

    # Provide a launch request that enables IPC and binary IPC
    mock_connection.add_request(
        "launch",
        {
            "program": "test.py",
            "useIpc": True,
            "useBinaryIpc": True,
            "ipcTransport": "tcp",
            "ipcHost": "127.0.0.1",
            "ipcPort": 5001,
        },
        seq=1,
    )

    server_task = asyncio.create_task(server.start())
    await asyncio.wait_for(server_task, timeout=1.0)

    # Verify debugger.launch received the forwarded flag
    assert len(mock_debugger.launch.calls) == 1
    _args, kwargs = mock_debugger.launch.calls[0]
    assert kwargs.get("use_ipc") is True
    assert kwargs.get("use_binary_ipc") is True
