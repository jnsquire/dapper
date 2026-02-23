from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from typing import Any

import pytest

import dapper.adapter.adapter_thread as adapter_thread_mod


class PortTimeoutError(Exception):
    def __init__(self) -> None:
        super().__init__("Timed out waiting for port assignment")


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

    # Set up port listener BEFORE starting to avoid race
    test_loop = asyncio.get_running_loop()
    port_future: asyncio.Future[int] = test_loop.create_future()

    def on_port(port: int) -> None:
        def _set() -> None:
            if not port_future.done():
                port_future.set_result(port)

        test_loop.call_soon_threadsafe(_set)

    runner.on_port_assigned.add_listener(on_port)

    try:
        runner.start()

        # Wait for port to be published by the adapter thread
        result_port = await asyncio.wait_for(port_future, timeout=2.0)
        assert result_port == 55555

        # Ensure thread is active
        assert isinstance(runner._thread, threading.Thread)
        assert runner._thread.is_alive()
    finally:
        runner.on_port_assigned.remove_listener(on_port)
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

    test_loop = asyncio.get_running_loop()
    port_future: asyncio.Future[int] = test_loop.create_future()

    def on_port_assigned(port):
        def _set() -> None:
            if not port_future.done():
                port_future.set_result(port)

        test_loop.call_soon_threadsafe(_set)

    runner = adapter_thread_mod.AdapterThread(connection_type="tcp", port=None)
    runner.on_port_assigned.add_listener(on_port_assigned)

    try:
        runner.start()
        port = await asyncio.wait_for(port_future, timeout=5.0)
        assert port == 55555, f"Expected port 55555, got {port}"
    except asyncio.TimeoutError:
        pytest.fail("Timeout waiting for port assignment")
    finally:
        if hasattr(runner, "on_port_assigned"):
            runner.on_port_assigned.remove_listener(on_port_assigned)

        if hasattr(runner, "stop"):
            try:
                runner.stop(join=True, timeout=1.0)
            except Exception:
                # If stop fails, try to clean up resources directly
                if hasattr(runner, "_thread") and runner._thread is not None:
                    runner._thread.join(timeout=0.5)
                if (
                    hasattr(runner, "_loop")
                    and runner._loop is not None
                    and not runner._loop.is_closed()
                ):
                    runner._loop.call_soon_threadsafe(runner._loop.stop)

            # Clear any references to help with garbage collection
            if hasattr(runner, "_thread"):
                runner._thread = None
            if hasattr(runner, "_loop"):
                runner._loop = None

        # Cancel the future if it's still pending
        if not port_future.done():
            port_future.cancel()


def test_cancel_thread_futures_cancelled_future_does_not_raise():
    """Verify that AdapterThread._cancel_thread_futures handles cancelled
    futures without raising an error.
    """
    # Create an adapter runner instance but do not start it. We just need the
    # instance to call the private helper.
    runner = adapter_thread_mod.AdapterThread(connection_type="tcp", port=None)

    # Submit a long running task so we can cancel it
    # Use a bare Future so cancellation will reliably mark it cancelled
    fut = concurrent.futures.Future()
    # Append to internal futures list
    runner._thread_futures.append(fut)

    # Call the private helper with low timeout - it should cancel the future
    # and not raise even if the future is still running or cancelled
    runner._cancel_thread_futures(timeout=0.01)

    # After cancellation attempt the future should be either cancelled or finished
    assert fut.cancelled() or fut.done()
