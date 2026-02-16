"""Runtime glue utilities for variable-domain command dispatch."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import Callable

if TYPE_CHECKING:
    from dapper.protocol.debugger_protocol import CommandHandlerDebuggerLike
    from dapper.protocol.debugger_protocol import DebuggerLike
    from dapper.shared.command_handler_helpers import Payload


def make_variable_runtime(
    dbg: DebuggerLike | None,
    name: str,
    value: Any,
    frame: object | None,
    *,
    make_variable_helper: Callable[..., Any],
    fallback_make_variable: Callable[..., Any],
    simple_fn_argcount: int,
) -> dict[str, Any]:
    """Create a variable payload object using injected helper dependencies."""
    return make_variable_helper(
        dbg,
        name,
        value,
        frame,
        fallback_make_variable=fallback_make_variable,
        simple_fn_argcount=simple_fn_argcount,
    )


def resolve_variables_for_reference_runtime(
    dbg: CommandHandlerDebuggerLike | None,
    frame_info: object,
    *,
    resolve_variables_helper: Callable[..., list[Payload]],
    extract_variables_from_mapping_helper: Callable[..., list[Payload]],
    make_variable_fn: Callable[..., Payload],
    var_ref_tuple_size: int,
) -> list[Payload]:
    """Resolve variable objects for a var reference using injected helpers."""

    def _extract_from_mapping(
        helper_dbg: DebuggerLike | None, mapping: dict[str, object], frame: object
    ) -> list[Payload]:
        return extract_variables_from_mapping_helper(
            helper_dbg,
            mapping,
            frame,
            make_variable_fn=make_variable_fn,
        )

    return resolve_variables_helper(
        dbg,
        frame_info,
        make_variable_fn=make_variable_fn,
        extract_variables_from_mapping_fn=_extract_from_mapping,
        var_ref_tuple_size=var_ref_tuple_size,
    )


def build_set_variable_dependencies(  # noqa: PLR0913
    *,
    convert_value_with_context_fn: Any,
    evaluate_with_policy_fn: Any,
    set_object_member_helper: Any,
    set_scope_variable_helper: Any,
    assign_to_parent_member_fn: Any,
    error_response_fn: Any,
    conversion_error_message: str,
    get_state_debugger: Any,
    make_variable_fn: Any,
    logger: Any,
    var_ref_tuple_size: int,
) -> dict[str, Any]:
    """Build dependency bundle for variable set command orchestration."""
    return {
        "convert_value_with_context_fn": convert_value_with_context_fn,
        "evaluate_with_policy_fn": evaluate_with_policy_fn,
        "set_object_member_helper": set_object_member_helper,
        "set_scope_variable_helper": set_scope_variable_helper,
        "assign_to_parent_member_fn": assign_to_parent_member_fn,
        "error_response_fn": error_response_fn,
        "conversion_error_message": conversion_error_message,
        "get_state_debugger": get_state_debugger,
        "make_variable_fn": make_variable_fn,
        "logger": logger,
        "var_ref_tuple_size": var_ref_tuple_size,
    }
