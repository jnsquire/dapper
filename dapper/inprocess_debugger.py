"""
In-process debugger bridge (no stdio).

This module exposes a simple object-oriented wrapper over DebuggerBDB that
mirrors the command handlers from `debug_launcher.py` without using stdin/
stdout. It is intended to be called by `PyDebugger` directly when running in
"in-process" mode (debugee is main, adapter is background thread).
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from dapper.debugger_bdb import DebuggerBDB
from dapper.events import EventEmitter

if TYPE_CHECKING:
    from collections.abc import Sequence

    # TypedDict for variable-shaped dicts
    from dapper.debugger_protocol import Variable
    from dapper.protocol_types import Breakpoint
    from dapper.protocol_types import ContinueResponseBody
    from dapper.protocol_types import EvaluateResponseBody
    from dapper.protocol_types import SetVariableResponseBody
    from dapper.protocol_types import SourceBreakpoint
    from dapper.protocol_types import StackTraceResponseBody
    from dapper.protocol_types import VariablesResponseBody

# Length of (frame_id, scope) tuple used in var_refs
SCOPE_TUPLE_LEN = 2

logger = logging.getLogger(__name__)

# Threshold for considering a string 'raw' (long/multiline)
STRING_RAW_THRESHOLD = 80


class InProcessDebugger:
    """Lightweight wrapper around DebuggerBDB with explicit APIs.
    Provides EventEmitter attributes for adapter/server callbacks used in
    in-process mode so events can be forwarded without JSON/stdio. Register
    listeners with the EventEmitter (e.g. `on_stopped.add_listener(...)`).

    Expected listener signatures:
        - on_stopped(data: dict) -> None
        - on_thread(data: dict) -> None
        - on_exited(data: dict) -> None
        - on_output(category: str, output: str) -> None
    """

    def __init__(self) -> None:
        self.debugger: DebuggerBDB = DebuggerBDB()
        self.command_lock = threading.RLock()

        # Optional event callbacks (set by adapter).

        self.on_stopped = EventEmitter()
        self.on_thread = EventEmitter()
        self.on_exited = EventEmitter()
        self.on_output = EventEmitter()

    def set_breakpoints(self, path: str, breakpoints: list[SourceBreakpoint]) -> list[Breakpoint]:
        """Set line breakpoints for a file."""
        with self.command_lock:
            # Clear existing breakpoints for this file (helper on DebuggerBDB)
            try:
                self.debugger.clear_breaks_for_file(path)  # type: ignore[attr-defined]
            except Exception:
                pass
            results: list[Breakpoint] = []
            for bp in breakpoints:
                line = bp.get("line")
                cond = bp.get("condition")
                verified = True
                if line:
                    try:
                        # Some debugger implementations may return a boolean to
                        # indicate whether installing the breakpoint succeeded.
                        res = self.debugger.set_break(path, line, cond=cond)
                    except Exception:
                        verified = False
                    else:
                        # If the debugger explicitly returns False, treat the
                        # installation as unsuccessful. Treat True/None/other
                        # values as success for backward compatibility.
                        verified = res is not False
                results.append({"verified": verified, "line": line})
            return results

    def set_function_breakpoints(
        self, breakpoints: list[SourceBreakpoint]
    ) -> Sequence[SourceBreakpoint]:
        """Replace function breakpoints and record per-breakpoint metadata.

        Mirrors the behavior in debug_launcher: clears existing function
        breakpoints and associated metadata, then installs new ones while
        persisting condition/hitCondition/logMessage for runtime use.
        """
        with self.command_lock:
            # Clear any existing function breakpoints and metadata
            self.debugger.clear_all_function_breakpoints()

            # Install new function breakpoints and capture metadata
            for bp in breakpoints:
                name = bp.get("name")
                if not name:
                    continue
                condition = bp.get("condition")
                hit_condition = bp.get("hitCondition")
                log_message = bp.get("logMessage")

                try:
                    self.debugger.function_breakpoints.append(name)
                except Exception:
                    # If attribute missing or wrong type, try to set fresh list
                    try:
                        self.debugger.function_breakpoints = [name]  # type: ignore[attr-defined]
                    except Exception:
                        pass

                # The debugger is expected to expose a dict for
                # function_breakpoint_meta; update it directly.
                fbm = self.debugger.function_breakpoint_meta
                meta = fbm.get(name, {})
                meta.setdefault("hit", 0)
                meta["condition"] = condition
                meta["hitCondition"] = hit_condition
                meta["logMessage"] = log_message
                fbm[name] = meta

            return cast("list[SourceBreakpoint]", [{"verified": True} for _ in breakpoints])

    def set_exception_breakpoints(self, filters: list[str]) -> list[SourceBreakpoint]:
        with self.command_lock:
            # Set boolean flags if present, fallback to dict otherwise
            try:
                self.debugger.exception_breakpoints_raised = "raised" in filters
                self.debugger.exception_breakpoints_uncaught = "uncaught" in filters
            except Exception:
                # If underlying debugger doesn't expose boolean attrs, ignore
                pass
            return cast("list[SourceBreakpoint]", [{"verified": True} for _ in filters])

    def continue_(self, thread_id: int) -> ContinueResponseBody:
        with self.command_lock:
            dbg = self.debugger
            if thread_id in dbg.stopped_thread_ids:
                try:
                    dbg.stopped_thread_ids.remove(thread_id)
                except Exception:
                    pass
            if not dbg.stopped_thread_ids:
                dbg.set_continue()
            return cast("ContinueResponseBody", {"allThreadsContinued": True})

    def next_(self, thread_id: int) -> None:
        with self.command_lock:
            dbg = self.debugger
            if thread_id == threading.get_ident():
                dbg.stepping = True
                if dbg.current_frame is not None:
                    dbg.set_next(dbg.current_frame)

    def step_in(self, thread_id: int) -> None:
        with self.command_lock:
            dbg = self.debugger
            if thread_id == threading.get_ident():
                dbg.stepping = True
                dbg.set_step()

    def step_out(self, thread_id: int) -> None:
        with self.command_lock:
            dbg = self.debugger
            if thread_id == threading.get_ident():
                dbg.stepping = True
                if dbg.current_frame is not None:
                    dbg.set_return(dbg.current_frame)

    # Variables/Stack/Evaluate
    # These follow the launcher semantics, but return dicts directly.

    def stack_trace(
        self, thread_id: int, start_frame: int = 0, levels: int = 0
    ) -> StackTraceResponseBody:
        dbg = self.debugger
        if thread_id not in getattr(dbg, "frames_by_thread", {}):
            return cast("StackTraceResponseBody", {"stackFrames": [], "totalFrames": 0})

        frames = dbg.frames_by_thread[thread_id]
        total_frames = len(frames)
        if levels > 0:
            end_frame = min(start_frame + levels, total_frames)
            frames_to_send = frames[start_frame:end_frame]
        else:
            frames_to_send = frames[start_frame:]
        return cast(
            "StackTraceResponseBody",
            {
                "stackFrames": frames_to_send,
                "totalFrames": total_frames,
            },
        )

    def variables(
        self,
        variables_reference: int,
        *,
        _filter: str | None = None,  # unused
        _start: int | None = None,  # unused
        _count: int | None = None,  # unused
    ) -> VariablesResponseBody:
        dbg = self.debugger
        var_ref = variables_reference
        if var_ref not in dbg.var_refs:
            return {"variables": []}

        frame_info = dbg.var_refs[var_ref]
        # scope ref is a tuple of (frame_id, scope)
        if isinstance(frame_info, tuple) and len(frame_info) == (SCOPE_TUPLE_LEN):
            frame_id, scope = frame_info
            frame = dbg.frame_id_to_frame.get(frame_id)
            variables: list[Variable] = []
            if frame and scope == "locals":
                for name, value in frame.f_locals.items():
                    variables.append(dbg.make_variable_object(name, value))
            elif frame and scope == "globals":
                for name, value in frame.f_globals.items():
                    variables.append(dbg.make_variable_object(name, value))
            # The `make_variable_object` helper returns Variable-shaped dicts
            return cast("VariablesResponseBody", {"variables": variables})
        return cast("VariablesResponseBody", {"variables": []})

    def set_variable(
        self, variables_reference: int, name: str, value: str
    ) -> SetVariableResponseBody | dict[str, Any]:
        dbg = self.debugger
        var_ref = variables_reference
        if var_ref not in dbg.var_refs:
            return {
                "success": False,
                "message": f"Invalid variable reference: {var_ref}",
            }

        frame_info = dbg.var_refs[var_ref]
        if isinstance(frame_info, tuple) and len(frame_info) == (SCOPE_TUPLE_LEN):
            frame_id, scope = frame_info
            frame = dbg.frame_id_to_frame.get(frame_id)
            if not frame:
                return {"success": False, "message": "Frame not found"}
            try:
                # naive eval into the target scope (mirrors launcher)
                target = frame.f_locals if scope == "locals" else frame.f_globals
                target[name] = eval(value, frame.f_globals, frame.f_locals)
                return {
                    "value": target[name],
                    "type": type(target[name]).__name__,
                    "variablesReference": 0,
                }
            except Exception as exc:  # pragma: no cover - defensive
                return {"success": False, "message": str(exc)}
        return {"success": False, "message": "Invalid reference"}

    def evaluate(
        self, expression: str, frame_id: int, _context: str = "hover"
    ) -> EvaluateResponseBody:
        dbg = self.debugger
        frame = dbg.frame_id_to_frame.get(frame_id)
        if not frame:
            return {
                "result": f"<evaluation of '{expression}' not available>",
                "type": "string",
                "variablesReference": 0,
            }
        try:
            result = eval(expression, frame.f_globals, frame.f_locals)
            return {
                "result": repr(result),
                "type": type(result).__name__,
                "variablesReference": 0,
            }
        except Exception as exc:  # pragma: no cover - defensive
            return {
                "result": str(exc),
                "type": "error",
                "variablesReference": 0,
            }
