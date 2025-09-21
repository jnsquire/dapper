"""
Launcher, argument parsing, IPC setup, and main routine for debug launcher.
"""

import argparse
import contextlib
import io
import logging
import os
import socket
import sys
import threading
from multiprocessing import connection as _mpc
from pathlib import Path

from dapper.debug_adapter_comm import receive_debug_commands
from dapper.debug_adapter_comm import state
from dapper.debugger_bdb import DebuggerBDB


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
                conn = _mpc.Client(address=args.ipc_pipe, family="AF_PIPE")
                state.ipc_enabled = True

                class _PipeIO(io.TextIOBase):
                    def __init__(self, conn=conn):
                        self.conn = conn

                    def write(self, s: str) -> int:
                        self.conn.send(s)
                        return len(s)

                    def flush(self) -> None:
                        return

                    def readline(self, size: int = -1) -> str:
                        try:
                            data = self.conn.recv()
                        except (EOFError, OSError):
                            return ""
                        s = data
                        if size is not None and size >= 0:
                            return s[:size]
                        return s

                    def close(self) -> None:
                        with contextlib.suppress(Exception):
                            self.conn.close()

                state.ipc_rfile = _PipeIO()
                state.ipc_wfile = _PipeIO()
            else:
                sock = None
                if args.ipc == "unix":
                    af_unix = getattr(os, "AF_UNIX", None)
                    if af_unix and args.ipc_path:
                        sock = socket.socket(af_unix, socket.SOCK_STREAM)
                        sock.connect(args.ipc_path)
                else:
                    host = args.ipc_host or "127.0.0.1"
                    port = int(args.ipc_port)
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.connect((host, port))
                if sock is not None:
                    state.ipc_sock = sock
                    state.ipc_rfile = sock.makefile("r", encoding="utf-8", newline="")
                    state.ipc_wfile = sock.makefile("w", encoding="utf-8", newline="")
                    state.ipc_enabled = True
        except Exception:
            state.ipc_enabled = False
    command_thread = threading.Thread(target=receive_debug_commands, daemon=True)
    command_thread.start()
    state.debugger = DebuggerBDB()
    if state.stop_at_entry:
        state.debugger.stop_on_entry = True
    if state.no_debug:
        run_program(program_path, program_args)
    else:
        sys.argv = [program_path, *program_args]
        state.debugger.run(f"exec(Path('{program_path}').open().read())")


def run_program(program_path, args):
    sys.argv = [program_path, *args]
    with Path(program_path).open() as f:
        program_code = f.read()
    program_dir = Path(program_path).resolve().parent
    if str(program_dir) not in sys.path:
        sys.path.insert(0, str(program_dir))
    exec(program_code, {"__name__": "__main__"})


if __name__ == "__main__":
    main()
