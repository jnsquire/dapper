"""
Debug adapter communication and command queue logic.
"""

import json
import os
import sys
import traceback

from dapper.dap_command_handlers import handle_debug_command
from dapper.debug_shared import send_debug_message
from dapper.debug_shared import state

state.handle_debug_command = handle_debug_command


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
                    state.handle_debug_command(command)
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
                    state.handle_debug_command(command)
                except Exception as e:
                    send_debug_message("error", message=f"Error receiving command: {e!s}")
                    traceback.print_exc()


def process_queued_commands():
    with state.command_lock:
        commands = state.command_queue.copy()
        state.command_queue.clear()
    for cmd in commands:
        state.handle_debug_command(cmd)
