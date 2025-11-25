"""
Communication helpers for the debug launcher.
"""

from __future__ import annotations

import json
import logging

from dapper.ipc.ipc_binary import pack_frame
from dapper.shared.debug_shared import state

send_logger = logging.getLogger("dapper.launcher.debug_launcher.send")


def send_debug_message(event_type: str, **kwargs) -> None:
    """
    Send a debug message to the debug adapter via IPC.
    Binary framing is the default transport.
    """
    state.require_ipc()
    state.require_ipc_write_channel()

    message = {"event": event_type}
    message.update(kwargs)

    # Binary IPC (default)
    payload = json.dumps(message).encode("utf-8")
    frame = pack_frame(1, payload)

    # Prefer pipe conn if available
    conn = state.ipc_pipe_conn
    if conn is not None:
        conn.send_bytes(frame)
        return

    wfile = state.ipc_wfile
    assert wfile is not None  # guaranteed by require_ipc_write_channel
    wfile.write(frame)  # type: ignore[arg-type]
    wfile.flush()  # type: ignore[call-arg]
