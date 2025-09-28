from __future__ import annotations

import asyncio
import os
from typing import Any
from unittest.mock import Mock

import pytest

from dapper.server import PyDebugger


class _StubServer:
    async def send_event(self, _event: str, _payload: dict[str, Any]) -> None:
        return


@pytest.mark.asyncio
async def test_pipe_endpoints_closed_on_cleanup() -> None:
    """Ensure pipe endpoints are closed during IPC cleanup on Windows.

    Skips on non-Windows platforms.
    """
    if os.name != "nt":
        pytest.skip("Named pipe cleanup test only applicable on Windows")

    loop = asyncio.get_event_loop()
    dbg = PyDebugger(_StubServer(), loop)

    # Create mocks for pipe connection and listener
    conn = Mock()
    listener = Mock()
    # Use helpers to register the listener and pipe connection
    dbg.set_ipc_pipe_listener(listener)
    dbg.enable_ipc_pipe_connection(conn, binary=False)

    # Use the debugger helper to perform IPC shutdown/cleanup
    dbg.disable_ipc()

    # Verify close was called on both
    conn.close.assert_called_once()
    listener.close.assert_called_once()
