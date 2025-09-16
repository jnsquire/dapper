from __future__ import annotations

import asyncio
import os
import socket as _socket
from typing import TYPE_CHECKING
from typing import Any

import pytest

from dapper.debugger import PyDebugger

if TYPE_CHECKING:
    from pathlib import Path


class _StubServer:
    async def send_event(self, _event: str, _payload: dict[str, Any]) -> None:
        return


@pytest.mark.asyncio
async def test_unix_socket_path_is_removed_on_cleanup(
    tmp_path: Path,
) -> None:
    """Ensure UNIX socket path is unlinked during IPC cleanup.

    Skips on Windows or platforms without AF_UNIX.
    """
    if os.name == "nt":
        pytest.skip("UNIX socket cleanup not applicable on Windows")
    if not hasattr(_socket, "AF_UNIX"):
        pytest.skip("AF_UNIX not available on this platform")

    loop = asyncio.get_event_loop()
    dbg = PyDebugger(_StubServer(), loop)

    # Create a fake unix socket path file to simulate listener side-effect
    name = f"dapper-test-{os.getpid()}.sock"
    unix_path = tmp_path / name
    unix_path.touch()

    # Sanity: file exists before cleanup
    assert unix_path.exists()

    # Set debugger's path and call the cleanup helper
    dbg._ipc_unix_path = unix_path  # type: ignore[attr-defined]
    dbg._cleanup_ipc_resources()

    # File should be removed
    assert not unix_path.exists(), "UNIX socket path should be unlinked"
