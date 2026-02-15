"""Lifecycle and exception command handler implementations."""

from __future__ import annotations

import sys
from typing import Any
from typing import Protocol

Payload = dict[str, Any]


class SafeSendDebugMessageFn(Protocol):
    def __call__(self, message_type: str, **payload: Any) -> bool: ...


class LoggerLike(Protocol):
    def debug(self, msg: str, *args: object, **kwargs: object) -> object: ...
    def exception(self, msg: str, *args: object, **kwargs: object) -> object: ...


class SessionStateLike(Protocol):
    is_terminated: bool
    ipc_pipe_conn: object | None
    ipc_wfile: object | None
    ipc_rfile: object | None
    ipc_enabled: bool
    command_thread: object | None
    debugger: object | None
    exit_func: object
    exec_func: object


def handle_exception_info_impl(
    dbg: object | None,
    arguments: Payload | None,
    logger: LoggerLike,
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
    safe_send_debug_message: SafeSendDebugMessageFn,
    state: SessionStateLike,
) -> None:
    """Handle terminate command."""
    safe_send_debug_message("exited", exitCode=0)
    state.is_terminated = True
    state.exit_func(0)


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
    safe_send_debug_message: SafeSendDebugMessageFn,
    state: SessionStateLike,
    logger: LoggerLike,
) -> Payload:
    """Handle restart command."""
    safe_send_debug_message("exited", exitCode=0)

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
            if getattr(state, "ipc_rfile", None) is not None:
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
            thread_handle = getattr(state, "command_thread", None)
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
    state: SessionStateLike,
    safe_send_debug_message: SafeSendDebugMessageFn,
) -> None:
    """Handle exceptionInfo request on command registry pathway."""
    thread_id = arguments.get("threadId") if arguments else None
    if thread_id is None:
        safe_send_debug_message("error", message="Missing required argument 'threadId'")
        return

    dbg = state.debugger
    if not dbg:
        safe_send_debug_message("error", message="Debugger not initialized")
        return

    if thread_id not in dbg.exception_handler.exception_info_by_thread:
        safe_send_debug_message(
            "error", message=f"No exception info available for thread {thread_id}"
        )
        return

    exception_info = dbg.exception_handler.exception_info_by_thread[thread_id]
    safe_send_debug_message(
        "exceptionInfo",
        exceptionId=exception_info["exceptionId"],
        description=exception_info["description"],
        breakMode=exception_info["breakMode"],
        details=exception_info["details"],
    )
