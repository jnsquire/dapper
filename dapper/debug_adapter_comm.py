"""
Debug adapter communication and command queue logic.
"""

import json
import os
import sys
import traceback

from dapper.dap_command_handlers import COMMAND_HANDLERS
from dapper.debug_shared import send_debug_message
from dapper.debug_shared import state


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

    def handle(self, _session, command: str, arguments, _full_command):
        func = self._mapping.get(command)
        if not callable(func):
            return {"success": False, "message": f"Unknown command: {command}"}
        result = func(arguments)
        return result if isinstance(result, dict) and ("success" in result) else None


# Register the mapping provider at a reasonable default priority.
state.register_command_provider(DapMappingProvider(COMMAND_HANDLERS), priority=100)


def receive_debug_commands() -> None:
    if state.ipc_enabled and state.ipc_rfile is not None:
        reader = state.ipc_rfile
        while not state.is_terminated:
            line = reader.readline()
            if not line:
                os._exit(0)
            if line.startswith("DBGCMD:"):
                command_json = line[7:].strip()
                try:
                    command = json.loads(command_json)
                    with state.command_lock:
                        state.command_queue.append(command)
                    state.dispatch_debug_command(command)
                except Exception as e:
                    send_debug_message("error", message=f"Error receiving command: {e!s}")
                    traceback.print_exc()
    else:
        while not state.is_terminated:
            line = sys.stdin.readline()
            if not line:
                os._exit(0)
            if line.startswith("DBGCMD:"):
                command_json = line[7:].strip()
                try:
                    command = json.loads(command_json)
                    with state.command_lock:
                        state.command_queue.append(command)
                    state.dispatch_debug_command(command)
                except Exception as e:
                    send_debug_message("error", message=f"Error receiving command: {e!s}")
                    traceback.print_exc()


def process_queued_commands():
    with state.command_lock:
        commands = state.command_queue.copy()
        state.command_queue.clear()
    for cmd in commands:
        state.dispatch_debug_command(cmd)
