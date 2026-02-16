"""Variable and evaluation DAP handler implementations."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Callable
from typing import Protocol
from typing import TypedDict

if TYPE_CHECKING:
    from logging import Logger

    from dapper.protocol.debugger_protocol import CommandHandlerDebuggerLike
    from dapper.protocol.debugger_protocol import DebuggerLike
    from dapper.shared.command_handler_helpers import Payload
    from dapper.shared.command_handler_helpers import SafeSendDebugMessageFn


class ResolveVariablesForReferenceFn(Protocol):
    def __call__(
        self, dbg: CommandHandlerDebuggerLike | None, frame_info: object, /
    ) -> list[Payload]: ...


class ErrorResponseFn(Protocol):
    def __call__(self, message: str) -> Payload: ...


class SetObjectMemberFn(Protocol):
    def __call__(self, parent_obj: object, name: str, value_str: str) -> Payload: ...


class SetScopeVariableFn(Protocol):
    def __call__(self, frame: object, scope: str, name: str, value_str: str) -> Payload: ...


class ConvertWithContextFn(Protocol):
    def __call__(
        self,
        value_str: str,
        frame: object | None = None,
        parent_obj: object | None = None,
    ) -> object: ...


class EvaluateWithPolicyFn(Protocol):
    def __call__(
        self,
        expression: str,
        frame: object,
        *,
        allow_builtins: bool = False,
    ) -> object: ...


class FormatEvaluationErrorFn(Protocol):
    def __call__(self, exc: Exception) -> str: ...


class SetVariableCommandDependencies(TypedDict):
    convert_value_with_context_fn: ConvertWithContextFn
    evaluate_with_policy_fn: EvaluateWithPolicyFn
    set_object_member_helper: Callable[..., Payload]
    set_scope_variable_helper: Callable[..., Payload]
    assign_to_parent_member_fn: Callable[[object, str, object], str | None]
    error_response_fn: ErrorResponseFn
    conversion_error_message: str
    get_state_debugger: Callable[[], DebuggerLike | None]
    make_variable_fn: Callable[[DebuggerLike | None, str, object, object | None], Payload]
    logger: Logger
    var_ref_tuple_size: int


def format_evaluation_error(
    exc: Exception,
    *,
    evaluation_error_message: str = "Evaluation failed",
    evaluation_policy_blocked_message: str = "Evaluation blocked by policy",
) -> str:
    """Format evaluation failures into a stable user-facing error string."""
    text = str(exc).lower()
    if "blocked by policy" in text:
        return f"<error: {evaluation_policy_blocked_message}>"
    return f"<error: {evaluation_error_message}>"


def handle_variables_impl(
    dbg: CommandHandlerDebuggerLike | None,
    arguments: Payload | None,
    safe_send_debug_message: SafeSendDebugMessageFn,
    resolve_variables_for_reference: ResolveVariablesForReferenceFn,
) -> Payload | None:
    """Handle variables command implementation."""
    arguments = arguments or {}
    variables_reference = arguments.get("variablesReference")

    variables: list[Payload] = []
    if not (
        dbg
        and isinstance(variables_reference, int)
        and variables_reference in getattr(dbg.var_manager, "var_refs", {})
    ):
        safe_send_debug_message(
            "variables", variablesReference=variables_reference, variables=variables
        )
        return None

    frame_info = dbg.var_manager.var_refs[variables_reference]
    variables = resolve_variables_for_reference(dbg, frame_info)

    safe_send_debug_message(
        "variables", variablesReference=variables_reference, variables=variables
    )
    return {"success": True, "body": {"variables": variables}}


def handle_set_variable_impl(
    dbg: CommandHandlerDebuggerLike | None,
    arguments: Payload | None,
    *,
    error_response: ErrorResponseFn,
    set_object_member: SetObjectMemberFn,
    set_scope_variable: SetScopeVariableFn,
    logger: Logger,
    conversion_error_message: str,
    var_ref_tuple_size: int,
) -> Payload:
    """Handle setVariable command implementation."""
    arguments = arguments or {}
    variables_reference = arguments.get("variablesReference")
    name = arguments.get("name")
    value = arguments.get("value")

    if not (dbg and isinstance(variables_reference, int) and name and value is not None):
        return error_response("Invalid arguments")

    if variables_reference not in getattr(dbg.var_manager, "var_refs", {}):
        return error_response("Invalid variable reference")

    frame_info = dbg.var_manager.var_refs[variables_reference]

    try:
        if isinstance(frame_info, tuple) and len(frame_info) == var_ref_tuple_size:
            first, second = frame_info

            if first == "object":
                parent_obj = second
                return set_object_member(parent_obj, name, value)

            if isinstance(first, int) and second in ("locals", "globals"):
                frame_id: int = first
                scope: str = second
                frame = getattr(dbg.thread_tracker, "frame_id_to_frame", {}).get(frame_id)
                if frame:
                    return set_scope_variable(frame, scope, name, value)
    except (AttributeError, KeyError, TypeError, ValueError):
        logger.debug("Failed to set variable from frame reference", exc_info=True)
        return error_response(conversion_error_message)

    return error_response(f"Invalid variable reference: {variables_reference}")


def handle_set_variable_command_impl(
    dbg: CommandHandlerDebuggerLike | None,
    arguments: Payload | None,
    *,
    dependencies: SetVariableCommandDependencies,
) -> Payload:
    """Handle setVariable command with injected runtime dependencies."""
    conversion_failed_sentinel = object()

    convert_value_with_context_fn = dependencies["convert_value_with_context_fn"]
    evaluate_with_policy_fn = dependencies["evaluate_with_policy_fn"]
    set_object_member_helper = dependencies["set_object_member_helper"]
    set_scope_variable_helper = dependencies["set_scope_variable_helper"]
    assign_to_parent_member_fn = dependencies["assign_to_parent_member_fn"]
    error_response_fn = dependencies["error_response_fn"]
    conversion_error_message = dependencies["conversion_error_message"]
    get_state_debugger = dependencies["get_state_debugger"]
    make_variable_fn = dependencies["make_variable_fn"]
    logger = dependencies["logger"]
    var_ref_tuple_size = dependencies["var_ref_tuple_size"]

    def _try_convert(
        value_str: str,
        frame: object | None = None,
        parent_obj: object | None = None,
    ) -> object:
        try:
            return convert_value_with_context_fn(value_str, frame, parent_obj)
        except (AttributeError, NameError, SyntaxError, TypeError, ValueError):
            logger.debug("Context conversion fallback failed", exc_info=True)
            return conversion_failed_sentinel

    common_setter_dependencies = {
        "try_custom_convert": _try_convert,
        "conversion_failed_sentinel": conversion_failed_sentinel,
        "convert_value_with_context_fn": convert_value_with_context_fn,
        "error_response_fn": error_response_fn,
        "conversion_error_message": conversion_error_message,
        "get_state_debugger": get_state_debugger,
        "make_variable_fn": make_variable_fn,
        "logger": logger,
    }

    def _set_object_member(parent_obj: object, name: str, value_str: str) -> Payload:
        return set_object_member_helper(
            parent_obj,
            name,
            value_str,
            dependencies={
                **common_setter_dependencies,
                "assign_to_parent_member_fn": assign_to_parent_member_fn,
            },
        )

    def _set_scope_variable(
        frame: object,
        scope: str,
        name: str,
        value_str: str,
    ) -> Payload:
        return set_scope_variable_helper(
            frame,
            scope,
            name,
            value_str,
            dependencies={
                **common_setter_dependencies,
                "evaluate_with_policy_fn": evaluate_with_policy_fn,
            },
        )

    return handle_set_variable_impl(
        dbg,
        arguments,
        error_response=error_response_fn,
        set_object_member=_set_object_member,
        set_scope_variable=_set_scope_variable,
        logger=logger,
        conversion_error_message=conversion_error_message,
        var_ref_tuple_size=var_ref_tuple_size,
    )


def handle_evaluate_impl(
    dbg: CommandHandlerDebuggerLike | None,
    arguments: Payload | None,
    *,
    evaluate_with_policy: EvaluateWithPolicyFn,
    format_evaluation_error: FormatEvaluationErrorFn | None,
    safe_send_debug_message: SafeSendDebugMessageFn,
    logger: Logger,
) -> Payload:
    """Handle evaluate command implementation."""
    arguments = arguments or {}
    expression = arguments.get("expression", "")
    frame_id = arguments.get("frameId")

    result = "<error>"
    format_error_fn = format_evaluation_error or globals()["format_evaluation_error"]

    if dbg and expression:
        if not isinstance(expression, str):
            raise TypeError("expression must be a string")
        try:
            stack = getattr(dbg, "stack", None)
            if stack and frame_id is not None and frame_id < len(stack):
                frame, _ = stack[frame_id]
                try:
                    value = evaluate_with_policy(expression, frame)
                    result = repr(value)
                except Exception as e:
                    result = format_error_fn(e)
            elif hasattr(dbg, "stepping_controller") and dbg.stepping_controller.current_frame:
                try:
                    value = evaluate_with_policy(expression, dbg.stepping_controller.current_frame)
                    result = repr(value)
                except Exception as e:
                    result = format_error_fn(e)
        except (AttributeError, IndexError, KeyError, NameError, TypeError):
            logger.debug("Evaluate context resolution failed", exc_info=True)

    safe_send_debug_message(
        "evaluate",
        expression=expression,
        result=result,
        variablesReference=0,
    )

    return {
        "success": True,
        "body": {
            "result": result,
            "variablesReference": 0,
        },
    }


def handle_set_data_breakpoints_impl(
    dbg: CommandHandlerDebuggerLike | None,
    arguments: Payload | None,
    logger: Logger,
) -> Payload:
    """Handle setDataBreakpoints command implementation."""
    arguments = arguments or {}
    breakpoints = arguments.get("breakpoints", [])

    clear_all = getattr(dbg, "clear_all_data_breakpoints", None)
    if callable(clear_all):
        try:
            clear_all()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug("Failed clearing existing data breakpoints", exc_info=True)

    watch_names: list[str] = []
    watch_meta: list[tuple[str, Payload]] = []

    results: list[Payload] = []
    for bp in breakpoints:
        data_id = bp.get("dataId")
        access_type = bp.get("accessType", "readWrite")
        cond = bp.get("condition")
        hit_condition = bp.get("hitCondition")

        verified = False

        set_db = getattr(dbg, "set_data_breakpoint", None)
        if data_id and callable(set_db):
            try:
                set_db(data_id, access_type)
                verified = True
            except (AttributeError, RuntimeError, TypeError, ValueError):
                logger.debug("set_data_breakpoint failed for data_id=%r", data_id, exc_info=True)
                verified = False

        name_for_watch: str | None = None
        if isinstance(data_id, str) and data_id:
            sep = ":var:"
            idx = data_id.rfind(sep)
            name_for_watch = data_id[idx + len(sep) :] if idx != -1 else data_id

        if name_for_watch:
            if name_for_watch not in watch_names:
                watch_names.append(name_for_watch)

            meta: Payload = {
                "dataId": data_id,
                "accessType": access_type,
            }
            if cond is not None:
                meta["condition"] = cond
            if hit_condition is not None:
                meta["hitCondition"] = hit_condition

            watch_meta.append((name_for_watch, meta))

        results.append({"verified": verified})

    register = getattr(dbg, "register_data_watches", None)
    if callable(register) and watch_names:
        try:
            register(watch_names, watch_meta)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug("register_data_watches failed", exc_info=True)

    return {"success": True, "body": {"breakpoints": results}}


def handle_data_breakpoint_info_impl(
    dbg: CommandHandlerDebuggerLike | None,
    arguments: Payload | None,
    *,
    max_value_repr_len: int,
    trunc_suffix: str,
) -> Payload:
    """Handle dataBreakpointInfo command implementation."""
    arguments = arguments or {}
    name = arguments.get("name", "")
    variables_reference = arguments.get("variablesReference")

    data_id = f"{variables_reference}:{name}" if variables_reference else name

    body: Payload = {
        "dataId": data_id,
        "description": f"Data breakpoint for {name}",
        "accessTypes": ["read", "write", "readWrite"],
        "canPersist": False,
    }

    try:
        frame = getattr(dbg, "current_frame", None) or getattr(dbg, "botframe", None)

        try:
            locals_map = getattr(frame, "f_locals", None)
            if frame is not None and locals_map is not None and name in locals_map:
                val = locals_map[name]
                body["type"] = type(val).__name__
                try:
                    sval = repr(val)
                    if len(sval) > max_value_repr_len:
                        trim_at = max_value_repr_len - len(trunc_suffix)
                        sval = sval[:trim_at] + trunc_suffix
                    body["value"] = sval
                except Exception:
                    pass
        except Exception:
            pass
    except Exception:
        pass

    return {"success": True, "body": body}
