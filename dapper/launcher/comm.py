"""
Communication helpers for the debug launcher.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sys

from dapper.ipc.ipc_binary import pack_frame
from dapper.shared.debug_shared import state

send_logger = logging.getLogger("dapper.launcher.debug_launcher.send")


def send_debug_message(event_type: str, **kwargs) -> None:
    """
    Send a debug message to the debug adapter.
    These are prefixed with DBGP: to distinguish them from regular output.
    """
    message = {"event": event_type}
    message.update(kwargs)
    if state.ipc_enabled:
        # Binary IPC when enabled
        if getattr(state, "ipc_binary", False):
            payload = json.dumps(message).encode("utf-8")
            frame = pack_frame(1, payload)
            # Prefer pipe conn if available
            conn = state.ipc_pipe_conn
            if conn is not None:
                conn.send_bytes(frame)

            wfile = state.ipc_wfile
            if wfile is not None:
                with contextlib.suppress(Exception):
                    wfile.write(frame)  # type: ignore[arg-type]
                    wfile.flush()  # type: ignore[call-arg]
                    return

        # Text IPC fallback
        if state.ipc_wfile is not None:
            try:
                state.ipc_wfile.write(f"DBGP:{json.dumps(message)}\n")
                state.ipc_wfile.flush()
            except Exception:
                # Fall back to logger
                pass
            else:
                return
    send_logger.debug(json.dumps(message))
    with contextlib.suppress(Exception):
        sys.stdout.flush()
