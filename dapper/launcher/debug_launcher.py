"""Debug launcher for Python programs.
This is used to start the debuggee process with the debugger attached.
"""

from __future__ import annotations

import argparse
import atexit
import json
import logging
from multiprocessing import connection as _mpc
import os
from pathlib import Path
import runpy
import sys
import threading
import traceback
from typing import Any
from typing import cast
import uuid

from dapper.adapter.subprocess_manager import SubprocessConfig
from dapper.adapter.subprocess_manager import SubprocessManager
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
            active_session.exit_if_alive(0)
            return
        if not data:
            active_session.exit_if_alive(0)
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
        try:
            header = read_exact(rfile, HEADER_SIZE)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            # Socket was closed (e.g. during test teardown) — exit quietly.
            active_session.exit_if_alive(0)
            return
        if not header:
            active_session.exit_if_alive(0)
            return
        try:
            kind, length = unpack_header(header)
        except Exception as e:
            with debug_shared.use_session(active_session):
                send_debug_message("error", message=f"Bad frame header: {e!s}")
            continue
        try:
            payload = read_exact(rfile, length)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            active_session.exit_if_alive(0)
            return
        if not payload:
            active_session.exit_if_alive(0)
            return
        if kind == KIND_COMMAND:
            try:
                _handle_command_bytes(payload, active_session)
            except SystemExit:
                # The terminate handler raises SystemExit after sending the
                # response.  Let the thread exit cleanly instead of leaving
                # an unhandled exception that pytest would report as a warning.
                return


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
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument(
        "--program",
        type=str,
        help="Path to the Python program to debug",
    )
    target_group.add_argument(
        "--module",
        type=str,
        help="Python module to run (equivalent to `python -m <module>`)",
    )
    target_group.add_argument(
        "--code",
        type=str,
        help="Python code string to run (equivalent to `python -c <code>`)",
    )
    parser.add_argument(
        "--arg",
        action="append",
        default=[],
        help="Arguments to pass to the debugged program",
    )
    parser.add_argument(
        "--module-search-path",
        action="append",
        default=[],
        help="Additional module search path entries (repeatable)",
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
    parser.add_argument(
        "--subprocess",
        action="store_true",
        help="Indicates this launcher invocation is for a child subprocess.",
    )
    parser.add_argument(
        "--subprocess-auto-attach",
        action="store_true",
        help="Enable automatic debugger injection for Python subprocess children.",
    )
    parser.add_argument(
        "--session-id",
        type=str,
        help="Logical session identifier for this launcher process.",
    )
    parser.add_argument(
        "--parent-session-id",
        type=str,
        help="Logical parent session identifier for this launcher process.",
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
    target_value: str,
    program_args: list[str],
    session: Any | None = None,
    *,
    target_kind: str = "program",
) -> None:
    """Execute the target under the debugger instance in state."""
    active_session = session if session is not None else debug_shared.get_active_session()
    dbg = active_session.debugger
    if dbg is None:
        dbg = configure_debugger(False, active_session)

    # Ensure the session context is set for this thread so that any
    # debugger callbacks (send_message, process_commands) that rely on
    # ``get_active_session()`` will find the correct session.
    with debug_shared.use_session(active_session):
        _run_target(dbg, active_session, target_value, program_args, target_kind=target_kind)


def _run_target(
    dbg: Any,
    active_session: Any,
    target_value: str,
    program_args: list[str],
    *,
    target_kind: str = "program",
) -> None:
    """Inner implementation for *run_with_debugger* — executes the target."""
    if target_kind == "program":
        program_path = target_value
        sys.argv = [program_path, *program_args]
        program_file = Path(program_path)
        if program_file.exists():
            # Mirror Python's normal script behaviour: insert the script's directory
            # as sys.path[0] so relative imports (e.g. `import hn` from src/) work.
            script_dir = str(program_file.parent.resolve())
            if not sys.path or sys.path[0] != script_dir:
                sys.path.insert(0, script_dir)
            with program_file.open("r", encoding="utf-8") as pf:
                program_code = pf.read()
            # Provide the same globals that Python sets when running a script directly,
            # so __file__, __name__ and builtins are all available to the program.
            script_globals = {
                "__name__": "__main__",
                "__file__": str(program_file.resolve()),
                "__builtins__": __builtins__,
            }
            # Pre-compile with the real filename so frame.f_code.co_filename
            # matches the paths used for breakpoint registration.  BDB's
            # run() would otherwise compile with "<string>".
            compiled = compile(program_code, str(program_file.resolve()), "exec")
            dbg.run(compiled, script_globals)
            return

        msg = f"Program file not found: {program_path!r}"
        raise FileNotFoundError(msg)

    if target_kind == "module":
        module_name = target_value
        for search_path in reversed(getattr(active_session, "module_search_paths", [])):
            if search_path and search_path not in sys.path:
                sys.path.insert(0, search_path)
        sys.argv = [module_name, *program_args]
        dbg.run(
            f"import runpy\nrunpy.run_module({module_name!r}, run_name='__main__', alter_sys=True)"
        )
        return

    if target_kind == "code":
        code_string = target_value
        sys.argv = ["-c", *program_args]
        dbg.run(code_string)
        return

    msg = f"Unsupported target kind: {target_kind}"
    raise RuntimeError(msg)


def _register_terminal_crash_handler() -> None:
    """Keep the terminal open when the launcher exits due to an unhandled exception.

    VS Code's integrated terminal can close before the user has a chance to
    read the traceback.  We install a thin ``sys.excepthook`` wrapper that
    sets a flag and an ``atexit`` handler that pauses for input when the
    flag is set.
    """
    _had_crash = [False]
    _orig_excepthook = sys.excepthook

    def _excepthook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: Any,
    ) -> None:
        _had_crash[0] = True
        _orig_excepthook(exc_type, exc_value, exc_tb)

    def _pause_on_crash() -> None:
        if not _had_crash[0]:
            return
        try:
            sys.stderr.write(
                "\n--- Dapper: the process exited with an error (see above) ---\n"
                "Press Enter to close this terminal..."
            )
            sys.stderr.flush()
            input()
        except (EOFError, OSError):
            pass

    sys.excepthook = _excepthook
    atexit.register(_pause_on_crash)


