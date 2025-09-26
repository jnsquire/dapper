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
    dbg.ipc.pipe_conn = conn
    dbg.ipc.pipe_listener = listener

    # Call new IPC context cleanup (legacy alias removed)
    dbg.ipc.cleanup()

    # Verify close was called on both
    conn.close.assert_called_once()
    listener.close.assert_called_once()
