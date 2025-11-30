from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock
from unittest.mock import Mock
from unittest.mock import patch

import pytest

import dapper.adapter.server as server_module
from dapper.adapter.server import DebugAdapterServer
from dapper.adapter.server import PyDebugger
from dapper.config import DapperConfig
from dapper.config import DebuggeeConfig
from dapper.config import IPCConfig
from dapper.ipc import ipc_context
from tests.integration.test_server import AsyncCallRecorder
from tests.mocks import MockConnection


@pytest.mark.asyncio
async def test_write_command_to_channel_ipc_pipe_text():
    """Test that IPCManager can send text messages."""
    p = PyDebugger(server=Mock())
    
    # Mock the connection to capture send_message calls
    mock_connection = AsyncMock()
    p.ipc._connection = mock_connection
    p.ipc._enabled = True
    
    # Test the new interface
    await p.ipc.send_message({"command": "test", "data": "abc"})
    
    # Verify the connection's write_message was called
    assert mock_connection.write_message.called, "Expected write_message to be called"
    call_args = mock_connection.write_message.call_args[0][0]
    assert call_args["command"] == "test"
    assert call_args["data"] == "abc"


@pytest.mark.asyncio
async def test_write_command_to_channel_ipc_pipe_binary():
    """Test that IPCManager can send binary messages."""
    p = PyDebugger(server=Mock())
    
    # Mock the connection to capture send_message calls
    mock_connection = AsyncMock()
    p.ipc._connection = mock_connection
    p.ipc._enabled = True
    
    # Test the new interface with binary data
    await p.ipc.send_message({"command": "test", "data": "xyz"})
    
    # Verify the connection's write_message was called
    assert mock_connection.write_message.called, "Expected write_message to be called"
    call_args = mock_connection.write_message.call_args[0][0]
    assert call_args["command"] == "test"
    assert call_args["data"] == "xyz"


@pytest.mark.asyncio
async def test_write_command_to_channel_ipc_socket_text():
    """Test that IPCManager can send messages through socket-like connections."""
    p = PyDebugger(server=Mock())
    
    # Mock the connection to capture send_message calls
    mock_connection = AsyncMock()
    p.ipc._connection = mock_connection
    p.ipc._enabled = True
    
    # Test the new interface
    await p.ipc.send_message({"command": "test", "data": "bbb"})
    
    # Verify the connection's write_message was called
    assert mock_connection.write_message.called, "Expected write_message to be called"
    call_args = mock_connection.write_message.call_args[0][0]
    assert call_args["command"] == "test"
    assert call_args["data"] == "bbb"


@pytest.mark.asyncio
async def test_write_command_to_channel_requires_ipc():
    """Test that IPCManager.send_message raises RuntimeError when IPC is not configured."""
    p = PyDebugger(server=Mock())

    # IPCManager starts disabled (no connection)
    with pytest.raises(RuntimeError, match="No IPC connection available"):
        await p.ipc.send_message({"test": "kkk"})