def main():  # noqa: PLR0912, PLR0915
    """Main entry point for the debug launcher"""
    _register_terminal_crash_handler()
    session = debug_shared.get_active_session()
    # Parse arguments and set module state
    args = parse_args()
    target_kind = "program"
    target_value = args.program
    if getattr(args, "module", None):
        target_kind = "module"
        target_value = args.module
    elif getattr(args, "code", None):
        target_kind = "code"
        target_value = args.code

    if not target_value:
        msg = "One of --program, --module, or --code is required"
        raise RuntimeError(msg)

    program_args = args.arg
    session.stop_at_entry = args.stop_on_entry
    session.no_debug = args.no_debug
    session.session_id = getattr(args, "session_id", None) or uuid.uuid4().hex
    session.parent_session_id = getattr(args, "parent_session_id", None)
    session.module_search_paths = list(getattr(args, "module_search_path", []))

    # Configure logging for debug messages
    logging.basicConfig(level=logging.DEBUG, format="DEBUG: %(message)s")

    logger.info(
        "Launcher started: %s=%s session_id=%s stop_on_entry=%s no_debug=%s",
        target_kind,
        target_value,
        session.session_id,
        session.stop_at_entry,
        session.no_debug,
    )

    subprocess_manager: SubprocessManager | None = None

    if getattr(args, "subprocess_auto_attach", False):
        subprocess_manager = SubprocessManager(
            send_event=lambda event_name, payload: send_debug_message(event_name, **payload),
            config=SubprocessConfig(
                enabled=True,
                auto_attach=True,
                ipc_host=args.ipc_host or "127.0.0.1",
                session_id=session.session_id,
                parent_session_id=session.parent_session_id,
            ),
        )
        subprocess_manager.enable()

    try:
        # Establish IPC connection if requested
        setup_ipc_from_args(args, session=session)
        logger.info("IPC connection established")

        # Start command listener thread (from IPC or stdin depending on state)
        start_command_listener(session=session)
        logger.info("Command listener thread started")

        # Create the debugger and store it on state
        configure_debugger(
            session.stop_at_entry,
            session=session,
            just_my_code=not args.no_just_my_code,
            strict_expression_watch_policy=getattr(args, "strict_expression_watch_policy", False),
        )
        logger.info(
            "Debugger configured (stop_at_entry=%s, no_debug=%s, just_my_code=%s)",
            session.stop_at_entry,
            session.no_debug,
            not args.no_just_my_code,
        )

        if session.no_debug:
            logger.info("Running without debugging: %s=%s", target_kind, target_value)
            # Just run the program without debugging
            if target_kind == "program":
                run_program(target_value, program_args)
            else:
                run_program(target_value, program_args, target_kind=target_kind)
        else:
            # Wait for the adapter to finish sending setBreakpoints / configurationDone
            # before starting the program so all breakpoints are in place.
            session.debugger_configured_event.set()
            logger.info("Waiting for configurationDone (timeout=30s)...")
            if not session.configuration_done_event.wait(timeout=30):
                logger.warning("Timed out waiting for configurationDone; starting anyway")
            else:
                logger.info("configurationDone received, starting program")
            # Run the program with debugging
            logger.info(
                "Starting debugger: %s=%s args=%s", target_kind, target_value, program_args
            )
            if target_kind == "program":
                run_with_debugger(target_value, program_args, session=session)
            else:
                run_with_debugger(
                    target_value,
                    program_args,
                    session=session,
                    target_kind=target_kind,
                )
            logger.info("Program execution completed")
    finally:
        # Notify the adapter that the program has finished so the debug
        # session in VS Code terminates instead of hanging indefinitely.
        logger.info("Sending exited/terminated events")
        try:
            send_debug_message("exited", exitCode=0)
            send_debug_message("terminated")
        except Exception:
            logger.debug("Failed to send exit events (IPC may already be closed)")
        if subprocess_manager is not None:
            subprocess_manager.cleanup()


def run_program(target_value, args, *, target_kind: str = "program"):
    """Run the target without debugging."""
    if target_kind == "program":
        program_path = target_value
        sys.argv = [program_path, *args]

        with Path(program_path).open() as f:
            program_code = f.read()

        # Add the program directory to sys.path
        program_dir = Path(program_path).resolve().parent
        if str(program_dir) not in sys.path:
            sys.path.insert(0, str(program_dir))

        exec(program_code, {"__name__": "__main__"})
        return

    if target_kind == "module":
        module_name = target_value
        active_session = debug_shared.get_active_session()
        for search_path in reversed(getattr(active_session, "module_search_paths", [])):
            if search_path and search_path not in sys.path:
                sys.path.insert(0, search_path)
        sys.argv = [module_name, *args]
        runpy.run_module(module_name, run_name="__main__", alter_sys=True)
        return

    if target_kind == "code":
        code_string = target_value
        sys.argv = ["-c", *args]
        exec(compile(code_string, "<string>", "exec"), {"__name__": "__main__"})
        return

    msg = f"Unsupported target kind: {target_kind}"
    raise RuntimeError(msg)


if __name__ == "__main__":
    main()
