"""Debug launcher for Python programs.
This is used to start the debuggee process with the debugger attached.
"""

from __future__ import annotations

import argparse
import json
import logging
from multiprocessing import connection as _mpc
import os
from pathlib import Path
import sys
import threading
import traceback
from typing import Any
from typing import cast

from dapper.core.debugger_bdb import DebuggerBDB
from dapper.ipc.ipc_binary import HEADER_SIZE
from dapper.ipc.ipc_binary import read_exact
from dapper.ipc.ipc_binary import unpack_header
from dapper.launcher.launcher_ipc import connector as default_connector
from dapper.shared import debug_shared
from dapper.shared.command_handlers import handle_debug_command

"""
Debug launcher entry point. Delegates to split modules.
"""

logger = logging.getLogger(__name__)

KIND_COMMAND = 2

# Backward compatibility: tests/legacy code reference debug_launcher.send_debug_message.
send_debug_message = debug_shared.send_debug_message


def _handle_command_bytes(payload: bytes, session: Any | None = None) -> None:
    active_session = session if session is not None else debug_shared.get_active_session()
    try:
        command = json.loads(payload.decode("utf-8"))
        active_session.command_queue.put(command)
        handle_debug_command(command, session=active_session)
    except Exception as e:
        with debug_shared.use_session(active_session):
            send_debug_message("error", message=f"Error receiving command: {e!s}")
        traceback.print_exc()


def _recv_binary_from_pipe(conn: _mpc.Connection, session: Any | None = None) -> None:
    active_session = session if session is not None else debug_shared.get_active_session()
    while not active_session.is_terminated:
        try:
            data = conn.recv_bytes()
        except (EOFError, OSError):
            active_session.exit_func(0)
            return
        if not data:
            active_session.exit_func(0)
            return
        try:
            kind, length = unpack_header(data[:HEADER_SIZE])
        except Exception as e:
            with debug_shared.use_session(active_session):
                send_debug_message("error", message=f"Bad frame header: {e!s}")
            continue
        payload = data[HEADER_SIZE : HEADER_SIZE + length]
        if kind == KIND_COMMAND:
            _handle_command_bytes(payload, active_session)


def _recv_binary_from_stream(rfile: Any, session: Any | None = None) -> None:
    active_session = session if session is not None else debug_shared.get_active_session()
    while not active_session.is_terminated:
        header = read_exact(rfile, HEADER_SIZE)  # type: ignore[arg-type]
        if not header:
            active_session.exit_func(0)
            return
        try:
            kind, length = unpack_header(header)
        except Exception as e:
            with debug_shared.use_session(active_session):
                send_debug_message("error", message=f"Bad frame header: {e!s}")
            continue
        payload = read_exact(rfile, length)  # type: ignore[arg-type]
        if not payload:
            active_session.exit_func(0)
            return
        if kind == KIND_COMMAND:
            _handle_command_bytes(payload, active_session)


def receive_debug_commands(session: Any | None = None) -> None:
    """Listen for commands from the debug adapter via IPC.

    IPC is mandatory; the launcher will not fall back to stdio.
    """
    active_session = session if session is not None else debug_shared.get_active_session()
    active_session.require_ipc()

    # Binary IPC path (default)
    conn = active_session.ipc_pipe_conn
    if conn is not None:
        _recv_binary_from_pipe(conn, active_session)
    else:
        _recv_binary_from_stream(active_session.ipc_rfile, active_session)


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
        "--no-just-my-code",
        action="store_true",
        help="Disable just-my-code filtering (step into library frames)",
    )
    parser.add_argument(
        "--strict-expression-watch-policy",
        action="store_true",
        help="Enable strict expression watchpoint policy checks",
    )
    parser.add_argument(
        "--ipc",
        choices=["tcp", "unix", "pipe"],
        required=True,
        help=(
            "IPC transport type to connect back to the adapter. On Windows use 'tcp' or 'pipe'."
        ),
    )
    parser.add_argument("--ipc-host", type=str, help="IPC TCP host")
    parser.add_argument("--ipc-port", type=int, help="IPC TCP port")
    parser.add_argument("--ipc-path", type=str, help="IPC UNIX socket path")
    parser.add_argument("--ipc-pipe", type=str, help="IPC Windows pipe name")
    parser.add_argument(
        "--ipc-binary",
        action="store_true",
        default=True,
        help="Use binary IPC frames (default: True)",
    )
    return parser.parse_args()


def _setup_ipc_pipe(ipc_pipe: str | None, session: Any | None = None) -> None:
    """Initialize Windows named pipe IPC.

    On success, populates state.ipc_* fields and enables IPC. On failure, raises.
    """
    if not (os.name == "nt" and ipc_pipe):
        msg = "Pipe IPC requested but not on Windows or missing pipe name"
        raise RuntimeError(msg)

    if not str(ipc_pipe).startswith("\\\\.\\pipe\\"):
        msg = "Pipe IPC requested but pipe name must be a full Windows named-pipe path"
        raise RuntimeError(msg)

    active_session = session if session is not None else debug_shared.get_active_session()
    active_session.ipc_enabled = True
    active_session.ipc_pipe_conn = _mpc.Client(address=ipc_pipe, family="AF_PIPE")


