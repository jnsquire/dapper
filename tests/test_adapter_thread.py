from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest

import dapper.adapter_thread as adapter_thread_mod


class _FakeTCPConnection:
    def __init__(self, host: str = "localhost", port: int = 4711) -> None:
        self.host = host
        self.port = port
        self._started = False

    async def start_listening(self) -> None:
        # Simulate binding to an ephemeral port
        self._started = True
        # Assign a deterministic test port so assertions are stable
        self.port = 55555 if self.port in (0, None) else self.port

    async def accept(self) -> None:
        # Not used by our fake server; no-op
        await asyncio.sleep(0)

    async def close(self) -> None:
        # No resources to close in fake
        await asyncio.sleep(0)


class _FakePipeConnection:
    def __init__(self, pipe_name: str) -> None:
        self.pipe_name = pipe_name

    async def accept(self) -> None:  # pragma: no cover - not used in tests
        await asyncio.sleep(0)


class _FakeDebugger:
    # Minimal stub to satisfy BreakpointController construction
    pass


class _FakeServer:
    def __init__(self, connection: Any, loop: asyncio.AbstractEventLoop | None = None) -> None:
        self.connection = connection
        self.loop = loop or asyncio.get_event_loop()
        self.debugger = _FakeDebugger()
        self._run_event = asyncio.Event()
        self._stopped = False

    async def start(self) -> None:
        # Block until stop is called, simulating a running server
        await self._run_event.wait()

    async def stop(self) -> None:
        self._stopped = True
        self._run_event.set()
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_start_stop_tcp(monkeypatch):
    # Patch dependencies inside module under test
    monkeypatch.setattr(adapter_thread_mod, "TCPServerConnection", _FakeTCPConnection)
    monkeypatch.setattr(adapter_thread_mod, "DebugAdapterServer", _FakeServer)

    runner = adapter_thread_mod.AdapterThread(connection_type="tcp", host="127.0.0.1", port=None)

    # Request the port future before starting; it should resolve after start
    fut = runner.get_port_future()
    assert not fut.done()

    runner.start()

    # Wait for port to be published by the adapter thread
    result_port = await asyncio.get_running_loop().run_in_executor(
        None, fut.result, 2.0  # 2 seconds timeout via concurrent Future API
    )
    assert result_port == 55555

    # Ensure thread and loop are active
    assert isinstance(runner.loop, asyncio.AbstractEventLoop)
    assert isinstance(runner.server, _FakeServer)
    assert isinstance(runner._thread, threading.Thread)
    assert runner._thread.is_alive()

    # Stop and join
    runner.stop(join=True, timeout=5.0)
    assert runner._thread is None


def test_idempotent_start(monkeypatch):
    monkeypatch.setattr(adapter_thread_mod, "TCPServerConnection", _FakeTCPConnection)
    monkeypatch.setattr(adapter_thread_mod, "DebugAdapterServer", _FakeServer)

    runner = adapter_thread_mod.AdapterThread(connection_type="tcp", port=None)
    runner.start()
    first_thread = runner._thread
    # Calling start again should be a no-op
    runner.start()
    assert runner._thread is first_thread
    runner.stop()


def test_pipe_connection_selection(monkeypatch):
    captured: dict[str, str] = {}

    class _CapturingPipe(_FakePipeConnection):
        def __init__(self, pipe_name: str) -> None:
            captured["pipe_name"] = pipe_name
            super().__init__(pipe_name)

    monkeypatch.setattr(adapter_thread_mod, "NamedPipeServerConnection", _CapturingPipe)
    monkeypatch.setattr(adapter_thread_mod, "DebugAdapterServer", _FakeServer)

    # Explicit pipe name provided
    runner = adapter_thread_mod.AdapterThread(connection_type="pipe", pipe_name="my_debug_pipe")
    runner.start()
    assert captured.get("pipe_name") == "my_debug_pipe"
    runner.stop()


@pytest.mark.asyncio
async def test_port_future_resolves_when_server_created(monkeypatch):
    monkeypatch.setattr(adapter_thread_mod, "TCPServerConnection", _FakeTCPConnection)
    monkeypatch.setattr(adapter_thread_mod, "DebugAdapterServer", _FakeServer)

    runner = adapter_thread_mod.AdapterThread(connection_type="tcp", port=None)
    # Get future before starting to ensure lazy creation path is covered
    fut = runner.get_port_future()
    assert not fut.done()

    runner.start()

    # Future should resolve to 55555 after the adapter thread starts listening
    result_port = await asyncio.get_running_loop().run_in_executor(None, fut.result, 2.0)
    assert result_port == 55555
    runner.stop()
