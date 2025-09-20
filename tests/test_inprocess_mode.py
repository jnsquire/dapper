from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from dapper.connection import ConnectionBase
from dapper.server import DebugAdapterServer


class MockConnection(ConnectionBase):
    def __init__(self) -> None:
        super().__init__()
        self.read_queue: list[dict] = []
        self.written_messages: list[dict] = []

    async def accept(self) -> None:
        # Immediately mark as connected for the server loop
        self.is_connected = True

    async def close(self) -> None:
        # Mark as disconnected; nothing else to clean up
        self.is_connected = False

    async def read_message(self) -> dict | None:
        if self.read_queue:
            return self.read_queue.pop(0)
        return None

    async def write_message(self, message: dict) -> None:
        self.written_messages.append(message)

    def add_request(self, command: str, arguments: dict | None = None, seq: int = 1) -> None:
        self.read_queue.append(
            {
                "seq": seq,
                "type": "request",
                "command": command,
                "arguments": arguments or {},
            }
        )


@pytest.mark.asyncio
async def test_launch_inprocess_sends_process_event():
    """
    Launch with in_process=True should send 'process' event and not
    spawn a subprocess.
    """
    # Prepare server with mock connection
    conn = MockConnection()
    loop = asyncio.get_event_loop()
    server = DebugAdapterServer(conn, loop)

    # Patch create_subprocess_exec to detect unintended subprocess launches
    with patch("asyncio.create_subprocess_exec") as create_proc:
        # Queue initialize and launch requests
        conn.add_request("initialize", seq=1)
        conn.add_request("launch", {"program": "test.py", "inProcess": True}, seq=2)
        conn.add_request("configurationDone", seq=3)

        task = asyncio.create_task(server.start())
        # Allow loop to process queued messages briefly
        await asyncio.sleep(0.1)
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        else:
            # If already finished naturally, just await it
            await task

        # Ensure no subprocess was attempted
        assert create_proc.call_count == 0

    # Verify a 'process' event was sent
    events = [
        m
        for m in conn.written_messages
        if m.get("type") == "event" and m.get("event") == "process"
    ]
    assert events, "Expected a 'process' event in in-process mode"


@pytest.mark.asyncio
async def test_inprocess_variables_bridge():
    """
    get_variables should call bridge with _filter/_start/_count and
    return values.
    """
    # Prepare a debugger instance directly to test variables path
    conn = MockConnection()
    loop = asyncio.get_event_loop()
    server = DebugAdapterServer(conn, loop)

    # Use a real PyDebugger but patch its _inproc with a fake bridge
    debugger = server.debugger
    debugger.in_process = True

    class FakeBridge:
        def variables(self, var_ref, *, _filter=None, _start=None, _count=None):
            # record call for assertion
            FakeBridge.called = (var_ref, _filter, _start, _count)
            return {"variables": [{"name": "x", "value": "1", "variablesReference": 0}]}

    fake = FakeBridge()
    debugger._inproc = fake  # type: ignore[attr-defined]

    result = await debugger.get_variables(123, filter_type="indexed", start=1, count=10)

    assert getattr(FakeBridge, "called", None) == (123, "indexed", 1, 10)
    assert isinstance(result, list)
    assert result
    assert result[0]["name"] == "x"
