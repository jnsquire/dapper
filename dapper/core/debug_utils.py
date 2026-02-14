"""
Utility functions for the debugger.
"""

from __future__ import annotations

import re

from dapper.shared.value_conversion import evaluate_with_policy

# Safety limit for stack walking to avoid infinite loops on mocked frames
MAX_STACK_DEPTH = 128


def evaluate_hit_condition(expr: str, hit_count: int) -> bool:
    """Evaluate a hit condition expression against the current hit count.

    Supported syntax:
        - ``%n``: Match when hit count is divisible by n (e.g., ``%3`` matches hits 3, 6, 9...)
        - ``==n``: Match when hit count equals n exactly
        - ``>=n``: Match when hit count is greater than or equal to n
        - ``n``: Plain number, equivalent to ``==n``

    Args:
        expr: The hit condition expression string.
        hit_count: The current breakpoint hit count.

    Returns:
        True if the condition is satisfied (breakpoint should trigger),
        False otherwise. Returns True on parse errors (fail-open).
    """
    try:
        s = expr.strip()
        m = re.match(r"^%\s*(\d+)$", s)
        if m:
            n = int(m.group(1))
            return n > 0 and (hit_count % n == 0)
        m = re.match(r"^==\s*(\d+)$", s)
        if m:
            return hit_count == int(m.group(1))
        m = re.match(r"^>=\s*(\d+)$", s)
        if m:
            return hit_count >= int(m.group(1))
        if re.match(r"^\d+$", s):
            return hit_count == int(s)
    except Exception:
        return True
    return True


def format_log_message(template: str, frame) -> str:
    def repl(match):
        expr = match.group(1)
        try:
            val = evaluate_with_policy(expr, frame, allow_builtins=True)
            return str(val)
        except Exception:
            return "<error>"

    # Use rare codepoints as placeholders so escaped double-braces are not
    # treated as expressions by the subsequent regex. Using U+007B/U+007D
    # (which are '{' and '}') defeats the purpose — we need non-brace
    # placeholders that won't match the r"\{([^{}]+)\}" regex.
    left_placeholder = "\u0001"
    right_placeholder = "\u0002"
    s = template.replace("{{", left_placeholder).replace("}}", right_placeholder)
    s = re.sub(r"\{([^{}]+)\}", repl, s)
    # Restore the original literal braces
    return s.replace(left_placeholder, "{").replace(right_placeholder, "}")


def get_function_candidate_names(frame) -> set[str]:
    names: set[str] = set()
    code = getattr(frame, "f_code", None)
    if not code:
        return names
    func = getattr(code, "co_name", None) or ""
    mod = frame.f_globals.get("__name__", "")
    names.add(func)
    if mod:
        names.add(f"{mod}.{func}")
    self_obj = frame.f_locals.get("self") if isinstance(frame.f_locals, dict) else None
    if self_obj is not None:
        cls = getattr(self_obj, "__class__", None)
        cls_name = getattr(cls, "__name__", None)
        if cls_name:
            names.add(f"{cls_name}.{func}")
            if mod:
                names.add(f"{mod}.{cls_name}.{func}")
    return names
