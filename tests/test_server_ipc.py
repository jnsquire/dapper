from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from dapper.server import DebugAdapterServer
from tests.test_server import AsyncCallRecorder
from tests.test_server import MockConnection


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
