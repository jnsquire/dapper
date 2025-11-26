from __future__ import annotations

import asyncio
import os
import socket as _socket
from typing import Any

import pytest

from dapper.adapter.server import PyDebugger


class _StubServer:
    async def send_event(self, _event: str, _payload: dict[str, Any]) -> None:
        """Minimal stub: debugger.launch awaits this."""
        return


@pytest.mark.asyncio
async def test_unix_is_default_on_non_windows():
    """On non-Windows, default transport is 'unix' (IPC is now always enabled)."""

    if os.name == "nt":
        pytest.skip("UNIX sockets not default on Windows")
    if not hasattr(_socket, "AF_UNIX"):
        pytest.skip("AF_UNIX not available on this platform")

    # Capture the debug command that would be used to start the debuggee
    captured_args: list[list[str]] = []

    # _start_debuggee_process is called from a thread and invoked as a
    # normal function with a single argument (debug_args). Define the
    # replacement to accept one positional argument so it's compatible with
    # both direct calls and bound/unbound situations.
    def _capture_start(debug_args: list[str]) -> None:
        captured_args.append(list(debug_args))

    # Build debugger with a stub server and patch the process starter
    loop = asyncio.get_event_loop()
    dbg = PyDebugger(_StubServer(), loop)
    # Run in test mode so launch uses a real thread instead of run_in_executor
    dbg._test_mode = True  # type: ignore[attr-defined]
    # Replace the method on this instance to capture args
    dbg._start_debuggee_process = _capture_start  # type: ignore[assignment]

    await dbg.launch(
        program="sample.py",
        args=[],
        stop_on_entry=False,
        no_debug=False,
        in_process=False,
        ipc_transport=None,  # IPC is now always enabled, let it default
    )

    # We should have exactly one start invocation captured
    assert captured_args, "debuggee process was not started"
    argv = captured_args[0]

    # Find the IPC args and verify transport is unix with a path
    assert "--ipc" in argv
    idx = argv.index("--ipc")
    assert argv[idx + 1] == "unix"
    # Ensure we provided the unix path argument
    assert "--ipc-path" in argv
    path_idx = argv.index("--ipc-path")
    assert path_idx + 1 < len(argv)
    assert argv[path_idx + 1].endswith(".sock")
    # Clean up any IPC listener resources created by launch to avoid
    # leaking sockets that are detected by strict test runs.
    await dbg.shutdown()
