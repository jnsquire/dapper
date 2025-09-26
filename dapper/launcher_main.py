"""
Launcher, argument parsing, IPC setup, and main routine for debug launcher.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from pathlib import Path

from dapper.debug_adapter_comm import receive_debug_commands
from dapper.debug_adapter_comm import state
from dapper.debugger_bdb import DebuggerBDB
from dapper.launcher_ipc import _setup_ipc_pipe
from dapper.launcher_ipc import _setup_ipc_socket


def _load_program_source(program_path, args):
    sys.argv = [program_path, *args]
    program_path_obj = Path(program_path)
    with program_path_obj.open() as f:
        program_code = f.read()
    program_dir = program_path_obj.resolve().parent
    if str(program_dir) not in sys.path:
        sys.path.insert(0, str(program_dir))
    return program_code


def parse_args():
    parser = argparse.ArgumentParser(description="Python Debug Launcher")
    parser.add_argument(
        "--program", type=str, required=True, help="Path to the Python program to debug"
    )
    parser.add_argument(
        "--arg", action="append", default=[], help="Arguments to pass to the debugged program"
    )
    parser.add_argument(
        "--stop-on-entry", action="store_true", help="Stop at the entry point of the program"
    )
    parser.add_argument(
        "--no-debug", action="store_true", help="Run the program without debugging"
    )
    parser.add_argument(
        "--ipc",
        choices=["tcp", "unix", "pipe"],
        help="Optional IPC transport type to connect back to the adapter. On Windows use 'tcp' or 'pipe'.",
    )
    parser.add_argument("--ipc-host", type=str, help="IPC TCP host")
    parser.add_argument("--ipc-port", type=int, help="IPC TCP port")
    parser.add_argument("--ipc-path", type=str, help="IPC UNIX socket path")
    parser.add_argument("--ipc-pipe", type=str, help="IPC Windows pipe name")
    return parser.parse_args()


def main():
    args = parse_args()
    program_path = args.program
    program_args = args.arg
    state.stop_at_entry = args.stop_on_entry
    state.no_debug = args.no_debug
    logging.basicConfig(level=logging.DEBUG, format="DEBUG: %(message)s")
    if args.ipc:
        try:
            if args.ipc == "pipe" and os.name == "nt" and args.ipc_pipe:
                _setup_ipc_pipe(args.ipc_pipe)
            else:
                _setup_ipc_socket(args.ipc, args.ipc_host, args.ipc_port, args.ipc_path)
        except Exception:
            state.ipc_enabled = False
    command_thread = threading.Thread(target=receive_debug_commands, daemon=True)
    command_thread.start()
    state.debugger = DebuggerBDB()
    if state.stop_at_entry:
        state.debugger.stop_on_entry = True

    program_code = _load_program_source(program_path, program_args)
    ns = {"__name__": "__main__"}

    if state.no_debug:
        exec(program_code, ns)
    else:
        state.debugger.run(program_code, ns)


if __name__ == "__main__":
    main()
