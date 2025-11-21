"""
Compatibility shim: re-export the shared/launcher_handlers implementation.
"""

import ast as _ast
import threading

import dapper.shared.launcher_handlers as _shared
from dapper.core.debug_utils import evaluate_hit_condition as _evaluate_hit_condition_impl
from dapper.core.debug_utils import format_log_message as _format_log_message_impl
from dapper.launcher.comm import send_debug_message

# Compatibility helpers: expose a small set of names that tests (and other
# modules) patch on the handlers module. We also bind these into the
# shared handler module so patches (e.g. patching `dapper.launcher.handlers.threading`)
# are visible to the implementation in `dapper.shared.launcher_handlers`.
from dapper.shared import debug_shared as _d_shared
from dapper.shared.launcher_handlers import *  # noqa: F403

# Ensure the shared implementation uses the same objects to allow tests to
# patch the symbols on the handlers module and have the patched value used
# by the shared implementation.
_shared.threading = threading
_shared._d_shared = _d_shared  # noqa: SLF001 - compatibility shim, tests patch this symbol
_shared._convert_string_to_value = None  # assigned below when helper is defined  # noqa: SLF001
_shared._evaluate_hit_condition = _evaluate_hit_condition_impl  # noqa: SLF001
def _shared_send_proxy(event_type: str, **kwargs):
    # Delegate to the handlers module-level send_debug_message so tests that
    # patch `dapper.launcher.handlers.send_debug_message` are honored.
    import importlib  # noqa: PLC0415

    try:
        mod = importlib.import_module("dapper.launcher.handlers")
        fn = getattr(mod, "send_debug_message", None)
        if callable(fn):
            return fn(event_type, **kwargs)
    except Exception:
        pass

    # Fall back to the original comm function
    return send_debug_message(event_type, **kwargs)


_shared.send_debug_message = _shared_send_proxy


def _convert_value_with_context(value_str: str, frame=None, parent_obj=None):
    """Convert string to a Python value with optional frame/parent context.

    This is a compatibility shim copied from the original handlers. It first
    tries literal evaluation, then expression evaluation in the provided frame,
    then falls back to simple type inference from the parent object.
    """
    # use top-level import

    s = value_str.strip()
    if s.lower() == "none":
        return None
    if s.lower() in ("true", "false"):
        return s.lower() == "true"

    # Try literal eval
    try:
        return _ast.literal_eval(s)
    except (ValueError, SyntaxError):
        pass

    # Evaluate in frame context if provided
    if frame is not None:
        try:
            return eval(s, frame.f_globals, frame.f_locals)
        except Exception:
            pass

    # Try simple type inference from parent
    if parent_obj is not None:
        try:
            target_type = None
            if isinstance(parent_obj, list) and parent_obj:
                target_type = type(parent_obj[0])
            elif isinstance(parent_obj, dict) and parent_obj:
                sample = next(iter(parent_obj.values()))
                target_type = type(sample)

            if target_type in (int, float, bool, str):
                return target_type(s)
        except Exception:
            pass

    return value_str


def _convert_string_to_value(value_str: str):
    """Legacy alias kept for backward compatibility."""
    return _convert_value_with_context(value_str)


def _evaluate_hit_condition(expr: str, hit_count: int) -> bool:
    """Compatibility wrapper around core evaluator."""
    return _evaluate_hit_condition_impl(expr, hit_count)


# Make shared module functions point to these helpers so tests patching
# `dapper.launcher.handlers` get seen by the implementation in
# `dapper.shared.launcher_handlers`.
try:
    _shared._convert_string_to_value = _convert_string_to_value  # noqa: SLF001
    _shared._d_shared = _d_shared  # noqa: SLF001
    # Re-export internal compatibility helpers used by tests
    def _format_log_message(template: str, frame):
        return _format_log_message_impl(template, frame)

    # Some internal helpers still live in the shared module and start with an underscore.
    # Tests import these directly from dapper.launcher.handlers; to remain compatible we
    # expose them here as aliases.
    try:
        from dapper.shared.launcher_handlers import (
            _set_object_member,  # type: ignore[attr-defined]
        )
    except Exception:
        _set_object_member = None
    try:
        from dapper.shared.launcher_handlers import (
            _set_scope_variable,  # type: ignore[attr-defined]
        )
    except Exception:
        _set_scope_variable = None
except Exception:
    pass

__all__ = [
    name
    for name in dir()
    if not name.startswith("_") and name not in ("__all__",)
]
