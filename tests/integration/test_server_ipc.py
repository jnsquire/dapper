from __future__ import annotations

import asyncio
import os
from unittest.mock import Mock
from unittest.mock import patch

import pytest

import dapper.adapter.server as server_module
from dapper.adapter.server import DebugAdapterServer
from dapper.adapter.server import PyDebugger
from dapper.ipc import ipc_context
from tests.integration.test_server import AsyncCallRecorder
from tests.mocks import MockConnection


def test_write_command_to_channel_ipc_pipe_text():
    p = PyDebugger(server=Mock())
    calls = []

    class PipeConn:
        def send(self, s):
            calls.append(("send", s))

    p.ipc.enable_pipe_connection(PipeConn(), binary=False)

    p.ipc.write_command("abc")
    # Break down assertion (PT018): verify list populated, action name, and payload
    assert calls, "Expected at least one call to pipe send"
    assert calls[0][0] == "send", f"Unexpected method {calls[0][0]!r}"
    assert calls[0][1] == "abc", f"Unexpected payload {calls[0][1]!r}"


def test_write_command_to_channel_ipc_pipe_binary():
    p = PyDebugger(server=Mock())
    calls = []

    class PipeConn:
        def send_bytes(self, b):
            calls.append(("send_bytes", b))

    # Use new PyDebugger helper to enable pipe-style binary IPC
    p.ipc.enable_pipe_connection(PipeConn(), binary=True)

    p.ipc.write_command("xyz")
    assert calls, "Expected at least one call to pipe send_bytes"
    assert calls[0][0] == "send_bytes", f"Unexpected method {calls[0][0]!r}"


def test_write_command_to_channel_ipc_socket_text():
    p = PyDebugger(server=Mock())
    calls = []

    class WFile:
        def write(self, s):
            calls.append(("write", s))

        def flush(self):
            calls.append(("flush", None))

    # Use the new helper to register a writer-only transport for tests
    p.ipc.enable_wfile(WFile(), binary=False)

    p.ipc.write_command("bbb")
    assert any("bbb" in c[1] for c in calls if c[0] == "write")


def test_write_command_to_channel_requires_ipc():
    """Test that ipc.write_command raises RuntimeError when IPC is not configured."""
    p = PyDebugger(server=Mock())

    p.ipc.disable()
    p.process = Mock()

    # Should raise RuntimeError since IPC is mandatory
    with pytest.raises(RuntimeError, match="IPC is required"):
        p.ipc.write_command("kkk")


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

    # Verify the debugger was called with the expected kwargs
    # Positional args are program, args (list), stop_on_entry, no_debug
    # IPC is now always enabled, so use_ipc is no longer passed
    assert len(mock_debugger.launch.calls) == 1
    args, kwargs = mock_debugger.launch.calls[0]
    assert args == ("test.py", [], False, False)
    assert kwargs.get("ipc_transport") == "pipe"
    assert kwargs.get("ipc_pipe_name") == r"\\.\pipe\dapper-test-pipe"
    assert kwargs.get("use_binary_ipc") is True


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="Named pipes apply to Windows only")
async def test_launch_generates_pipe_name_when_missing(monkeypatch):
    captured_args: list[str] = []

    def fake_start(self, debug_args):
        captured_args.clear()
        captured_args.extend(debug_args)
        self.process = Mock(pid=4242)

    class DummyThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=False):
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}
            self.daemon = daemon

        def start(self):
            if self._target is not None:
                self._target(*self._args, **self._kwargs)

    class DummyServer:
        def __init__(self):
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
    debugger = server_module.PyDebugger(DummyServer(), loop)
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
    monkeypatch.setattr(server_module.threading, "Thread", DummyThread)

    await debugger.launch(
        "test.py",
        args=[],
        ipc_transport="pipe",  # IPC is now always enabled
    )

    pipe_listener = debugger.ipc.pipe_listener
    assert pipe_listener is not None, "Expected a named pipe listener to be created"
    generated_pipe = getattr(pipe_listener, "address", None)
    assert isinstance(generated_pipe, str)
    assert generated_pipe.startswith(r"\\.\pipe\dapper-")
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

    # Verify debugger.launch received the forwarded flag
    # IPC is now always enabled, so use_ipc is no longer passed
    assert len(mock_debugger.launch.calls) == 1
    _args, kwargs = mock_debugger.launch.calls[0]
    assert kwargs.get("use_binary_ipc") is True
    assert kwargs.get("ipc_transport") == "tcp"
