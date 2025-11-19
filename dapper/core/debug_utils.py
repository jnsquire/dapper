"""
Utility functions for the debugger.
"""

from __future__ import annotations

import re

# Safety limit for stack walking to avoid infinite loops on mocked frames
MAX_STACK_DEPTH = 128


def evaluate_hit_condition(expr: str, hit_count: int) -> bool:
    # TODO Document the supported syntax
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
            val = eval(expr, frame.f_globals, frame.f_locals)
            return str(val)
        except Exception:
            return "<error>"

    s = template.replace("{{", "\u007b").replace("}}", "\u007d")
    s = re.sub(r"\{([^{}]+)\}", repl, s)
    return s.replace("\u007b", "{").replace("\u007d", "}")


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
