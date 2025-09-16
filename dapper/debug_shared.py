"""
Shared debug adapter state and utilities to break circular imports.
"""

import contextlib
import json
import logging
import sys
import threading
from types import SimpleNamespace

MAX_STRING_LENGTH = 1000
VAR_REF_TUPLE_SIZE = 2

send_logger = logging.getLogger(__name__ + ".send")
logger = logging.getLogger(__name__)

state = SimpleNamespace(
    debugger=None,
    stop_at_entry=False,
    no_debug=False,
    command_queue=[],
    command_lock=threading.Lock(),
    is_terminated=False,
    ipc_enabled=False,
    ipc_sock=None,
    ipc_rfile=None,
    ipc_wfile=None,
    handle_debug_command=None,  # Set by debug_adapter_comm
)


def send_debug_message(event_type: str, **kwargs) -> None:
    message = {"event": event_type}
    message.update(kwargs)
    if state.ipc_enabled and state.ipc_wfile is not None:
        try:
            state.ipc_wfile.write(f"DBGP:{json.dumps(message)}\n")
            state.ipc_wfile.flush()
        except Exception:
            pass
        else:
            return
    send_logger.debug(json.dumps(message))
    with contextlib.suppress(Exception):
        sys.stdout.flush()
