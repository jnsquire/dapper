"""Breakpoint-related DAP handler implementations extracted from command_handlers."""

from __future__ import annotations

import dis
import linecache
import logging
from typing import TYPE_CHECKING
from typing import Any
from typing import NamedTuple

if TYPE_CHECKING:
    from dapper.shared.command_handler_helpers import Payload
    from dapper.shared.debug_shared import DebugSession

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class _BpMeta(NamedTuple):
    """Common breakpoint metadata extracted from a DAP breakpoint descriptor."""

    condition: str | None
    hit_condition: str | None
    log_message: str | None


def _extract_bp_metadata(bp: dict[str, Any]) -> _BpMeta:
    """Pull condition / hitCondition / logMessage from a DAP breakpoint dict."""
    return _BpMeta(
        condition=bp.get("condition"),
        hit_condition=bp.get("hitCondition"),
        log_message=bp.get("logMessage"),
    )


def _clear_file_breakpoints(dbg: Any, path: str) -> None:
    """Clear all breakpoints and associated metadata for *path*."""
    dbg.clear_breaks_for_file(path)
    dbg.clear_break_meta_for_file(path)


def _register_function_breakpoint(dbg: Any, name: str, meta: _BpMeta) -> None:
    """Append *name* to the debugger's function-breakpoint list and store metadata."""
    dbg.bp_manager.function_names.append(name)
    fbm = getattr(dbg.bp_manager, "function_meta", None)
    if isinstance(fbm, dict):
        entry = fbm.get(name, {})
        entry.setdefault("hit", 0)
        entry["condition"] = meta.condition
        entry["hitCondition"] = meta.hit_condition
        entry["logMessage"] = meta.log_message
        fbm[name] = entry


# ---------------------------------------------------------------------------
# Public handler implementations
# ---------------------------------------------------------------------------


def handle_set_breakpoints_impl(
    session: DebugSession,
    arguments: Payload | None,
) -> Payload | None:
    """Handle setBreakpoints command implementation."""
    arguments = arguments or {}
    source = arguments.get("source", {})
    bps = arguments.get("breakpoints", [])
    path = source.get("path")

    dbg = session.debugger
    if not (path and dbg):
        return None

    _clear_file_breakpoints(dbg, path)

    verified_bps: list[Payload] = []
    for bp in bps:
        line = bp.get("line")
        if not line:
            continue

        meta = _extract_bp_metadata(bp)
        verified = _try_set_break(dbg, path, line, meta.condition)
        dbg.record_breakpoint(
            path,
            int(line),
            condition=meta.condition,
            hit_condition=meta.hit_condition,
            log_message=meta.log_message,
        )
        verified_bps.append({"verified": verified, "line": line})

    session.safe_send("breakpoints", source=source, breakpoints=verified_bps)
    return {"success": True, "body": {"breakpoints": verified_bps}}


def _try_set_break(
    dbg: Any,
    path: str,
    line: int,
    condition: str | None,
) -> bool:
    """Attempt to set a breakpoint; return whether it was verified."""
    try:
        res = dbg.set_break(path, line, cond=condition)
    except Exception:
        return False
    return res is not False


def handle_set_function_breakpoints_impl(
    session: DebugSession,
    arguments: Payload | None,
) -> Payload | None:
    """Handle setFunctionBreakpoints command implementation."""
    arguments = arguments or {}
    bps = arguments.get("breakpoints", [])

    dbg = session.debugger
    if not dbg:
        return None

    dbg.clear_all_function_breakpoints()

    registered_names: set[str] = set()
    for bp in bps:
        name = bp.get("name")
        if not name:
            continue
        _register_function_breakpoint(dbg, name, _extract_bp_metadata(bp))
        registered_names.add(name)

    results: list[Payload] = [
        {"verified": bool(bp.get("name") and bp.get("name") in registered_names)} for bp in bps
    ]
    return {"success": True, "body": {"breakpoints": results}}


def handle_set_exception_breakpoints_impl(
    session: DebugSession,
    arguments: Payload | None,
) -> Payload | None:
    """Handle setExceptionBreakpoints command implementation."""
    arguments = arguments or {}
    raw_filters = arguments.get("filters", [])

    filters: list[str] = (
        [str(f) for f in raw_filters] if isinstance(raw_filters, (list, tuple)) else []
    )

    # Extract per-filter conditions from filterOptions (DAP 1.51+)
    filter_options: list[dict[str, Any]] = arguments.get("filterOptions", [])
    condition_map: dict[str, str | None] = {}
    for opt in filter_options:
        fid = opt.get("filterId", "")
        cond = opt.get("condition") or None
        condition_map[fid] = cond
        # filterOptions also activates the filter (even if not in "filters")
        if fid and fid not in filters:
            filters.append(fid)

    dbg = session.debugger
    if not dbg:
        return None

    verified_all: bool = True
    try:
        dbg.exception_handler.config.break_on_raised = "raised" in filters
        dbg.exception_handler.config.break_on_uncaught = "uncaught" in filters
        dbg.exception_handler.config.raised_condition = condition_map.get("raised")
        dbg.exception_handler.config.uncaught_condition = condition_map.get("uncaught")
    except (AttributeError, TypeError, ValueError):
        verified_all = False

    body = {"breakpoints": [{"verified": verified_all} for _ in filters]}
    return {"success": True, "body": body}


def handle_breakpoint_locations_impl(
    arguments: dict[str, Any] | None,
) -> dict[str, Any]:
    """Handle breakpointLocations request.

    Returns valid breakable lines within the given source range using
    Python's code-object line number table.
    """

    arguments = arguments or {}
    source = arguments.get("source", {})
    path = source.get("path", "")
    start_line = arguments.get("line", 1)
    end_line = arguments.get("endLine", start_line)

    locations: list[dict[str, int]] = []

    if not path:
        return {"success": True, "body": {"breakpoints": locations}}

    try:
        # Read and compile the source to get the line-number table
        source_text = linecache.getlines(path)
        if not source_text:
            # File not in cache — try reading directly
            with open(path, encoding="utf-8") as f:  # noqa: PTH123
                source_text = f.readlines()
        code = compile("".join(source_text), path, "exec")
        # Collect all lines that have associated bytecode
        valid_lines: set[int] = set()
        _collect_code_lines(code, valid_lines, dis)

        locations = [
            {"line": line_no}
            for line_no in sorted(valid_lines)
            if start_line <= line_no <= end_line
        ]
    except Exception:
        # Fallback: return every line in the range (best-effort)
        locations = [{"line": ln} for ln in range(start_line, end_line + 1)]

    return {"success": True, "body": {"breakpoints": locations}}


def _collect_code_lines(
    code: Any,
    out: set[int],
    dis_module: Any,
) -> None:
    """Recursively collect lines from a code object and its nested code objects."""
    for _offset, line in dis_module.findlinestarts(code):
        if line is not None:
            out.add(line)
    for const in code.co_consts:
        if hasattr(const, "co_code"):
            _collect_code_lines(const, out, dis_module)
