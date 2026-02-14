"""Shared value/expression conversion utilities for debug command handlers."""

from __future__ import annotations

import ast
from typing import Any

_DISALLOWED_EVAL_TOKENS = (
    "__",
    "import ",
    "import(",
    "open(",
    "exec(",
    "eval(",
    "compile(",
    "globals(",
    "locals(",
    "vars(",
    "os.",
    "sys.",
    "subprocess",
    "socket",
)


def _enforce_eval_policy(expression: str) -> None:
    lowered = expression.lower()
    if any(token in lowered for token in _DISALLOWED_EVAL_TOKENS):
        msg = "expression blocked by policy"
        raise ValueError(msg)


def evaluate_with_policy(
    expression: str,
    frame: Any | None,
    *,
    allow_builtins: bool = False,
) -> Any:
    """Evaluate an expression in frame context with simple safety policy checks."""
    if not isinstance(expression, str):
        msg = "expression must be a string"
        raise TypeError(msg)

    expr = expression.strip()
    if not expr:
        msg = "expression cannot be empty"
        raise ValueError(msg)

    _enforce_eval_policy(expr)

    if frame is None or not hasattr(frame, "f_globals") or not hasattr(frame, "f_locals"):
        msg = "frame context is required"
        raise ValueError(msg)

    globals_ctx = dict(getattr(frame, "f_globals", {}) or {})
    locals_ctx = getattr(frame, "f_locals", {}) or {}
    if not allow_builtins:
        globals_ctx["__builtins__"] = {}

    return eval(expr, globals_ctx, locals_ctx)


def convert_value_with_context(
    value_str: str,
    frame: Any | None = None,
    parent_obj: Any | None = None,
) -> Any:
    """Convert a string to a Python value using literals, frame context, and type hints."""
    s = value_str.strip()
    if s.lower() == "none":
        return None
    if s.lower() in ("true", "false"):
        return s.lower() == "true"

    try:
        return ast.literal_eval(s)
    except (ValueError, SyntaxError):
        pass

    if frame is not None:
        try:
            return evaluate_with_policy(s, frame)
        except (AttributeError, NameError, SyntaxError, TypeError, ValueError):
            pass

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
        except (StopIteration, TypeError, ValueError):
            pass

    return value_str
