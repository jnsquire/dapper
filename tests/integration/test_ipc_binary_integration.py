from __future__ import annotations

import asyncio
import json
import socket
from typing import Any

import pytest

from dapper.adapter.server import DebugAdapterServer
from dapper.adapter.server import PyDebugger
from dapper.config import DapperConfig
from dapper.config import DebuggeeConfig
from dapper.config import IPCConfig
from dapper.ipc.ipc_binary import pack_frame
from tests.mocks import MockConnection


class _CapturingServer(DebugAdapterServer):
    """Stub server for testing that captures events."""
    
    def __init__(self) -> None:
        # Initialize parent with mock connection
        super().__init__(MockConnection(), asyncio.get_event_loop())
        self.events: list[dict[str, Any]] = []
    
    async def send_event(self, event_name: str, body: dict[str, Any] | None = None) -> None:
        self.events.append({"event": event_name, "body": body or {}})
    
    async def send_message(self, message: dict[str, Any]) -> None:
        # Stub implementation
        pass
    
    def spawn_threadsafe(self, target: Any, *args: Any, **kwargs: Any) -> None:
        # Stub implementation
        pass


@pytest.mark.asyncio
async def test_binary_ipc_frame_roundtrip_exited_event():
    """Exercise the binary IPC read loop by sending an 'exited' event frame.

    This avoids starting the real launcher by connecting to the debugger's
    ephemeral TCP listener and writing a single binary frame that carries the
    JSON debug message. The debugger should parse it and emit corresponding
    DAP events to the server.
    """
    # Use TCP for reliability across environments
    transport = "tcp"

    loop = asyncio.get_event_loop()
    cap = _CapturingServer()
    dbg = PyDebugger(cap, loop)
    dbg._test_mode = True  # type: ignore[attr-defined]
    # Prevent spawning a real debuggee; IPC acceptor is still started below.
    # Patch at the class level so the bound method receives `self` correctly
    # when invoked from a background thread with (debug_args,) parameters.

    def _noop_start(_self: PyDebugger, _args: list[str]) -> None:  # type: ignore[override]
        return

    original = PyDebugger._start_debuggee_process  # type: ignore[attr-defined]
    PyDebugger._start_debuggee_process = _noop_start  # type: ignore[assignment]

    try:
        config = DapperConfig(
            debuggee=DebuggeeConfig(
                program="sample.py",
                args=[],
                stop_on_entry=False,
                no_debug=False,
            ),
            ipc=IPCConfig(
                use_binary=True,
                transport=transport,
            ),
        )
        await dbg.launch(config)
    finally:
        PyDebugger._start_debuggee_process = original  # type: ignore[assignment]

    # Grab listener address and connect as the debuggee
    listen = dbg.ipc.listen_sock
    assert listen is not None, "IPC listen socket not created"
    host, port = listen.getsockname()

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3)
    s.connect((host, port))
    
    # Give the server a moment to accept the connection
    await asyncio.sleep(0.1)

    try:
        payload = json.dumps({"event": "exited", "exitCode": 0}).encode("utf-8")
        frame = pack_frame(1, payload)  # kind=1 (event)
        s.sendall(frame)
    finally:
        # Let the server consume the frame, then close our side
        s.close()

    # Give the background accept/read thread a moment to process and schedule
    # adapter events on the loop
    for _ in range(40):
        if any(e.get("event") == "exited" for e in cap.events):
            break
        await asyncio.sleep(0.05)

    # We should see an 'exited' event followed by a 'terminated'
    names = [e.get("event") for e in cap.events]
    assert "exited" in names
    assert "terminated" in names

    await dbg.shutdown()
