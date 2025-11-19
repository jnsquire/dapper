"""
Debug launcher for Python programs.
This is used to start the debuggee process with the debugger attached.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys
import threading
import traceback
from multiprocessing import connection as _mpc
from pathlib import Path
from typing import Any
from typing import cast

from dapper.core.debugger_bdb import DebuggerBDB
from dapper.ipc.ipc_binary import HEADER_SIZE
from dapper.ipc.ipc_binary import read_exact
from dapper.ipc.ipc_binary import unpack_header
from dapper.launcher.comm import send_debug_message
from dapper.launcher.handlers import handle_debug_command
from dapper.shared.debug_shared import state


"""
Debug launcher entry point. Delegates to split modules.
"""

logger = logging.getLogger(__name__)

KIND_COMMAND = 2


def _handle_command_bytes(payload: bytes) -> None:
    try:
        command = json.loads(payload.decode("utf-8"))
        state.command_queue.put(command)
        handle_debug_command(command)
    except Exception as e:
        send_debug_message("error", message=f"Error receiving command: {e!s}")
        traceback.print_exc()


def _recv_binary_from_pipe(conn: _mpc.Connection) -> None:
    while not state.is_terminated:
        try:
            data = conn.recv_bytes()
        except (EOFError, OSError):
            state.exit_func(0)
            return
        if not data:
            state.exit_func(0)
            return
        try:
            kind, length = unpack_header(data[:HEADER_SIZE])
        except Exception as e:
            send_debug_message("error", message=f"Bad frame header: {e!s}")
            continue
        payload = data[HEADER_SIZE : HEADER_SIZE + length]
        if kind == KIND_COMMAND:
            _handle_command_bytes(payload)


def _recv_binary_from_stream(rfile: Any) -> None:
    while not state.is_terminated:
        header = read_exact(rfile, HEADER_SIZE)  # type: ignore[arg-type]
        if not header:
            state.exit_func(0)
        try:
            kind, length = unpack_header(header)
        except Exception as e:
            send_debug_message("error", message=f"Bad frame header: {e!s}")
            continue
        payload = read_exact(rfile, length)  # type: ignore[arg-type]
        if not payload:
            state.exit_func(0)
        if kind == KIND_COMMAND:
            _handle_command_bytes(payload)


def receive_debug_commands() -> None:
    """
    Listen for commands from the debug adapter on stdin.
    These are prefixed with DBGCMD: to distinguish them from regular input.
    """
    # read-only access to state.is_terminated
    if state.ipc_enabled:
        # Binary IPC path
        conn = state.ipc_pipe_conn
        if conn is not None:
            _recv_binary_from_pipe(conn)
            return
        _recv_binary_from_stream(state.ipc_rfile)
        return

    while not state.is_terminated:
        line = sys.stdin.readline()
        if not line:
            # End of input stream, debug adapter has closed connection
            state.exit_func(0)

        if line.startswith("DBGCMD:"):
            _handle_command_bytes(line[7:].strip().encode("utf-8"))





def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description="Python Debug Launcher")
    parser.add_argument(
        "--program",
        type=str,
        required=True,
        help="Path to the Python program to debug",
    )
    parser.add_argument(
        "--arg",
        action="append",
        default=[],
        help="Arguments to pass to the debugged program",
    )
    parser.add_argument(
        "--stop-on-entry",
        action="store_true",
        help="Stop at the entry point of the program",
    )
    parser.add_argument(
        "--no-debug",
        action="store_true",
        help="Run the program without debugging",
    )
    parser.add_argument(
        "--ipc",
        choices=["tcp", "unix", "pipe"],
        help=(
            "Optional IPC transport type to connect back to the adapter. "
            "On Windows use 'tcp' or 'pipe'."
        ),
    )
    parser.add_argument("--ipc-host", type=str, help="IPC TCP host")
    parser.add_argument("--ipc-port", type=int, help="IPC TCP port")
    parser.add_argument("--ipc-path", type=str, help="IPC UNIX socket path")
    parser.add_argument("--ipc-pipe", type=str, help="IPC Windows pipe name")
    parser.add_argument("--ipc-binary", action="store_true", help="Use binary IPC frames")
    return parser.parse_args()


def _setup_ipc_pipe(ipc_pipe: str | None) -> None:
    """Initialize Windows named pipe IPC.

    On success, populates state.ipc_* fields and enables IPC. On failure, raises.
    """
    if not (os.name == "nt" and ipc_pipe):
        msg = "Pipe IPC requested but not on Windows or missing pipe name"
        raise RuntimeError(msg)

    conn = _mpc.Client(address=ipc_pipe, family="AF_PIPE")
    state.ipc_enabled = True
    state.ipc_pipe_conn = conn


def _setup_ipc_socket(
    kind: str,
    host: str | None,
    port: int | None,
    path: str | None,
    ipc_binary: bool = False,
) -> None:
    """Initialize TCP/UNIX socket IPC and configure state.

    kind: "tcp" or "unix"
    """
    sock = None
    if kind == "unix":
        af_unix = getattr(socket, "AF_UNIX", None)
        if af_unix and path:
            sock = socket.socket(af_unix, socket.SOCK_STREAM)
            sock.connect(path)
        else:
            msg = "UNIX sockets unsupported or missing path"
            raise RuntimeError(msg)
    else:
        # Default to TCP
        if port is None:
            msg = "Missing --ipc-port for TCP IPC"
            raise RuntimeError(msg)
        h = host or "127.0.0.1"
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((h, int(port)))

    state.ipc_sock = sock
    state.ipc_rfile = cast("Any", sock.makefile("rb", buffering=0))
    state.ipc_wfile = cast("Any", sock.makefile("wb", buffering=0))
    state.ipc_enabled = True
    # record whether binary frames are used
    state.ipc_binary = bool(ipc_binary)


def setup_ipc_from_args(args: Any) -> None:
    """Best-effort IPC initialization based on parsed CLI args.

    Any failure will leave IPC disabled and fall back to stdio.
    """
    if not args.ipc:
        return
    try:
        if args.ipc == "pipe":
            _setup_ipc_pipe(args.ipc_pipe)
        else:
            _setup_ipc_socket(
                args.ipc, args.ipc_host, args.ipc_port, args.ipc_path, args.ipc_binary
            )
    except Exception:
        # If IPC fails, proceed with stdio
        state.ipc_enabled = False


def start_command_listener() -> threading.Thread:
    """Start the background thread that listens for incoming commands."""
    thread = threading.Thread(target=receive_debug_commands, daemon=True)
    thread.start()
    return thread


def configure_debugger(stop_on_entry: bool) -> DebuggerBDB:
    """Create and configure the debugger, storing it on shared state."""
    dbg = DebuggerBDB()
    if stop_on_entry:
        dbg.stop_on_entry = True
    state.debugger = cast("Any", dbg)
    return dbg


def run_with_debugger(program_path: str, program_args: list[str]) -> None:
    """Execute the target program under the debugger instance in state."""
    sys.argv = [program_path, *program_args]
    dbg = state.debugger
    if dbg is None:
        dbg = configure_debugger(False)
    dbg.run(f"exec(Path('{program_path}').open().read())")


def main():
    """Main entry point for the debug launcher"""
    # Parse arguments and set module state
    args = parse_args()
    program_path = args.program
    program_args = args.arg
    state.stop_at_entry = args.stop_on_entry
    state.no_debug = args.no_debug

    # Configure logging for debug messages
    logging.basicConfig(level=logging.DEBUG, format="DEBUG: %(message)s")

    # Establish IPC connection if requested
    setup_ipc_from_args(args)

    # Start command listener thread (from IPC or stdin depending on state)
    start_command_listener()

    # Create the debugger and store it on state
    configure_debugger(state.stop_at_entry)

    if state.no_debug:
        # Just run the program without debugging
        run_program(program_path, program_args)
    else:
        # Run the program with debugging
        run_with_debugger(program_path, program_args)


def run_program(program_path, args):
    """Run the program without debugging"""
    sys.argv = [program_path, *args]

    with Path(program_path).open() as f:
        program_code = f.read()

    # Add the program directory to sys.path
    program_dir = Path(program_path).resolve().parent
    if str(program_dir) not in sys.path:
        sys.path.insert(0, str(program_dir))

    # Execute the program
    exec(program_code, {"__name__": "__main__"})


if __name__ == "__main__":
    main()
