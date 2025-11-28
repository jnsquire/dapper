"""
IPC receiver for debug adapter commands.

This module handles receiving and dispatching debug commands from the
IPC channel (socket or pipe) established between the debug adapter and
the debuggee process.
"""

from __future__ import annotations

import json
import logging
import traceback
from queue import Empty
from typing import Any
from typing import cast

from dapper.shared.command_handlers import COMMAND_HANDLERS
from dapper.shared.debug_shared import send_debug_message
from dapper.shared.debug_shared import state

logger = logging.getLogger(__name__)


class DapMappingProvider:
    """Provider that wraps the legacy COMMAND_HANDLERS mapping.

    Each handler is a callable taking (arguments) and optionally returning
    a response dict with a "success" field. If no dict is returned, the
    handler is assumed to have already sent messages.
    """

    def __init__(self, mapping):
        self._mapping = mapping

    def supported_commands(self):
        try:
            return set(self._mapping.keys())
        except Exception:
            return set()

    def can_handle(self, command: str) -> bool:
        return command in self._mapping

    def handle(self, command: str, arguments: dict[str, Any]):
        # The underlying mapping handlers only accept `arguments` so delegate
        # and translate their return shape to the protocol expected by
        # register_command_provider.
        func = self._mapping.get(command)
        if not callable(func):
            return {"success": False, "message": f"Unknown command: {command}"}
        result = func(arguments)
        return result if isinstance(result, dict) and ("success" in result) else None


# Register the mapping provider at a reasonable default priority.
state.register_command_provider(cast("Any", DapMappingProvider(COMMAND_HANDLERS)), priority=100)


def receive_debug_commands() -> None:
    """
    Continuously reads debug commands from the IPC channel, parses them,
    and dispatches them for processing until termination is requested.

    IPC is mandatory; raises RuntimeError if IPC is not enabled.
    """
    state.require_ipc()
    if state.ipc_rfile is None:
        msg = "IPC is enabled but no read channel is available."
        raise RuntimeError(msg)

    reader = state.ipc_rfile
    while not state.is_terminated:
        line = reader.readline()
        if not line:
            state.exit_func(0)
        # Each line is a JSON command
        command_json = line.strip()
        if command_json:
            try:
                command = json.loads(command_json)
                state.command_queue.put(command)
                state.dispatch_debug_command(command)
            except Exception as e:
                send_debug_message("error", message=f"Error receiving command: {e!s}")
                traceback.print_exc()


def process_queued_commands():
    while True:
        try:
            cmd = state.command_queue.get_nowait()
            state.dispatch_debug_command(cmd)
        except Empty:  # noqa: PERF203
            break