def _setup_ipc_socket(
    kind: str,
    host: str | None,
    port: int | None,
    path: str | None,
    ipc_binary: bool = False,
    connector: Any = None,
    session: Any | None = None,
) -> None:
    """Initialize TCP/UNIX socket IPC and configure state.

    kind: "tcp" or "unix"
    """
    # Use the provided connector or fall back to the default one
    if connector is None:
        connector = default_connector

    try:
        if kind == "unix":
            sock = connector.connect_unix(path)
        else:
            sock = connector.connect_tcp(host, port)
    except Exception as exc:  # pragma: no cover - platform specific
        raise RuntimeError("failed to connect socket") from exc

    if sock is None:
        msg = "failed to connect socket"
        raise RuntimeError(msg)

    active_session = session if session is not None else debug_shared.get_active_session()
    active_session.ipc_sock = sock
    if ipc_binary:
        # binary sockets use buffering=0 for raw bytes
        active_session.ipc_rfile = cast("Any", sock.makefile("rb", buffering=0))
        active_session.ipc_wfile = cast("Any", sock.makefile("wb", buffering=0))
    else:
        active_session.ipc_rfile = cast("Any", sock.makefile("r", encoding="utf-8", newline=""))
        active_session.ipc_wfile = cast("Any", sock.makefile("w", encoding="utf-8", newline=""))
    active_session.ipc_enabled = True
    # record whether binary frames are used
    active_session.ipc_binary = bool(ipc_binary)


def setup_ipc_from_args(args: Any, session: Any | None = None) -> None:
    """Initialize IPC based on parsed CLI args.

    IPC is mandatory; raises RuntimeError on failure.
    """
    if args.ipc == "pipe":
        _setup_ipc_pipe(args.ipc_pipe, session=session)
    else:
        _setup_ipc_socket(
            args.ipc,
            args.ipc_host,
            args.ipc_port,
            args.ipc_path,
            args.ipc_binary,
            session=session,
        )


def start_command_listener(session: Any | None = None) -> threading.Thread:
    """Start the background thread that listens for incoming commands."""
    active_session = session if session is not None else debug_shared.get_active_session()
    thread = threading.Thread(target=receive_debug_commands, args=(active_session,), daemon=True)
    thread.start()
    return thread


def configure_debugger(
    stop_on_entry: bool,
    session: Any | None = None,
    just_my_code: bool = True,
    strict_expression_watch_policy: bool = False,
) -> DebuggerBDB:
    """Create and configure the debugger, storing it on shared state."""
    active_session = session if session is not None else debug_shared.get_active_session()
    dbg = DebuggerBDB(
        send_message=send_debug_message,
        process_commands=active_session.process_queued_commands_launcher,
        just_my_code=just_my_code,
        strict_expression_watch_policy=strict_expression_watch_policy,
    )
    if stop_on_entry:
        dbg.stepping_controller.stop_on_entry = True
    active_session.debugger = cast("Any", dbg)
    return dbg


def run_with_debugger(
    program_path: str,
    program_args: list[str],
    session: Any | None = None,
) -> None:
    """Execute the target program under the debugger instance in state."""
    sys.argv = [program_path, *program_args]
    active_session = session if session is not None else debug_shared.get_active_session()
    dbg = active_session.debugger
    if dbg is None:
        dbg = configure_debugger(False, active_session)
    # Read the program file and execute it under the debugger. Avoid building
    # a string that embeds the path (which can mis-handle quotes); instead
    # read the file contents and pass the source directly to the debugger.
    program_file = Path(program_path)
    if program_file.exists():
        # When the program file exists, read and pass its source to the debugger.
        with program_file.open("r", encoding="utf-8") as pf:
            program_code = pf.read()
        dbg.run(program_code)
    else:
        # For testability and backwards-compatibility, if the file does not
        # exist (tests often supply synthetic paths), preserve the previous
        # behaviour of passing an exec-string referencing the path.
        dbg.run(f"exec(Path('{program_path}').open().read())")


def main():
    """Main entry point for the debug launcher"""
    session = debug_shared.get_active_session()
    # Parse arguments and set module state
    args = parse_args()
    program_path = args.program
    program_args = args.arg
    session.stop_at_entry = args.stop_on_entry
    session.no_debug = args.no_debug

    # Configure logging for debug messages
    logging.basicConfig(level=logging.DEBUG, format="DEBUG: %(message)s")

    # Establish IPC connection if requested
    setup_ipc_from_args(args, session=session)

    # Start command listener thread (from IPC or stdin depending on state)
    start_command_listener(session=session)

    # Create the debugger and store it on state
    configure_debugger(
        session.stop_at_entry,
        session=session,
        just_my_code=not args.no_just_my_code,
        strict_expression_watch_policy=getattr(args, "strict_expression_watch_policy", False),
    )

    if session.no_debug:
        # Just run the program without debugging
        run_program(program_path, program_args)
    else:
        # Run the program with debugging
        run_with_debugger(program_path, program_args, session=session)


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
