"""Shared helper utilities for DAP command handler modules."""

from __future__ import annotations

from typing import Any
from typing import Callable
from typing import Protocol
from typing import cast

Payload = dict[str, Any]


class ThreadingLike(Protocol):
    def get_ident(self) -> int: ...


class LoggerLike(Protocol):
    def debug(self, msg: str, *args: object, **kwargs: object) -> object: ...


class SendDebugMessageFn(Protocol):
    def __call__(self, message_type: str, **payload: Any) -> object: ...


class SafeSendDebugMessageFn(Protocol):
    def __call__(self, message_type: str, **payload: Any) -> bool: ...


class MakeVariableFn(Protocol):
    def __call__(
        self,
        dbg: object | None,
        name: str,
        value: object,
        frame: object | None,
    ) -> Payload: ...


class ErrorResponseFn(Protocol):
    def __call__(self, message: str) -> Payload: ...


class ConvertWithContextFn(Protocol):
    def __call__(
        self,
        value_str: str,
        frame: object | None = None,
        parent_obj: object | None = None,
    ) -> object: ...


class EvaluateWithPolicyFn(Protocol):
    def __call__(self, expression: str, frame: object, allow_builtins: bool = False) -> object: ...


def error_response(message: str) -> Payload:
    """Return a standardized failed handler response payload."""
    return {"success": False, "message": message}


def get_thread_ident(threading_module: ThreadingLike) -> int:
    """Return current thread id using the supplied threading-like module."""
    return threading_module.get_ident()


def set_dbg_stepping_flag(dbg: object) -> None:
    """Ensure debugger stepping flag is enabled, best-effort."""
    try:
        dbg.stepping_controller.stepping = True
    except Exception:
        pass


def build_safe_send_debug_message(
    send_message_fn: SendDebugMessageFn | Callable[[], SendDebugMessageFn],
    logger: LoggerLike,
    *,
    dynamic: bool = False,
) -> SafeSendDebugMessageFn:
    """Create a safe DAP send function that shields handler flow from transport failures."""

    def _safe_send_debug_message(message_type: str, **payload: Any) -> bool:
        try:
            sender = (
                cast("Callable[[], SendDebugMessageFn]", send_message_fn)()
                if dynamic
                else cast("SendDebugMessageFn", send_message_fn)
            )
            sender(message_type, **payload)
        except (BrokenPipeError, ConnectionError, OSError, RuntimeError, TypeError, ValueError):
            logger.debug("Failed to send debug message '%s'", message_type, exc_info=True)
            return False
        else:
            return True

    return _safe_send_debug_message


def make_variable(
    dbg: object | None,
    name: str,
    value: object,
    frame: object | None,
    *,
    fallback_make_variable: Callable[[str, object, object | None, object | None], Payload],
    simple_fn_argcount: int,
) -> Payload:
    """Create a variable object using debugger factory when available."""
    fn = getattr(dbg, "make_variable_object", None) if dbg is not None else None
    var_obj = None
    if callable(fn):
        try:
            if (
                getattr(fn, "__code__", None) is not None
                and fn.__code__.co_argcount > simple_fn_argcount
            ):
                var_obj = fn(name, value, frame)
            else:
                var_obj = fn(name, value)
        except Exception:
            var_obj = None

    if not isinstance(var_obj, dict):
        var_obj = fallback_make_variable(name, value, dbg, frame)

    return var_obj


def extract_variables_from_mapping(
    dbg: object | None,
    mapping: dict[str, object],
    frame: object | None,
    *,
    make_variable_fn: MakeVariableFn,
) -> list[Payload]:
    """Convert a mapping of names -> values to variable objects."""
    out: list[Payload] = []
    for name, val in mapping.items():
        out.append(make_variable_fn(dbg, name, val, frame))
    return out


def resolve_variables_for_reference(  # noqa: PLR0912
    dbg: object | None,
    frame_info: object,
    *,
    make_variable_fn: MakeVariableFn,
    extract_variables_from_mapping_fn: Callable[
        [object | None, dict[str, object], object], list[Payload]
    ],
    var_ref_tuple_size: int,
) -> list[Payload]:
    """Return variables for a var_refs entry."""
    vars_out: list[Payload] = []

    if isinstance(frame_info, list):
        vars_out.extend([v for v in frame_info if isinstance(v, dict)])
        return vars_out

    if not (isinstance(frame_info, tuple) and len(frame_info) == var_ref_tuple_size):
        return vars_out

    kind, payload = frame_info

    if kind == "object":
        parent_obj = payload

        if isinstance(parent_obj, dict):
            for name, val in parent_obj.items():
                vars_out.append(make_variable_fn(dbg, name, val, None))
        elif isinstance(parent_obj, list):
            for idx, val in enumerate(parent_obj):
                vars_out.append(make_variable_fn(dbg, str(idx), val, None))
        else:
            for name in dir(parent_obj):
                if name.startswith("_"):
                    continue
                try:
                    val = getattr(parent_obj, name)
                except AttributeError:
                    continue
                vars_out.append(make_variable_fn(dbg, name, val, None))
        return vars_out

    if isinstance(kind, int) and payload in ("locals", "globals"):
        frame_id = kind
        scope = payload
        frame = getattr(dbg.thread_tracker, "frame_id_to_frame", {}).get(frame_id)
        if not frame:
            return []

        mapping = frame.f_locals if scope == "locals" else frame.f_globals
        vars_out.extend(extract_variables_from_mapping_fn(dbg, mapping, frame))
        return vars_out

    return vars_out


