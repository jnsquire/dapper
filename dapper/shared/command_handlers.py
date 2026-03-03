"""Canonical DAP command handler implementations and registry for the debuggee process.

This module provides:
1. The `COMMAND_HANDLERS` registry populated via the `@command_handler` decorator
2. The canonical handler implementations for all DAP commands
3. The `handle_debug_command()` entry point for command dispatch

Both IPC pathways dispatch through the `COMMAND_HANDLERS` registry:
- Pipe-based IPC: `debug_launcher.py` calls `handle_debug_command()`
- Socket-based IPC: `ipc_receiver.py` wraps `COMMAND_HANDLERS` in a provider

Dependencies:
- `dapper.shared.debug_shared.send_debug_message` for IPC message output
- `dapper.shared.debug_shared.get_active_session` for debugger session state
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING
from typing import Any
from typing import Callable
from typing import Literal
from typing import TypedDict
from typing import cast

if TYPE_CHECKING:
    from dapper.core.thread_tracker import FrameType

from dapper.shared import breakpoint_handlers

# FrameType is only needed for type hints; import under TYPE_CHECKING to
# avoid runtime dependency and satisfy ruff TC001.
from dapper.shared import command_handler_helpers
from dapper.shared import debug_shared as _d_shared
from dapper.shared import lifecycle_handlers
from dapper.shared import source_handlers
from dapper.shared import stack_handlers
from dapper.shared import stepping_handlers
from dapper.shared import variable_handlers
from dapper.shared.value_conversion import convert_value_with_context
from dapper.shared.value_conversion import evaluate_with_policy

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from dapper.protocol.debugger_protocol import CommandHandlerDebuggerLike
    from dapper.protocol.debugger_protocol import DebuggerLike
    from dapper.protocol.requests import ContinueArguments

    # Data breakpoints are defined alongside other breakpoints
    from dapper.protocol.requests import DataBreakpointInfoArguments
    from dapper.protocol.requests import EvaluateArguments
    from dapper.protocol.requests import GotoArguments
    from dapper.protocol.requests import GotoTarget
    from dapper.protocol.requests import GotoTargetsArguments
    from dapper.protocol.requests import GotoTargetsResponseBody
    from dapper.protocol.requests import HotReloadOptions
    from dapper.protocol.requests import NextArguments
    from dapper.protocol.requests import PauseArguments
    from dapper.protocol.requests import ScopesArguments
    from dapper.protocol.requests import SetBreakpointsArguments
    from dapper.protocol.requests import SetDataBreakpointsArguments
    from dapper.protocol.requests import SetExceptionBreakpointsArguments
    from dapper.protocol.requests import SetExpressionArguments
    from dapper.protocol.requests import SetFunctionBreakpointsArguments
    from dapper.protocol.requests import SetVariableArguments
    from dapper.protocol.requests import StackTraceArguments
    from dapper.protocol.requests import StepInArguments
    from dapper.protocol.requests import StepOutArguments
    from dapper.protocol.requests import VariablesArguments


CommandPayload = command_handler_helpers.Payload

# Commands that resume program execution and should unblock
# ``process_queued_commands_launcher`` (which is blocking on ``_resume_event``).
_RESUME_COMMANDS: frozenset[str] = frozenset(
    {
        "continue",
        "next",
        "stepIn",
        "stepOut",
        "terminate",
    }
)

SIMPLE_FN_ARGCOUNT = 2
_CONVERSION_ERROR_MESSAGE = "Conversion failed"
# Maximum string length for enriched repr values in dataBreakpointInfo
MAX_VALUE_REPR_LEN = 200
_TRUNC_SUFFIX = "..."

# =============================================================================
# Command Registry
# =============================================================================

# Command mapping table - populated by the @command_handler decorator
COMMAND_HANDLERS: dict[str, Callable[..., None]] = {}


_error_response = command_handler_helpers.error_response

# Backward compatibility: tests/legacy code monkeypatch this symbol directly.
send_debug_message = _d_shared.send_debug_message


def _flush_transport(session: _d_shared.DebugSession) -> None:
    """Best-effort flush of the IPC write channel.

    Call this after sending a response that *must* arrive before the next
    action (e.g. before ``os._exit`` or before unblocking the main thread).
    """
    wfile = session.transport.ipc_wfile
    if wfile is not None:
        try:
            wfile.flush()
        except Exception:
            pass


def command_handler(command_name: str):
    """Decorator to register DAP command handlers in the COMMAND_HANDLERS registry."""

    def decorator(func):
        COMMAND_HANDLERS[command_name] = func
        return func

    return decorator


def handle_debug_command(
    command: CommandPayload,
    session: _d_shared.DebugSession | None = None,
) -> None:
    """Handle debug commands using the COMMAND_HANDLERS registry.

    This is the main entry point for command dispatch. Both IPC pathways
    (pipe-based and socket-based) ultimately dispatch through this registry.

    Historically the dispatcher would automatically emit a default response
    when a handler returned a simple dictionary.  That implicit "fallback
    ack" behaviour has been removed: handlers are now responsible for
    calling ``session.safe_send_response`` (or ``active_session.safe_send``)
    when they have finished processing a command.  If no response is sent the
    dispatcher will log a warning, but it will not generate any DAP message on
    the caller's behalf.
    """
    active_session = session if session is not None else _d_shared.get_active_session()
    with _d_shared.use_session(active_session):
        cmd = command.get("command")
        cmd_id = command.get("id")  # request id to echo back in the response
        arguments = command.get("arguments", {})
        logger.debug("handle_debug_command: cmd=%s id=%s", cmd, cmd_id)
        # Ensure the command name is a string before looking up the handler
        if not isinstance(cmd, str):
            active_session.safe_send(
                "response",
                id=cmd_id,
                success=False,
                message=f"Invalid command: {cmd!r}",
            )
            return

        # Scope the request lifecycle on the transport so handlers
        # can read session.request_id and response_sent is tracked.
        with active_session.transport.request_scope(cmd_id) as transport:
            # Look up the command handler in the mapping table and dispatch
            handler_func = COMMAND_HANDLERS.get(cmd)
            if handler_func is not None:
                result = handler_func(arguments)
                logger.info(
                    "handle_debug_command: cmd=%s id=%s handler_returned=%r response_sent=%s",
                    cmd,
                    cmd_id,
                    result,
                    transport.response_sent,
                )
                # We no longer send an automatic acknowledgement.  the handler is
                # responsible for calling ``session.safe_send_response`` when it
                # has finished processing.  If the transport still shows
                # ``response_sent`` == `False` after the handler has run, log a
                # warning so that misbehaving handlers are easier to spot.
                if cmd_id is not None and not transport.response_sent:
                    logger.warning(
                        "handle_debug_command: no response sent by handler for cmd=%s id=%s",
                        cmd,
                        cmd_id,
                    )
                elif cmd_id is not None and transport.response_sent:
                    # explicit acknowledgement already emitted by handler
                    logger.info(
                        "handle_debug_command: handler sent response for cmd=%s id=%s",
                        cmd,
                        cmd_id,
                    )
                # Signal resume for stepping/continue/terminate commands so the
                # debugger thread unblocks from process_queued_commands_launcher.
                if cmd in _RESUME_COMMANDS:
                    active_session.signal_resume()
            else:
                active_session.safe_send(
                    "response",
                    id=cmd_id,
                    success=False,
                    message=f"Unknown command: {cmd}",
                )


def _get_thread_ident() -> int:
    """Return the current thread id."""
    return command_handler_helpers.get_thread_ident(threading)


def _set_dbg_stepping_flag(dbg: CommandHandlerDebuggerLike) -> None:
    """Ensure the debugger reports a stepping state."""
    command_handler_helpers.set_dbg_stepping_flag(dbg)


def _active_session() -> _d_shared.DebugSession:
    """Return the context-local active debug session."""
    return _d_shared.get_active_session()


def _active_debugger() -> CommandHandlerDebuggerLike | None:
    """Return the active debugger from the context-local session."""
    return cast("CommandHandlerDebuggerLike | None", _active_session().debugger)


# =============================================================================
# Public API Functions (for backward compatibility with (dbg, arguments) signature)
# These are called by tests that use the old signature.
# =============================================================================


# =============================================================================
# Registered Handlers (decorated with @command_handler)
# These take only (arguments) and get dbg from active session.
# =============================================================================


@command_handler("setBreakpoints")
def _cmd_set_breakpoints(
    arguments: SetBreakpointsArguments | dict[str, Any] | None,
) -> None:
    source = (
        (arguments or {}).get("source", {}).get("path", "<unknown>")
        if isinstance(arguments, dict)
        else "<unknown>"
    )
    logger.debug("setBreakpoints: source=%s", source)
    session = _active_session()
    if session.debugger:
        result = breakpoint_handlers.handle_set_breakpoints_impl(
            session,
            cast("dict[str, Any] | None", arguments),
        )
        if result:
            session.safe_send_response(**result)
    else:
        # gracefully acknowledge even without a debugger; this avoids a
        # hung client when the adapter erroneously sends breakpoints early.
        session.safe_send_response(success=False, message="No active debugger")


@command_handler("setFunctionBreakpoints")
def _cmd_set_function_breakpoints(arguments: SetFunctionBreakpointsArguments) -> None:
    session = _active_session()
    result = None
    if session.debugger:
        result = breakpoint_handlers.handle_set_function_breakpoints_impl(
            session,
            cast("dict[str, Any] | None", arguments),
        )
    # always acknowledge; include body if the helper returned one
    session.safe_send_response(**(result or {"success": True}))


@command_handler("setExceptionBreakpoints")
def _cmd_set_exception_breakpoints(
    arguments: SetExceptionBreakpointsArguments | dict[str, Any] | None,
) -> None:
    session = _active_session()
    result = None
    if session.debugger:
        result = breakpoint_handlers.handle_set_exception_breakpoints_impl(
            session,
            cast("dict[str, Any] | None", arguments),
        )
    session.safe_send_response(**(result or {"success": True}))


@command_handler("continue")
def _cmd_continue(arguments: ContinueArguments | dict[str, Any] | None) -> None:
    session = _active_session()
    if session.debugger:
        stepping_handlers.handle_continue_impl(session, cast("dict[str, Any] | None", arguments))
    # always ack the request
    session.safe_send_response(success=True)


@command_handler("next")
def _cmd_next(arguments: NextArguments | dict[str, Any] | None) -> None:
    session = _active_session()
    if session.debugger:
        stepping_handlers.handle_next_impl(
            session,
            cast("dict[str, Any] | None", arguments),
            _get_thread_ident,
            _set_dbg_stepping_flag,
        )
    session.safe_send_response(success=True)


@command_handler("stepIn")
def _cmd_step_in(arguments: StepInArguments | dict[str, Any] | None) -> None:
    session = _active_session()
    if session.debugger:
        stepping_handlers.handle_step_in_impl(
            session,
            cast("dict[str, Any] | None", arguments),
            _get_thread_ident,
            _set_dbg_stepping_flag,
        )
    session.safe_send_response(success=True)


@command_handler("stepOut")
def _cmd_step_out(arguments: StepOutArguments | dict[str, Any] | None) -> None:
    session = _active_session()
    if session.debugger:
        stepping_handlers.handle_step_out_impl(
            session,
            cast("dict[str, Any] | None", arguments),
            _get_thread_ident,
            _set_dbg_stepping_flag,
        )
    session.safe_send_response(success=True)


@command_handler("pause")
def _cmd_pause(arguments: PauseArguments | dict[str, Any] | None) -> None:
    session = _active_session()
    if session.debugger:
        stepping_handlers.handle_pause_impl(
            session,
            cast("dict[str, Any] | None", arguments),
            _get_thread_ident,
            logger,
        )
    session.safe_send_response(success=True)


@command_handler("gotoTargets")
def _cmd_goto_targets(
    arguments: GotoTargetsArguments | dict[str, Any] | None,
) -> None:
    session = _active_session()
    result: dict[str, Any]
    dbg = session.debugger
    if dbg is None:
        body: GotoTargetsResponseBody = {"targets": []}
        result = {"success": True, "body": body}
    else:
        payload = cast("GotoTargetsArguments", arguments or {})
        frame_id = payload.get("frameId")
        line = payload.get("line")
        if not isinstance(frame_id, int) or not isinstance(line, int):
            result = {
                "success": False,
                "message": "gotoTargets requires integer frameId and line",
            }
        else:
            resolver = getattr(dbg, "goto_targets", None)
            if not callable(resolver):
                body: GotoTargetsResponseBody = {"targets": []}
                result = {"success": True, "body": body}
            else:
                try:
                    targets = resolver(frame_id, line)
                except Exception as exc:
                    logger.exception("Error handling gotoTargets command")
                    result = {"success": False, "message": f"gotoTargets failed: {exc!s}"}
                else:
                    normalized: list[GotoTarget] = targets if isinstance(targets, list) else []
                    body: GotoTargetsResponseBody = {"targets": normalized}
                    result = {"success": True, "body": body}
    # send the computed response
    session.safe_send_response(**result)


@command_handler("goto")
def _cmd_goto(arguments: GotoArguments | dict[str, Any] | None) -> None:
    session = _active_session()
    dbg = session.debugger
    if dbg is None:
        result = {"success": False, "message": "No active debugger"}
    else:
        payload = cast("GotoArguments", arguments or {})
        thread_id = payload.get("threadId")
        target_id = payload.get("targetId")
        if not isinstance(thread_id, int) or not isinstance(target_id, int):
            result = {
                "success": False,
                "message": "goto requires integer threadId and targetId",
            }
        else:
            goto_fn = getattr(dbg, "goto", None)
            if not callable(goto_fn):
                result = {"success": False, "message": "goto not supported"}
            else:
                try:
                    goto_fn(thread_id, target_id)
                except Exception as exc:
                    logger.exception("Error handling goto command")
                    result = {"success": False, "message": f"goto failed: {exc!s}"}
                else:
                    result = {"success": True, "body": {}}
    session.safe_send_response(**result)


@command_handler("stackTrace")
def _cmd_stack_trace(
    arguments: StackTraceArguments | dict[str, Any] | None,
) -> None:
    session = _active_session()
    if session.debugger:
        result = stack_handlers.handle_stack_trace_impl(
            session,
            cast("dict[str, Any] | None", arguments),
            get_thread_ident=_get_thread_ident,
        )
        if result:
            session.safe_send_response(**result)
    else:
        # no debugger configured; still acknowledge to satisfy clients/tests
        session.safe_send_response(success=True)


@command_handler("threads")
def _cmd_threads(arguments: dict[str, Any] | None = None) -> None:
    session = _active_session()
    if session.debugger:
        result = stack_handlers.handle_threads_impl(session, arguments)
        if result:
            session.safe_send_response(**result)
    else:
        session.safe_send_response(success=False, message="No active debugger")


@command_handler("scopes")
def _cmd_scopes(arguments: ScopesArguments | None) -> None:
    session = _active_session()
    if session.debugger:
        result = stack_handlers.handle_scopes_impl(
            session, cast("dict[str, Any] | None", arguments)
        )
        if result:
            session.safe_send_response(**result)
    else:
        session.safe_send_response(success=False, message="No active debugger")


@command_handler("variables")
def _cmd_variables(arguments: VariablesArguments | dict[str, Any] | None) -> None:
    session = _active_session()
    dbg = session.debugger
    if not dbg:
        session.safe_send_response(success=False, message="No active debugger")
        return

    # helpers used by the variable resolver
    def _make_variable_fn(
        runtime_dbg: DebuggerLike | None,
        name: str,
        value: object,
        frame: object | None,
    ) -> dict[str, Any]:
        return command_handler_helpers.make_variable(
            runtime_dbg,
            name,
            value,
            frame,
        )

    def _resolve_variables_for_reference(
        runtime_dbg: CommandHandlerDebuggerLike | None,
        frame_info: object,
    ) -> list[dict[str, Any]]:
        def _extract_from_mapping(
            helper_dbg: DebuggerLike | None,
            mapping: dict[str, object],
            frame: object,
        ) -> list[dict[str, Any]]:
            return command_handler_helpers.extract_variables_from_mapping(
                helper_dbg,
                mapping,
                frame,
                make_variable_fn=_make_variable_fn,
            )

        return command_handler_helpers.resolve_variables_for_reference(
            runtime_dbg,
            frame_info,
            make_variable_fn=_make_variable_fn,
            extract_variables_from_mapping_fn=_extract_from_mapping,
        )

    result = variable_handlers.handle_variables_impl(
        session,
        cast("dict[str, Any] | None", arguments),
        _resolve_variables_for_reference,
    )

    if result:
        session.safe_send_response(**result)
    else:
        # the helper returned nothing, treat as failure so client isn't left
        # waiting for a reply.
        session.safe_send_response(success=False, message="No active debugger")


@command_handler("setVariable")
def _cmd_set_variable(arguments: SetVariableArguments | dict[str, Any] | None) -> None:
    session = _active_session()
    dbg = session.debugger
    if dbg:

        def _make_variable_fn(
            runtime_dbg: DebuggerLike | None,
            name: str,
            value: object,
            frame: object | None,
        ) -> dict[str, Any]:
            return command_handler_helpers.make_variable(
                runtime_dbg,
                name,
                value,
                frame,
            )

        conversion_failed_sentinel = object()

        def _try_convert(
            value_str: str,
            frame: FrameType | None = None,
            parent_obj: object | None = None,
        ) -> object:
            try:
                return convert_value_with_context(value_str, frame, parent_obj)
            except (AttributeError, NameError, SyntaxError, TypeError, ValueError):
                logger.debug("Context conversion fallback failed", exc_info=True)
                return conversion_failed_sentinel

        result = variable_handlers.handle_set_variable_impl(
            session,
            cast("dict[str, Any] | None", arguments),
            object_member_deps=command_handler_helpers.ObjectMemberDependencies(
                assign_to_parent_member_fn=command_handler_helpers.assign_to_parent_member,
                try_custom_convert=_try_convert,
                conversion_failed_sentinel=conversion_failed_sentinel,
                convert_value_with_context_fn=convert_value_with_context,
                error_response_fn=command_handler_helpers.error_response,
                conversion_error_message=_CONVERSION_ERROR_MESSAGE,
                get_state_debugger=_active_debugger,
                make_variable_fn=_make_variable_fn,
                logger=logger,
            ),
            scope_variable_deps=command_handler_helpers.ScopeVariableDependencies(
                evaluate_with_policy_fn=evaluate_with_policy,
                try_custom_convert=_try_convert,
                conversion_failed_sentinel=conversion_failed_sentinel,
                convert_value_with_context_fn=convert_value_with_context,
                error_response_fn=command_handler_helpers.error_response,
                conversion_error_message=_CONVERSION_ERROR_MESSAGE,
                get_state_debugger=_active_debugger,
                make_variable_fn=_make_variable_fn,
                logger=logger,
            ),
        )
        if result:
            session.safe_send("setVariable", **result)
            session.safe_send_response(**result)
    else:
        session.safe_send_response(success=False, message="No active debugger")


@command_handler("evaluate")
def _cmd_evaluate(arguments: EvaluateArguments | dict[str, Any] | None) -> None:
    session = _active_session()
    result = None
    if session.debugger:
        result = variable_handlers.handle_evaluate_impl(
            session,
            cast("dict[str, Any] | None", arguments),
            evaluate_with_policy=evaluate_with_policy,
            format_evaluation_error=variable_handlers.format_evaluation_error,
            logger=logger,
        )
        if result:
            session.safe_send_response(**result)
    else:
        session.safe_send_response(success=False, message="No active debugger")


@command_handler("setExpression")
def _cmd_set_expression(arguments: SetExpressionArguments | dict[str, Any] | None = None) -> None:
    session = _active_session()
    if session.debugger:
        result = variable_handlers.handle_set_expression_impl(
            session,
            cast("SetExpressionArguments | None", arguments),
            evaluate_with_policy=evaluate_with_policy,
            logger=logger,
        )
        if result:
            session.safe_send_response(**result)
    else:
        session.safe_send_response(success=False, message="No active debugger")


@command_handler("setDataBreakpoints")
def _cmd_set_data_breakpoints(
    arguments: SetDataBreakpointsArguments | dict[str, Any] | None,
) -> None:
    session = _active_session()
    result = None
    if session.debugger:
        result = variable_handlers.handle_set_data_breakpoints_impl(
            session,
            cast("dict[str, Any] | None", arguments),
            logger,
        )
        if result:
            session.safe_send_response(**result)
    else:
        session.safe_send_response(success=False, message="No active debugger")


@command_handler("dataBreakpointInfo")
def _cmd_data_breakpoint_info(
    arguments: DataBreakpointInfoArguments | dict[str, Any] | None,
) -> None:
    session = _active_session()
    result = None
    if session.debugger:
        result = variable_handlers.handle_data_breakpoint_info_impl(
            session,
            cast("dict[str, Any] | None", arguments),
            max_value_repr_len=MAX_VALUE_REPR_LEN,
            trunc_suffix=_TRUNC_SUFFIX,
        )
        if result:
            session.safe_send_response(**result)
    else:
        session.safe_send_response(success=False, message="No active debugger")


@command_handler("exceptionInfo")
def _cmd_exception_info(arguments: dict[str, Any]) -> None:
    """Handle exceptionInfo request."""
    lifecycle_handlers.cmd_exception_info(
        arguments,
        state=_active_session(),
    )


@command_handler("configurationDone")
def _cmd_configuration_done(_arguments: dict[str, Any] | None = None) -> None:
    logger.info("configurationDone received")
    lifecycle_handlers.handle_configuration_done_impl()
    # Acknowledge the request so the TS adapter's sendRequestToPython resolves.
    # We must send the response *and flush* before setting the event that
    # unblocks main(), because main() will immediately start the program
    # which can emit events (stopped, thread, etc.).  If the adapter hasn't
    # received the configurationDone response yet, the ordering is violated.
    session = _active_session()
    session.safe_send_response(success=True)
    _flush_transport(session)
    # Unblock the launcher main thread which is waiting before starting the program
    session.configuration_done_event.set()
    logger.debug("configurationDone: configuration_done_event set")


@command_handler("terminate")
def _cmd_terminate(_arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    logger.info("terminate received")
    state = _active_session()
    result = lifecycle_handlers.handle_terminate_impl(
        state=state,
    )
    # Send the response and ensure it is flushed to the wire *before*
    # calling exit_func (which may invoke os._exit and kill the process
    # immediately, potentially before the kernel flushes the socket buffer).
    state.safe_send_response(**result)
    _flush_transport(state)
    state.exit_func(0)
    return result  # won't reach if exit_func raises, but satisfies type


@command_handler("initialize")
def _cmd_initialize(_arguments: dict[str, Any] | None = None) -> None:
    logger.info("initialize received")
    result = lifecycle_handlers.handle_initialize_impl()
    session = _active_session()
    logger.info(
        "initialize: handle_initialize_impl returned result=%r  request_id=%s  response_sent_before=%s",
        type(result).__name__,
        session.request_id,
        session.transport.response_sent,
    )
    if result:
        ok = session.safe_send_response(**result)
        logger.info(
            "initialize: safe_send_response returned %s  response_sent_after=%s",
            ok,
            session.transport.response_sent,
        )
    else:
        logger.info("initialize: result is falsy — skipping safe_send_response")
    # After responding to initialize, emit the 'initialized' event so the client
    # knows it can send setBreakpoints / setExceptionBreakpoints / configurationDone.
    session.safe_send("initialized")
    logger.info("initialize: sent initialized event")


@command_handler("launch")
def _cmd_launch(_arguments: dict[str, Any] | None = None) -> None:
    """Acknowledge the launch request.

    When the launcher is spawned directly inside VS Code's integrated terminal
    the TS adapter proxies the DAP ``launch`` request over IPC.  The launcher
    already knows the target from its CLI arguments, so we simply acknowledge
    the request so that VS Code continues with the normal DAP sequence
    (``setBreakpoints`` → ``configurationDone``).
    """
    logger.info("launch received")
    session = _active_session()
    logger.info(
        "launch: request_id=%s  response_sent_before=%s",
        session.request_id,
        session.transport.response_sent,
    )
    ok = session.safe_send_response(success=True)
    logger.info(
        "launch: safe_send_response returned %s  response_sent_after=%s",
        ok,
        session.transport.response_sent,
    )


@command_handler("disconnect")
def _cmd_disconnect(_arguments: dict[str, Any] | None = None) -> None:
    """Handle the DAP disconnect request.

    Marks the session as terminated and unblocks the debugger thread so the
    launcher can exit cleanly.
    """
    logger.info("disconnect received")
    session = _active_session()
    session.terminate_session()
    session.safe_send_response(success=True)


@command_handler("restart")
def _cmd_restart(_arguments: dict[str, Any] | None = None) -> None:
    lifecycle_handlers.handle_restart_impl(
        state=_active_session(),
        logger=logger,
    )


@command_handler("loadedSources")
def _cmd_loaded_sources(_arguments: dict[str, Any] | None = None) -> None:
    source_handlers.handle_loaded_sources(
        _active_session(),
    )


@command_handler("breakpointLocations")
def _cmd_breakpoint_locations(arguments: dict[str, Any] | None = None) -> None:
    session = _active_session()
    result = breakpoint_handlers.handle_breakpoint_locations_impl(
        cast("dict[str, Any] | None", arguments),
    )
    if result:
        session.safe_send_response(**result)


@command_handler("source")
def _cmd_source(arguments: dict[str, Any] | None = None) -> None:
    source_handlers.handle_source(
        arguments,
        _active_session(),
    )


@command_handler("modules")
def _cmd_modules(arguments: dict[str, Any] | None = None) -> None:
    source_handlers.handle_modules(
        arguments,
        _active_session(),
    )


# ---------------------------------------------------------------------------
# TypedDicts for the hotReload command handler response
# ---------------------------------------------------------------------------


class _HotReloadHandlerSuccess(TypedDict):
    """Response shape returned by the hotReload handler on success."""

    success: Literal[True]
    body: dict[str, Any]


class _HotReloadHandlerError(TypedDict):
    """Response shape returned by the hotReload handler on failure."""

    success: Literal[False]
    message: str


@command_handler("hotReload")
def _cmd_hot_reload(
    arguments: dict[str, Any] | None,
) -> _HotReloadHandlerSuccess | _HotReloadHandlerError:
    """Handle the 'hotReload' command in the debuggee process.

    Performs a live reload of the Python source file identified by
    ``arguments["path"]``, rebinds live stack frames to the new code objects,
    and returns a response dict that ``DapMappingProvider`` will forward back
    to the adapter via the IPC channel.

    The return value must have a ``"success"`` key so that
    :class:`~dapper.shared.debug_shared.CommandDispatcher` recognises it as a
    structured response and echoes the command ``id`` back to the adapter.
    """
    # Deferred import: reload_helpers is a shared module that must not be
    # loaded at command_handlers import time to avoid slowing down startup.
    from dapper.shared import reload_helpers  # noqa: PLC0415

    args: dict[str, Any] = arguments or {}
    path: str = args.get("path", "")
    options: HotReloadOptions | None = cast("HotReloadOptions | None", args.get("options"))

    try:
        result = reload_helpers.perform_reload(path, options)
        # Convert PerformReloadResult (TypedDict) to a plain dict so the
        # protocol layer can safely merge it into the IPC response envelope.
        return _HotReloadHandlerSuccess(success=True, body=dict(result))
    except Exception as exc:
        return _HotReloadHandlerError(success=False, message=str(exc))
