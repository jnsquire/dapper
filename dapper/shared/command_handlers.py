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

from dapper.shared import breakpoint_handlers
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
    from dapper.protocol.data_breakpoints import DataBreakpointInfoArguments

    # Data breakpoints are defined separately
    from dapper.protocol.data_breakpoints import SetDataBreakpointsArguments
    from dapper.protocol.debugger_protocol import CommandHandlerDebuggerLike
    from dapper.protocol.debugger_protocol import DebuggerLike
    from dapper.protocol.requests import ContinueArguments
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
    from dapper.protocol.requests import SetExceptionBreakpointsArguments
    from dapper.protocol.requests import SetFunctionBreakpointsArguments
    from dapper.protocol.requests import SetVariableArguments
    from dapper.protocol.requests import StackTraceArguments
    from dapper.protocol.requests import StepInArguments
    from dapper.protocol.requests import StepOutArguments
    from dapper.protocol.requests import VariablesArguments
    from dapper.shared.command_handler_helpers import Payload


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

VAR_REF_TUPLE_SIZE = 2
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


_safe_send_debug_message: command_handler_helpers.SafeSendDebugMessageFn = (
    command_handler_helpers.build_safe_send_debug_message(
        lambda: send_debug_message,
        cast("command_handler_helpers.LoggerLike", logger),
        dynamic=True,
    )
)


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
    """
    active_session = session if session is not None else _d_shared.get_active_session()
    with _d_shared.use_session(active_session):
        cmd = command.get("command")
        cmd_id = command.get("id")  # request id to echo back in the response
        arguments = command.get("arguments", {})
        logger.debug("handle_debug_command: cmd=%s id=%s", cmd, cmd_id)
        # Ensure the command name is a string before looking up the handler
        if not isinstance(cmd, str):
            _safe_send_debug_message(
                "response",
                id=cmd_id,
                success=False,
                message=f"Invalid command: {cmd!r}",
            )
            return

        # Scope the request lifecycle on the transport so
        # SessionTransport.send() auto-injects the request id into
        # outbound response messages.
        with active_session.transport.request_scope(cmd_id) as transport:
            # Look up the command handler in the mapping table and dispatch
            handler_func = COMMAND_HANDLERS.get(cmd)
            if handler_func is not None:
                result = handler_func(arguments)
                # If the adapter expects a response and one hasn't been sent
                # yet, send either the handler's return value or a default ack.
                if cmd_id is not None and not transport.response_sent:
                    if isinstance(result, dict) and "success" in result:
                        _safe_send_debug_message("response", **result)
                    else:
                        _safe_send_debug_message("response", success=True)
                # Signal resume for stepping/continue/terminate commands so the
                # debugger thread unblocks from process_queued_commands_launcher.
                if cmd in _RESUME_COMMANDS:
                    active_session.signal_resume()
            else:
                _safe_send_debug_message(
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
) -> dict[str, Any] | None:
    source = (
        (arguments or {}).get("source", {}).get("path", "<unknown>")
        if isinstance(arguments, dict)
        else "<unknown>"
    )
    logger.debug("setBreakpoints: source=%s", source)
    dbg = _active_debugger()
    if dbg:
        return breakpoint_handlers.handle_set_breakpoints_impl(
            dbg,
            cast("dict[str, Any] | None", arguments),
            _safe_send_debug_message,
            logger,
        )
    return None


@command_handler("setFunctionBreakpoints")
def _cmd_set_function_breakpoints(arguments: SetFunctionBreakpointsArguments) -> None:
    dbg = _active_debugger()
    if dbg:
        breakpoint_handlers.handle_set_function_breakpoints_impl(
            dbg,
            cast("dict[str, Any] | None", arguments),
        )


@command_handler("setExceptionBreakpoints")
def _cmd_set_exception_breakpoints(
    arguments: SetExceptionBreakpointsArguments | dict[str, Any] | None,
) -> None:
    dbg = _active_debugger()
    if dbg:
        breakpoint_handlers.handle_set_exception_breakpoints_impl(
            dbg,
            cast("dict[str, Any] | None", arguments),
        )


@command_handler("continue")
def _cmd_continue(arguments: ContinueArguments | dict[str, Any] | None) -> None:
    dbg = _active_debugger()
    if dbg:
        stepping_handlers.handle_continue_impl(dbg, cast("dict[str, Any] | None", arguments))


@command_handler("next")
def _cmd_next(arguments: NextArguments | dict[str, Any] | None) -> None:
    dbg = _active_debugger()
    if dbg:
        stepping_handlers.handle_next_impl(
            dbg,
            cast("dict[str, Any] | None", arguments),
            _get_thread_ident,
            _set_dbg_stepping_flag,
        )


@command_handler("stepIn")
def _cmd_step_in(arguments: StepInArguments | dict[str, Any] | None) -> None:
    dbg = _active_debugger()
    if dbg:
        stepping_handlers.handle_step_in_impl(
            dbg,
            cast("dict[str, Any] | None", arguments),
            _get_thread_ident,
            _set_dbg_stepping_flag,
        )


@command_handler("stepOut")
def _cmd_step_out(arguments: StepOutArguments | dict[str, Any] | None) -> None:
    dbg = _active_debugger()
    if dbg:
        stepping_handlers.handle_step_out_impl(
            dbg,
            cast("dict[str, Any] | None", arguments),
            _get_thread_ident,
            _set_dbg_stepping_flag,
        )


@command_handler("pause")
def _cmd_pause(arguments: PauseArguments | dict[str, Any] | None) -> None:
    dbg = _active_debugger()
    if dbg:
        stepping_handlers.handle_pause_impl(
            dbg,
            cast("dict[str, Any] | None", arguments),
            _get_thread_ident,
            _safe_send_debug_message,
            logger,
        )


@command_handler("gotoTargets")
def _cmd_goto_targets(
    arguments: GotoTargetsArguments | dict[str, Any] | None,
) -> dict[str, Any]:
    dbg = _active_debugger()
    if dbg is None:
        body: GotoTargetsResponseBody = {"targets": []}
        return {"success": True, "body": body}

    payload = cast("GotoTargetsArguments", arguments or {})
    frame_id = payload.get("frameId")
    line = payload.get("line")
    if not isinstance(frame_id, int) or not isinstance(line, int):
        return {
            "success": False,
            "message": "gotoTargets requires integer frameId and line",
        }

    resolver = getattr(dbg, "goto_targets", None)
    if not callable(resolver):
        body: GotoTargetsResponseBody = {"targets": []}
        return {"success": True, "body": body}

    try:
        targets = resolver(frame_id, line)
    except Exception as exc:
        logger.exception("Error handling gotoTargets command")
        return {"success": False, "message": f"gotoTargets failed: {exc!s}"}

    normalized: list[GotoTarget] = targets if isinstance(targets, list) else []
    body: GotoTargetsResponseBody = {"targets": normalized}
    return {"success": True, "body": body}


@command_handler("goto")
def _cmd_goto(arguments: GotoArguments | dict[str, Any] | None) -> dict[str, Any]:
    dbg = _active_debugger()
    if dbg is None:
        return {"success": False, "message": "No active debugger"}

    payload = cast("GotoArguments", arguments or {})
    thread_id = payload.get("threadId")
    target_id = payload.get("targetId")
    if not isinstance(thread_id, int) or not isinstance(target_id, int):
        return {
            "success": False,
            "message": "goto requires integer threadId and targetId",
        }

    goto_fn = getattr(dbg, "goto", None)
    if not callable(goto_fn):
        return {"success": False, "message": "goto not supported"}

    try:
        goto_fn(thread_id, target_id)
    except Exception as exc:
        logger.exception("Error handling goto command")
        return {"success": False, "message": f"goto failed: {exc!s}"}

    return {"success": True, "body": {}}


@command_handler("stackTrace")
def _cmd_stack_trace(
    arguments: StackTraceArguments | dict[str, Any] | None,
) -> dict[str, Any] | None:
    dbg = _active_debugger()
    if dbg:
        return stack_handlers.handle_stack_trace_impl(
            dbg,
            cast("dict[str, Any] | None", arguments),
            get_thread_ident=_get_thread_ident,
            safe_send_debug_message=_safe_send_debug_message,
        )
    return None


@command_handler("threads")
def _cmd_threads(arguments: dict[str, Any] | None = None) -> dict[str, Any] | None:
    dbg = _active_debugger()
    if dbg:
        return stack_handlers.handle_threads_impl(dbg, arguments, _safe_send_debug_message)
    return None


@command_handler("scopes")
def _cmd_scopes(arguments: ScopesArguments | dict[str, Any] | None) -> dict[str, Any] | None:
    dbg = _active_debugger()
    if dbg:
        return stack_handlers.handle_scopes_impl(
            dbg,
            cast("dict[str, Any] | None", arguments),
            safe_send_debug_message=_safe_send_debug_message,
            var_ref_tuple_size=VAR_REF_TUPLE_SIZE,
        )
    return None


@command_handler("variables")
def _cmd_variables(arguments: VariablesArguments | dict[str, Any] | None) -> Payload | None:
    dbg = _active_debugger()
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
                var_ref_tuple_size=VAR_REF_TUPLE_SIZE,
            )

        return variable_handlers.handle_variables_impl(
            dbg,
            cast("dict[str, Any] | None", arguments),
            _safe_send_debug_message,
            _resolve_variables_for_reference,
        )
    return None


@command_handler("setVariable")
def _cmd_set_variable(arguments: SetVariableArguments | dict[str, Any] | None) -> None:
    dbg = _active_debugger()
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

        result = variable_handlers.handle_set_variable_command_impl(
            dbg,
            cast("dict[str, Any] | None", arguments),
            dependencies=cast(
                "variable_handlers.SetVariableCommandDependencies",
                {
                    "convert_value_with_context_fn": convert_value_with_context,
                    "evaluate_with_policy_fn": evaluate_with_policy,
                    "set_object_member_helper": (
                        command_handler_helpers.set_object_member_with_dependencies
                    ),
                    "set_scope_variable_helper": (
                        command_handler_helpers.set_scope_variable_with_dependencies
                    ),
                    "assign_to_parent_member_fn": (
                        command_handler_helpers.assign_to_parent_member
                    ),
                    "error_response_fn": command_handler_helpers.error_response,
                    "conversion_error_message": _CONVERSION_ERROR_MESSAGE,
                    "get_state_debugger": _active_debugger,
                    "make_variable_fn": _make_variable_fn,
                    "logger": logger,
                    "var_ref_tuple_size": VAR_REF_TUPLE_SIZE,
                },
            ),
        )
        if result:
            _safe_send_debug_message("setVariable", **result)


@command_handler("evaluate")
def _cmd_evaluate(arguments: EvaluateArguments | dict[str, Any] | None) -> dict[str, Any] | None:
    dbg = _active_debugger()
    if dbg:
        return variable_handlers.handle_evaluate_impl(
            dbg,
            cast("dict[str, Any] | None", arguments),
            evaluate_with_policy=evaluate_with_policy,
            format_evaluation_error=variable_handlers.format_evaluation_error,
            safe_send_debug_message=_safe_send_debug_message,
            logger=logger,
        )
    return None


@command_handler("setDataBreakpoints")
def _cmd_set_data_breakpoints(
    arguments: SetDataBreakpointsArguments | dict[str, Any] | None,
) -> None:
    dbg = _active_debugger()
    if dbg:
        variable_handlers.handle_set_data_breakpoints_impl(
            dbg,
            cast("dict[str, Any] | None", arguments),
            logger,
        )


@command_handler("dataBreakpointInfo")
def _cmd_data_breakpoint_info(
    arguments: DataBreakpointInfoArguments | dict[str, Any] | None,
) -> None:
    dbg = _active_debugger()
    if dbg:
        variable_handlers.handle_data_breakpoint_info_impl(
            dbg,
            cast("dict[str, Any] | None", arguments),
            max_value_repr_len=MAX_VALUE_REPR_LEN,
            trunc_suffix=_TRUNC_SUFFIX,
        )


@command_handler("exceptionInfo")
def _cmd_exception_info(arguments: dict[str, Any]) -> None:
    """Handle exceptionInfo request."""
    lifecycle_handlers.cmd_exception_info(
        arguments,
        state=_active_session(),
        safe_send_debug_message=_safe_send_debug_message,
    )


@command_handler("configurationDone")
def _cmd_configuration_done(_arguments: dict[str, Any] | None = None) -> None:
    logger.info("configurationDone received")
    lifecycle_handlers.handle_configuration_done_impl()
    # Acknowledge the request so the TS adapter's sendRequestToPython resolves
    _safe_send_debug_message("response", success=True)
    # Unblock the launcher main thread which is waiting before starting the program
    _active_session().configuration_done_event.set()
    logger.debug("configurationDone: configuration_done_event set")


@command_handler("terminate")
def _cmd_terminate(_arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    logger.info("terminate received")
    state = _active_session()
    result = lifecycle_handlers.handle_terminate_impl(
        safe_send_debug_message=_safe_send_debug_message,
        state=state,
    )
    # Return here so that the dispatch sends the response first, then
    # the resume event (set inside handle_terminate_impl) unblocks the
    # debugger thread.  Call exit_func *after* the response is sent.
    _safe_send_debug_message("response", **result)
    state.exit_func(0)
    return result  # won't reach if exit_func raises, but satisfies type


@command_handler("initialize")
def _cmd_initialize(_arguments: dict[str, Any] | None = None) -> None:
    logger.info("initialize received")
    result = lifecycle_handlers.handle_initialize_impl()
    if result:
        _safe_send_debug_message("response", **result)
    # After responding to initialize, emit the 'initialized' event so the client
    # knows it can send setBreakpoints / setExceptionBreakpoints / configurationDone.
    _safe_send_debug_message("initialized")
    logger.debug("initialize: sent initialized event")


@command_handler("launch")
def _cmd_launch(_arguments: dict[str, Any] | None = None) -> None:
    """Acknowledge the launch request.

    When the launcher is spawned directly inside VS Code's integrated terminal
    the TS adapter proxies the DAP ``launch`` request over IPC.  The launcher
    already knows the target from its CLI arguments, so we simply acknowledge
    the request so that VS Code continues with the normal DAP sequence
    (``setBreakpoints`` → ``configurationDone``).
    """
    logger.info("launch acknowledged")
    _safe_send_debug_message("response", success=True)


@command_handler("disconnect")
def _cmd_disconnect(_arguments: dict[str, Any] | None = None) -> None:
    """Handle the DAP disconnect request.

    Marks the session as terminated and unblocks the debugger thread so the
    launcher can exit cleanly.
    """
    logger.info("disconnect received")
    session = _active_session()
    session.terminate_session()
    _safe_send_debug_message("response", success=True)


@command_handler("restart")
def _cmd_restart(_arguments: dict[str, Any] | None = None) -> None:
    lifecycle_handlers.handle_restart_impl(
        safe_send_debug_message=_safe_send_debug_message,
        state=_active_session(),
        logger=logger,
    )


@command_handler("loadedSources")
def _cmd_loaded_sources(_arguments: dict[str, Any] | None = None) -> None:
    source_handlers.handle_loaded_sources(_active_session(), _safe_send_debug_message)


@command_handler("source")
def _cmd_source(arguments: dict[str, Any] | None = None) -> None:
    source_handlers.handle_source(arguments, _active_session(), _safe_send_debug_message)


@command_handler("modules")
def _cmd_modules(arguments: dict[str, Any] | None = None) -> None:
    source_handlers.handle_modules(arguments, _safe_send_debug_message)


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
