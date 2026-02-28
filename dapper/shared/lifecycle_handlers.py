"""Lifecycle and exception command handler implementations."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logging import Logger

    from dapper.protocol.debugger_protocol import CommandHandlerDebuggerLike
    from dapper.shared.command_handler_helpers import Payload
    from dapper.shared.debug_shared import DebugSession


def handle_exception_info_impl(
    dbg: CommandHandlerDebuggerLike | None,
    arguments: Payload | None,
    logger: Logger,
) -> Payload:
    """Handle exceptionInfo command implementation."""
    arguments = arguments or {}

    exception_info = {
        "exceptionId": "Exception",
        "description": "An exception occurred",
        "breakMode": "always",
        "details": {
            "message": "Exception details unavailable",
            "typeName": "Exception",
        },
    }

    if dbg:
        exc = getattr(dbg, "current_exception", None)
        if exc:
            try:
                exception_info.update(
                    {
                        "exceptionId": type(exc).__name__,
                        "description": str(exc),
                        "details": {
                            "message": str(exc),
                            "typeName": type(exc).__name__,
                        },
                    }
                )
            except (AttributeError, TypeError, ValueError):
                logger.debug("Failed to enrich exception info payload", exc_info=True)

    return {"success": True, "body": exception_info}


def handle_configuration_done_impl() -> Payload:
    """Handle configurationDone command."""
    return {"success": True}


def handle_terminate_impl(
    *,
    state: DebugSession,
) -> Payload:
    """Handle terminate command."""
    state.safe_send("exited", exitCode=0)
    state.terminate_session()
    # Return a success response so the dispatch sends it before we exit.
    # exit_func is called after the handler returns (or in a deferred manner).
    return {"success": True}


def handle_initialize_impl() -> Payload:
    """Handle initialize command."""
    capabilities = {
        "supportsConfigurationDoneRequest": True,
        "supportsFunctionBreakpoints": True,
        "supportsExceptionBreakpoints": True,
        "supportsDataBreakpoints": True,
        "supportsSetVariable": True,
        "supportsEvaluateForHovers": True,
        "supportsLogPoints": True,
        "supportsRestartRequest": True,
    }
    return {"success": True, "body": capabilities}


def handle_restart_impl(  # noqa: PLR0912, PLR0915
    *,
    state: DebugSession,
    logger: Logger,
) -> Payload:
    """Handle restart command."""
    state.safe_send("exited", exitCode=0)

    try:
        state.is_terminated = True

        try:
            if state.ipc_pipe_conn is not None:
                try:
                    state.ipc_pipe_conn.close()
                except Exception:
                    logger.debug("Failed to close ipc_pipe_conn during restart", exc_info=True)
                finally:
                    state.ipc_pipe_conn = None
        except Exception:
            logger.debug("Error while cleaning ipc_pipe_conn", exc_info=True)

        try:
            if state.ipc_wfile is not None:
                try:
                    state.ipc_wfile.close()
                except Exception:
                    logger.debug("Failed to close ipc_wfile during restart", exc_info=True)
                finally:
                    state.ipc_wfile = None
        except Exception:
            logger.debug("Error while cleaning ipc_wfile", exc_info=True)

        try:
            if state.ipc_rfile is not None:
                try:
                    state.ipc_rfile.close()
                except Exception:
                    logger.debug("Failed to close ipc_rfile during restart", exc_info=True)
                finally:
                    state.ipc_rfile = None
        except Exception:
            logger.debug("Error while cleaning ipc_rfile", exc_info=True)

        try:
            state.ipc_enabled = False
        except Exception:
            pass

        try:
            thread_handle = state.command_thread
            if thread_handle is not None and getattr(thread_handle, "is_alive", lambda: False)():
                try:
                    thread_handle.join(timeout=0.1)
                except Exception:
                    logger.debug("Failed to join command_thread during restart", exc_info=True)
            state.command_thread = None
        except Exception:
            logger.debug("Error while handling command_thread cleanup", exc_info=True)
    except Exception:
        logger.exception("Unexpected error during restart cleanup")

    python = sys.executable
    argv = sys.argv[1:]
    state.exec_func(python, [python, *argv])
    return {"success": True}


def cmd_exception_info(
    arguments: Payload | None,
    *,
    state: DebugSession,
) -> None:
    """Handle exceptionInfo request on command registry pathway."""
    thread_id = arguments.get("threadId") if arguments else None
    if thread_id is None:
        state.safe_send("error", message="Missing required argument 'threadId'")
        return

    dbg = state.debugger
    if not dbg:
        state.safe_send("error", message="Debugger not initialized")
        return

    exception_handler = dbg.exception_handler
    if thread_id not in exception_handler.exception_info_by_thread:
        state.safe_send("error", message=f"No exception info available for thread {thread_id}")
        return

    exception_info = exception_handler.exception_info_by_thread[thread_id]
    state.safe_send(
        "exceptionInfo",
        exceptionId=exception_info["exceptionId"],
        description=exception_info["description"],
        breakMode=exception_info["breakMode"],
        details=exception_info["details"],
    )
