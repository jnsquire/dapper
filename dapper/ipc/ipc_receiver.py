"""
IPC receiver for debug adapter commands.

This module handles receiving and dispatching debug commands from the
IPC channel (socket or pipe) established between the debug adapter and
the debuggee process.
"""

from __future__ import annotations

import json
import logging
from queue import Empty
import traceback
from typing import Any
from typing import Callable

from dapper.shared import debug_shared
from dapper.shared.command_handlers import COMMAND_HANDLERS

# Backward compatibility: tests and legacy callers may patch ipc_receiver.send_debug_message.
send_debug_message = debug_shared.send_debug_message

logger = logging.getLogger(__name__)

HANDLE_ARGS_DIRECT = 2
HANDLE_ARGS_PROVIDER = 4


def _active_session(session: debug_shared.DebugSession | None = None) -> debug_shared.DebugSession:
    """Return explicitly provided session or context-local active session."""
    return session if session is not None else debug_shared.get_active_session()


ErrorSender = Callable[..., Any]


def _resolve_error_sender(error_sender: ErrorSender | None) -> ErrorSender:
    """Return the explicit sender hook or fallback sender."""
    if error_sender is not None:
        return error_sender
    return send_debug_message


def _send_error(
    message: str,
    session: debug_shared.DebugSession,
    *,
    error_sender: ErrorSender | None = None,
) -> None:
    """Emit an error event using the provided active session context."""
    with debug_shared.use_session(session):
        _resolve_error_sender(error_sender)("error", message=message)


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

    def handle(self, *args: Any):
        """Handle calls from both direct and provider-based dispatch paths."""
        if len(args) == HANDLE_ARGS_DIRECT:
            command, arguments = args
        elif len(args) == HANDLE_ARGS_PROVIDER:
            _session, command, arguments, _full_command = args
        else:
            msg = f"Unexpected handle() arguments: {len(args)}"
            raise TypeError(msg)

        # The underlying mapping handlers only accept `arguments` so delegate
        # and translate their return shape to the protocol expected by
        # register_command_provider.
        func = self._mapping.get(command)
        if not callable(func):
            return {"success": False, "message": f"Unknown command: {command}"}
        result = func(arguments)
        return result if isinstance(result, dict) and ("success" in result) else None


def _ensure_mapping_provider(session: debug_shared.DebugSession) -> None:
    for _priority, provider in list(session.get_command_providers()):
        if isinstance(provider, DapMappingProvider):
            return
    session.register_command_provider(DapMappingProvider(COMMAND_HANDLERS), priority=100)


def receive_debug_commands(
    session: debug_shared.DebugSession | None = None,
    *,
    error_sender: ErrorSender | None = None,
) -> None:
    """
    Continuously reads debug commands from the IPC channel, parses them,
    and dispatches them for processing until termination is requested.

    IPC is mandatory; raises RuntimeError if IPC is not enabled.
    """
    active_session = _active_session(session)
    _ensure_mapping_provider(active_session)

    active_session.require_ipc()
    if active_session.ipc_rfile is None:
        msg = "IPC is enabled but no read channel is available."
        raise RuntimeError(msg)

    reader = active_session.ipc_rfile
    while not active_session.is_terminated:
        line = reader.readline()
        if not line:
            active_session.exit_func(0)
        # Each line is a JSON command
        command_json = line.strip()
        if command_json:
            try:
                command = json.loads(command_json)
                active_session.command_queue.put(command)
            except Exception as e:
                _send_error(
                    f"Error receiving command: {e!s}",
                    active_session,
                    error_sender=error_sender,
                )
                traceback.print_exc()


def process_queued_commands(session: debug_shared.DebugSession | None = None):
    active_session = _active_session(session)
    _ensure_mapping_provider(active_session)
    while True:
        try:
            cmd = active_session.command_queue.get_nowait()
            with debug_shared.use_session(active_session):
                active_session.dispatch_debug_command(cmd)
        except Empty:  # noqa: PERF203
            break
