"""Breakpoint-related DAP handler implementations extracted from command_handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import Protocol

if TYPE_CHECKING:
    from dapper.protocol.debugger_protocol import DebuggerLike

Payload = dict[str, Any]


class SafeSendDebugMessageFn(Protocol):
    def __call__(self, message_type: str, **payload: Any) -> bool: ...


class LoggerLike(Protocol):
    def debug(self, msg: str, *args: object, **kwargs: object) -> object: ...


def handle_set_breakpoints_impl(
    dbg: DebuggerLike | None,
    arguments: Payload | None,
    safe_send_debug_message: SafeSendDebugMessageFn,
    logger: LoggerLike,
) -> Payload | None:
    """Handle setBreakpoints command implementation."""
    arguments = arguments or {}
    source = arguments.get("source", {})
    bps = arguments.get("breakpoints", [])
    path = source.get("path")

    if path and dbg:
        try:
            dbg.clear_breaks_for_file(path)
        except (AttributeError, TypeError, ValueError):
            try:
                dbg.clear_break(path)
            except (AttributeError, TypeError, ValueError):
                try:
                    dbg.clear_break_meta_for_file(path)
                except (AttributeError, TypeError, ValueError):
                    logger.debug(
                        "Failed to clear existing breakpoints for %s", path, exc_info=True
                    )

        verified_bps: list[Payload] = []
        for bp in bps:
            line = bp.get("line")
            condition = bp.get("condition")
            hit_condition = bp.get("hitCondition")
            log_message = bp.get("logMessage")

            verified = True
            if line:
                try:
                    res = dbg.set_break(path, line, cond=condition)
                except Exception:
                    verified = False
                else:
                    verified = res is not False

                try:
                    dbg.record_breakpoint(
                        path,
                        int(line),
                        condition=condition,
                        hit_condition=hit_condition,
                        log_message=log_message,
                    )
                except (AttributeError, TypeError, ValueError):
                    logger.debug(
                        "Failed to record breakpoint metadata for %s:%s",
                        path,
                        line,
                        exc_info=True,
                    )

                verified_bps.append({"verified": verified, "line": line})

        safe_send_debug_message("breakpoints", source=source, breakpoints=verified_bps)
        return {"success": True, "body": {"breakpoints": verified_bps}}

    return None


def handle_set_function_breakpoints_impl(
    dbg: DebuggerLike | None,
    arguments: Payload | None,
) -> Payload | None:
    """Handle setFunctionBreakpoints command implementation."""
    arguments = arguments or {}
    bps = arguments.get("breakpoints", [])

    if dbg:
        dbg.clear_all_function_breakpoints()

        for bp in bps:
            name = bp.get("name")
            if not name:
                continue

            condition = bp.get("condition")
            hit_condition = bp.get("hitCondition")
            log_message = bp.get("logMessage")

            dbg.bp_manager.function_names.append(name)
            try:
                fbm = dbg.bp_manager.function_meta
            except AttributeError:
                fbm = None
            if isinstance(fbm, dict):
                mb = fbm.get(name, {})
                mb.setdefault("hit", 0)
                mb["condition"] = condition
                mb["hitCondition"] = hit_condition
                mb["logMessage"] = log_message
                fbm[name] = mb

        results: list[Payload] = []
        fb_list = getattr(dbg.bp_manager, "function_names", [])
        for bp in bps:
            name = bp.get("name")
            verified = False
            if name and isinstance(fb_list, list):
                try:
                    verified = name in fb_list
                except (TypeError, ValueError):
                    verified = False
            results.append({"verified": verified})

        return {"success": True, "body": {"breakpoints": results}}

    return None


def handle_set_exception_breakpoints_impl(
    dbg: DebuggerLike | None,
    arguments: Payload | None,
) -> Payload | None:
    """Handle setExceptionBreakpoints command implementation."""
    arguments = arguments or {}
    raw_filters = arguments.get("filters", [])

    if isinstance(raw_filters, (list, tuple)):
        filters: list[str] = [str(f) for f in raw_filters]
    else:
        filters = []

    if not dbg:
        return None

    verified_all: bool = True
    try:
        dbg.exception_handler.config.break_on_raised = "raised" in filters
        dbg.exception_handler.config.break_on_uncaught = "uncaught" in filters
    except (AttributeError, TypeError, ValueError):
        verified_all = False

    body = {"breakpoints": [{"verified": verified_all} for _ in filters]}
    response: Payload = {"success": True, "body": body}
    return response