def assign_to_parent_member(parent_obj: Any, name: str, new_value: Any) -> str | None:
    """Assign value into parent container/object; returns error string on failure."""
    err: str | None = None

    if isinstance(parent_obj, dict):
        parent_obj[name] = new_value
    elif isinstance(parent_obj, list):
        try:
            index = int(name)
        except (TypeError, ValueError):
            err = f"Invalid list index: {name}"
        else:
            if not (0 <= index < len(parent_obj)):
                err = f"List index {index} out of range"
            else:
                parent_obj[index] = new_value
    elif isinstance(parent_obj, tuple):
        err = "Cannot modify tuple - tuples are immutable"
    else:
        try:
            setattr(parent_obj, name, new_value)
        except (AttributeError, TypeError, ValueError) as e:
            err = f"Cannot set attribute '{name}' on {type(parent_obj).__name__}: {e!s}"

    return err


def set_scope_variable(  # noqa: PLR0913
    frame: object,
    scope: str,
    name: str,
    value_str: str,
    *,
    try_custom_convert: ConvertWithContextFn,
    conversion_failed_sentinel: object,
    evaluate_with_policy_fn: EvaluateWithPolicyFn,
    convert_value_with_context_fn: ConvertWithContextFn,
    logger: LoggerLike,
    error_response_fn: ErrorResponseFn,
    conversion_error_message: str,
    get_state_debugger: Callable[[], object | None],
    make_variable_fn: MakeVariableFn,
) -> Payload:
    """Set a variable in frame locals/globals scope."""
    try:
        new_value = try_custom_convert(value_str, frame, None)
        if new_value is conversion_failed_sentinel:
            new_value = evaluate_with_policy_fn(value_str, frame, allow_builtins=True)
    except (AttributeError, NameError, SyntaxError, TypeError, ValueError):
        try:
            new_value = convert_value_with_context_fn(value_str, frame)
        except (AttributeError, NameError, SyntaxError, TypeError, ValueError):
            logger.debug("Failed to convert value for scope assignment", exc_info=True)
            return error_response_fn(conversion_error_message)

    if scope == "locals":
        frame.f_locals[name] = new_value
    elif scope == "globals":
        frame.f_globals[name] = new_value
    else:
        return error_response_fn(f"Unknown scope: {scope}")

    dbg = get_state_debugger()
    var_obj = make_variable_fn(dbg, name, new_value, frame)
    return {
        "success": True,
        "body": {
            "value": var_obj["value"],
            "type": var_obj["type"],
            "variablesReference": var_obj["variablesReference"],
        },
    }


def set_object_member(  # noqa: PLR0913
    parent_obj: object,
    name: str,
    value_str: str,
    *,
    try_custom_convert: ConvertWithContextFn,
    conversion_failed_sentinel: object,
    convert_value_with_context_fn: ConvertWithContextFn,
    assign_to_parent_member_fn: Callable[[object, str, object], str | None],
    error_response_fn: ErrorResponseFn,
    conversion_error_message: str,
    get_state_debugger: Callable[[], object | None],
    make_variable_fn: MakeVariableFn,
    logger: LoggerLike,
) -> Payload:
    """Set an attribute or item of an object."""
    try:
        new_value = try_custom_convert(value_str, None, parent_obj)
        if new_value is conversion_failed_sentinel:
            new_value = convert_value_with_context_fn(value_str, None, parent_obj)
    except (AttributeError, NameError, SyntaxError, TypeError, ValueError):
        logger.debug("Failed to convert value for object member assignment", exc_info=True)
        return error_response_fn(conversion_error_message)

    err = assign_to_parent_member_fn(parent_obj, name, new_value)

    try:
        if err is not None:
            return error_response_fn(err)

        dbg = get_state_debugger()
        var_obj = make_variable_fn(dbg, name, new_value, None)
        return {
            "success": True,
            "body": {
                "value": var_obj["value"],
                "type": var_obj["type"],
                "variablesReference": var_obj["variablesReference"],
            },
        }
    except (AttributeError, KeyError, TypeError, ValueError) as e:
        return error_response_fn(f"Failed to set object member '{name}': {e!s}")


def extract_variables(
    dbg: object | None,
    variables: list[Payload],
    parent: object,
    *,
    make_variable_fn: MakeVariableFn,
) -> None:
    """Recursively extract variables from dict/list/object into output list."""

    def _create_variable_object(key: str, val: object) -> Payload:
        return make_variable_fn(dbg, key, val, None)

    if isinstance(parent, dict):
        for key, val in parent.items():
            variables.append(_create_variable_object(key, val))
        return

    if isinstance(parent, (list, tuple)):
        for i, val in enumerate(parent):
            variables.append(_create_variable_object(str(i), val))
        return

    for attr in dir(parent):
        if str(attr).startswith("_"):
            continue
        try:
            val = getattr(parent, attr)
            variables.append(_create_variable_object(attr, val))
        except Exception:
            continue
