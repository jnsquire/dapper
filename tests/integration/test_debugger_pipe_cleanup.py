from __future__ import annotations

import os
from typing import Any
from unittest.mock import Mock

import pytest

from dapper.ipc.ipc_context import IPCContext


class _StubServer:
    async def send_event(self, _event: str, _payload: dict[str, Any]) -> None:
        return


@pytest.mark.asyncio
async def test_pipe_endpoints_closed_on_cleanup() -> None:
    """
    Ensure pipe endpoints are closed during IPC cleanup on Windows.

        Skips on non-Windows platforms.
    """
    if os.name != "nt":
        pytest.skip("Named pipe cleanup test only applicable on Windows")

    # Create mocks for pipe connection and listener
    conn = Mock()
    listener = Mock()
    
    # Use the legacy IPCContext interface directly for this test
    # since we're testing the low-level cleanup behavior
    ipc_context = IPCContext()
    ipc_context.set_pipe_listener(listener)
    ipc_context.enable_pipe_connection(conn, binary=False)

    # Test cleanup directly on the IPCContext
    ipc_context.cleanup()

    # Verify close was called on both
    conn.close.assert_called_once()
    listener.close.assert_called_once()
