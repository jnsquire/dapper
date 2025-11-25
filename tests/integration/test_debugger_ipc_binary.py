from __future__ import annotations

import asyncio
import os
import socket as _socket
from typing import Any

import pytest

from dapper.adapter.server import PyDebugger


class _StubServer:
    async def send_event(self, _event: str, _payload: dict[str, Any] | None = None) -> None:
        return


@pytest.mark.asyncio
async def test_launcher_args_include_ipc_binary_flag_when_requested():
    """When use_binary_ipc is True, PyDebugger should add --ipc-binary to argv."""
    # Capture the debug command that would be used to start the debuggee
    captured_args: list[list[str]] = []

    def _capture_start(self: PyDebugger, debug_args: list[str]) -> None:  # type: ignore[override]  # noqa: ARG001
        captured_args.append(list(debug_args))

    loop = asyncio.get_event_loop()
    dbg = PyDebugger(_StubServer(), loop)
    dbg._test_mode = True  # type: ignore[attr-defined]
    # Patch at class level so descriptor binding supplies `self`
    original = PyDebugger._start_debuggee_process  # type: ignore[attr-defined]
    PyDebugger._start_debuggee_process = _capture_start  # type: ignore[assignment]

    # Choose a transport that is supported on this OS to get IPC args populated
    ipc_transport = (
        "pipe" if os.name == "nt" else ("unix" if hasattr(_socket, "AF_UNIX") else "tcp")
    )

    try:
        await dbg.launch(
            program="sample.py",
            args=[],
            stop_on_entry=False,
            no_debug=False,
            in_process=False,
            use_binary_ipc=True,  # IPC is now always enabled
            ipc_transport=ipc_transport,
        )
    finally:
        PyDebugger._start_debuggee_process = original  # type: ignore[assignment]

    # Wait briefly for background starter thread to run
    for _ in range(20):
        if captured_args:
            break
        await asyncio.sleep(0.05)
    assert captured_args, "debuggee process was not started"
    argv = captured_args[0]

    # Verify the binary flag is present
    assert "--ipc-binary" in argv

    # Also sanity check that the base --ipc args exist
    assert "--ipc" in argv

    await dbg.shutdown()