@pytest.mark.asyncio
@patch("dapper.adapter.server.PyDebugger")
async def test_launch_forwards_ipc_pipe_kwargs(mock_debugger_class):
    # Setup the mock debugger
    mock_debugger = mock_debugger_class.return_value
    mock_debugger.launch = AsyncCallRecorder(return_value=None)
    mock_debugger.shutdown = AsyncCallRecorder(return_value=None)

    # Create server with patched debugger
    with patch("dapper.adapter.server.PyDebugger", return_value=mock_debugger):
        mock_connection = MockConnection()
        loop = asyncio.get_event_loop()
        server = DebugAdapterServer(mock_connection, loop)

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

    # Verify the debugger was called with the expected config object
    assert len(mock_debugger.launch.calls) == 1
    args, kwargs = mock_debugger.launch.calls[0]
    config = args[0]  # First positional argument is the DapperConfig
    
    assert isinstance(config, DapperConfig)
    assert config.debuggee.program == "test.py"
    assert config.debuggee.args == []
    assert config.debuggee.stop_on_entry is False
    assert config.debuggee.no_debug is False
    assert config.ipc.transport == "pipe"
    assert config.ipc.pipe_name == r"\\.\pipe\dapper-test-pipe"
    assert config.ipc.use_binary is True


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="Named pipes apply to Windows only")
async def test_launch_generates_pipe_name_when_missing(monkeypatch):
    captured_args: list[str] = []

    def fake_start(self, debug_args):
        captured_args.clear()
        captured_args.extend(debug_args)
        self.process = Mock(pid=4242)

    class DummyThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=False, name=None):
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}
            self.daemon = daemon
            self.name = name

        def start(self):
            if self._target is not None:
                self._target(*self._args, **self._kwargs)
        
        def is_alive(self):
            return False

    class DummyServer(DebugAdapterServer):
        def __init__(self, loop):
            # Create a mock connection for the parent class
            mock_connection = Mock()
            mock_connection.send_request = Mock()
            mock_connection.send_response = Mock()
            mock_connection.send_event = Mock()
            super().__init__(mock_connection, loop)
            self._debugger = None
        
        async def send_event(self, *_args, **_kwargs):
            return None
        
        async def send_message(self, *_args, **_kwargs):
            return None
            
        def spawn_threadsafe(self, *_args, **_kwargs):
            return None
            
        @property
        def debugger(self):
            if self._debugger is None:
                self._debugger = server_module.PyDebugger(self, loop)
            return self._debugger

    loop = asyncio.get_event_loop()
    debugger = server_module.PyDebugger(DummyServer(loop), loop)
    debugger._test_mode = True  # type: ignore[attr-defined]

    monkeypatch.setattr(
        server_module.PyDebugger, "_start_debuggee_process", fake_start, raising=False
    )

    # Patch the IPC accept method to be a no-op (it would block waiting for connection)
    def _noop_ipc(_self, _handler):
        return None

    monkeypatch.setattr(
        ipc_context.IPCContext, "run_accept_and_read", _noop_ipc, raising=False
    )
    monkeypatch.setattr(ipc_context, "threading", type("threading", (), {"Thread": DummyThread}))

        
    config = DapperConfig(
        mode="launch",
        debuggee=DebuggeeConfig(
            program="test.py",
            args=[],
        ),
        ipc=IPCConfig(
            transport="pipe",
        ),
    )
    await debugger.launch(config)

    # In the new IPCManager, we check the connection instead of pipe_listener
    connection = debugger.ipc.connection
    assert connection is not None, "Expected an IPC connection to be created"
    # The connection should have pipe path information for pipe transport
    assert hasattr(connection, "pipe_path"), "Expected connection to have pipe_path attribute"
    generated_pipe = getattr(connection, "pipe_path", None)
    assert isinstance(generated_pipe, str)
    assert generated_pipe.startswith("\\\\.\\pipe\\dapper-")
    assert str(os.getpid()) in generated_pipe

    assert captured_args, "Expected debuggee launch args to be captured"
    assert "--ipc" in captured_args
    assert "--ipc-pipe" in captured_args
    ipc_index = captured_args.index("--ipc")
    assert captured_args[ipc_index + 1] == "pipe"
    pipe_arg_index = captured_args.index("--ipc-pipe")
    assert captured_args[pipe_arg_index + 1] == generated_pipe


@pytest.mark.asyncio
@patch("dapper.adapter.server.PyDebugger")
async def test_launch_forwards_binary_ipc_flag(mock_debugger_class):
    """

    from pathlib import Path

    # Add the project root to the Python path
    project_root = str(Path(__file__).parent.parent.parent)
    if project_root not in sys.path:

    Server should forward useBinaryIpc to debugger.launch as use_binary_ipc."""
    # Setup the mock debugger
    mock_debugger = mock_debugger_class.return_value
    mock_debugger.launch = AsyncCallRecorder(return_value=None)
    mock_debugger.shutdown = AsyncCallRecorder(return_value=None)

    # Create server with patched debugger
    with patch("dapper.adapter.server.PyDebugger", return_value=mock_debugger):
        mock_connection = MockConnection()
        loop = asyncio.get_event_loop()
        server = DebugAdapterServer(mock_connection, loop)

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

    # Verify debugger.launch received the config object
    assert len(mock_debugger.launch.calls) == 1
    args, kwargs = mock_debugger.launch.calls[0]
    config_arg = args[0]  # First positional argument (config)
    
    # Check that the config contains the expected IPC settings
    assert isinstance(config_arg, DapperConfig)
    assert config_arg.ipc.use_binary is True
    assert config_arg.ipc.transport == "tcp"
