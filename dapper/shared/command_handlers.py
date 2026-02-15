"""
Canonical DAP command handler implementations and registry for the debuggee process.

This module provides:
1. The `COMMAND_HANDLERS` registry populated via the `@command_handler` decorator
2. The canonical handler implementations for all DAP commands
3. The `handle_debug_command()` entry point for command dispatch

Both IPC pathways dispatch through the `COMMAND_HANDLERS` registry:
- Pipe-based IPC: `debug_launcher.py` calls `handle_debug_command()`
- Socket-based IPC: `ipc_receiver.py` wraps `COMMAND_HANDLERS` in a provider

Dependencies:
- `dapper.launcher.comm.send_debug_message` for IPC message output
- `dapper.shared.debug_shared.get_active_session` for debugger session state
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING
from typing import Any
from typing import Callable
from typing import Protocol
from typing import cast

from dapper.launcher.comm import send_debug_message
from dapper.shared import breakpoint_handlers
from dapper.shared import command_handler_helpers
from dapper.shared import debug_shared as _d_shared
from dapper.shared import lifecycle_handlers
from dapper.shared import source_handlers
from dapper.shared import stack_handlers
from dapper.shared import stepping_handlers
from dapper.shared import variable_command_runtime
from dapper.shared import variable_handlers
from dapper.shared.value_conversion import convert_value_with_context
from dapper.shared.value_conversion import evaluate_with_policy

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from dapper.protocol.data_breakpoints import DataBreakpointInfoArguments

    # Data breakpoints are defined separately
    from dapper.protocol.data_breakpoints import SetDataBreakpointsArguments
    from dapper.protocol.debugger_protocol import DebuggerLike
    from dapper.protocol.requests import ContinueArguments
    from dapper.protocol.requests import EvaluateArguments
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


CommandPayload = dict[str, Any]


class SafeSendDebugMessageFn(Protocol):
    def __call__(self, message_type: str, **payload: Any) -> bool: ...


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


_error_response: Callable[[str], dict[str, Any]] = command_handler_helpers.error_response


_safe_send_debug_message: SafeSendDebugMessageFn = (
    command_handler_helpers.build_safe_send_debug_message(
        lambda: send_debug_message,
        logger,
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
        arguments = command.get("arguments", {})
        # Ensure the command name is a string before looking up the handler
        if not isinstance(cmd, str):
            _safe_send_debug_message(
                "response",
                request_seq=command.get("seq"),
                success=False,
                message=f"Invalid command: {cmd!r}",
            )
            return

        # Look up the command handler in the mapping table and dispatch
        handler_func = COMMAND_HANDLERS.get(cmd)
        if handler_func is not None:
            handler_func(arguments)
        else:
            _safe_send_debug_message(
                "response",
                request_seq=command.get("seq"),
                success=False,
                message=f"Unknown command: {cmd}",
            )


def _get_thread_ident() -> int:
    """Return the current thread id."""
    return command_handler_helpers.get_thread_ident(threading)


def _set_dbg_stepping_flag(dbg: DebuggerLike) -> None:
    """Ensure the debugger reports a stepping state."""
    command_handler_helpers.set_dbg_stepping_flag(dbg)


def _active_session() -> _d_shared.DebugSession:
    """Return the context-local active debug session."""
    return _d_shared.get_active_session()


def _active_debugger() -> DebuggerLike | None:
    """Return the active debugger from the context-local session."""
    return cast("DebuggerLike | None", _active_session().debugger)


# =============================================================================
# Public API Functions (for backward compatibility with (dbg, arguments) signature)
# These are called by tests that use the old signature.
# =============================================================================


# =============================================================================
# Registered Handlers (decorated with @command_handler)
# These take only (arguments) and get dbg from active session.
# =============================================================================


@command_handler("setBreakpoints")
def _cmd_set_breakpoints(arguments: SetBreakpointsArguments | dict[str, Any] | None) -> None:
    dbg = _active_debugger()
    if dbg:
        breakpoint_handlers.handle_set_breakpoints_impl(
            dbg,
            cast("dict[str, Any] | None", arguments),
            _safe_send_debug_message,
            logger,
        )


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


@command_handler("stackTrace")
def _cmd_stack_trace(arguments: StackTraceArguments | dict[str, Any] | None) -> None:
    dbg = _active_debugger()
    if dbg:
        stack_handlers.handle_stack_trace_impl(
            dbg,
            cast("dict[str, Any] | None", arguments),
            get_thread_ident=_get_thread_ident,
            safe_send_debug_message=_safe_send_debug_message,
        )


@command_handler("threads")
def _cmd_threads(arguments: dict[str, Any] | None = None) -> None:
    dbg = _active_debugger()
    if dbg:
        stack_handlers.handle_threads_impl(dbg, arguments, _safe_send_debug_message)


@command_handler("scopes")
def _cmd_scopes(arguments: ScopesArguments | dict[str, Any] | None) -> None:
    dbg = _active_debugger()
    if dbg:
        stack_handlers.handle_scopes_impl(
            dbg,
            cast("dict[str, Any] | None", arguments),
            safe_send_debug_message=_safe_send_debug_message,
            var_ref_tuple_size=VAR_REF_TUPLE_SIZE,
        )


@command_handler("variables")
def _cmd_variables(arguments: VariablesArguments | dict[str, Any] | None) -> None:
    dbg = _active_debugger()
    if dbg:

        def _make_variable_fn(
            runtime_dbg: object | None,
            name: str,
            value: object,
            frame: object | None,
        ) -> dict[str, Any]:
            return variable_command_runtime.make_variable_runtime(
                runtime_dbg,
                name,
                value,
                frame,
                make_variable_helper=command_handler_helpers.make_variable,
                fallback_make_variable=_d_shared.make_variable_object,
                simple_fn_argcount=SIMPLE_FN_ARGCOUNT,
            )

        def _resolve_variables_for_reference(
            runtime_dbg: object | None,
            frame_info: object,
        ) -> list[dict[str, Any]]:
            return variable_command_runtime.resolve_variables_for_reference_runtime(
                runtime_dbg,
                frame_info,
                resolve_variables_helper=command_handler_helpers.resolve_variables_for_reference,
                extract_variables_from_mapping_helper=command_handler_helpers.extract_variables_from_mapping,
                make_variable_fn=_make_variable_fn,
                var_ref_tuple_size=VAR_REF_TUPLE_SIZE,
            )

        variable_handlers.handle_variables_impl(
            dbg,
            cast("dict[str, Any] | None", arguments),
            _safe_send_debug_message,
            _resolve_variables_for_reference,
        )


@command_handler("setVariable")
def _cmd_set_variable(arguments: SetVariableArguments | dict[str, Any] | None) -> None:
    dbg = _active_debugger()
    if dbg:

        def _make_variable_fn(
            runtime_dbg: object | None,
            name: str,
            value: object,
            frame: object | None,
        ) -> dict[str, Any]:
            return variable_command_runtime.make_variable_runtime(
                runtime_dbg,
                name,
                value,
                frame,
                make_variable_helper=command_handler_helpers.make_variable,
                fallback_make_variable=_d_shared.make_variable_object,
                simple_fn_argcount=SIMPLE_FN_ARGCOUNT,
            )

        result = variable_handlers.handle_set_variable_command_impl(
            dbg,
            cast("dict[str, Any] | None", arguments),
            dependencies=variable_command_runtime.build_set_variable_dependencies(
                convert_value_with_context_fn=convert_value_with_context,
                evaluate_with_policy_fn=evaluate_with_policy,
                set_object_member_helper=command_handler_helpers.set_object_member,
                set_scope_variable_helper=command_handler_helpers.set_scope_variable,
                assign_to_parent_member_fn=command_handler_helpers.assign_to_parent_member,
                error_response_fn=command_handler_helpers.error_response,
                conversion_error_message=_CONVERSION_ERROR_MESSAGE,
                get_state_debugger=_active_debugger,
                make_variable_fn=_make_variable_fn,
                logger=logger,
                var_ref_tuple_size=VAR_REF_TUPLE_SIZE,
            ),
        )
        if result:
            _safe_send_debug_message("setVariable", **result)


@command_handler("evaluate")
def _cmd_evaluate(arguments: EvaluateArguments | dict[str, Any] | None) -> None:
    dbg = _active_debugger()
    if dbg:
        variable_handlers.handle_evaluate_impl(
            dbg,
            cast("dict[str, Any] | None", arguments),
            evaluate_with_policy=evaluate_with_policy,
            format_evaluation_error=variable_handlers.format_evaluation_error,
            safe_send_debug_message=_safe_send_debug_message,
            logger=logger,
        )


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
    lifecycle_handlers.handle_configuration_done_impl()


@command_handler("terminate")
def _cmd_terminate(_arguments: dict[str, Any] | None = None) -> None:
    lifecycle_handlers.handle_terminate_impl(
        safe_send_debug_message=_safe_send_debug_message,
        state=_active_session(),
    )


@command_handler("initialize")
def _cmd_initialize(_arguments: dict[str, Any] | None = None) -> None:
    result = lifecycle_handlers.handle_initialize_impl()
    if result:
        _safe_send_debug_message("response", **result)


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
