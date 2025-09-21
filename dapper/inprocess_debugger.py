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

from dapper.debug_shared import make_variable_object
from dapper.debugger_bdb import DebuggerBDB
from dapper.events import EventEmitter

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dapper.protocol_types import Breakpoint
    from dapper.protocol_types import ContinueResponseBody
    from dapper.protocol_types import EvaluateResponseBody
    from dapper.protocol_types import FunctionBreakpoint
    from dapper.protocol_types import SetVariableResponseBody
    from dapper.protocol_types import StackTraceResponseBody
    from dapper.protocol_types import VariablesResponseBody

# Length of (frame_id, scope) tuple used in var_refs
SCOPE_TUPLE_LEN = 2

logger = logging.getLogger(__name__)

# Threshold for considering a string 'raw' (long/multiline)
STRING_RAW_THRESHOLD = 80


class InProcessDebugger:
    """Lightweight wrapper around DebuggerBDB with explicit APIs.

    Event callbacks (callable attributes) can be set by the adapter to
    forward DAP events without going through JSON/stdio.
    """

    def __init__(self) -> None:
        self.debugger = DebuggerBDB()
        self.command_lock = threading.RLock()

        # Optional event callbacks (set by adapter).

        self.on_stopped = EventEmitter()
        self.on_thread = EventEmitter()
        self.on_exited = EventEmitter()
        self.on_output = EventEmitter()

    def set_breakpoints(
        self, path: str, breakpoints: list[dict[str, Any]]
    ) -> list[Breakpoint]:
        """Set line breakpoints for a file."""
        with self.command_lock:
            # Clear existing breakpoints for this file
            try:
                # Some implementations support clearing by filename only
                self.debugger.clear_break(path)  # type: ignore[call-arg]
            except Exception:
                pass
            for bp in breakpoints:
                line = bp.get("line")
                cond = bp.get("condition")
                if line:
                    self.debugger.set_break(path, line, cond=cond)
            # Return the minimal Breakpoint shape expected by the adapter/client
            return cast("list[Breakpoint]", [{"verified": True, "line": bp.get("line")} for bp in breakpoints])

    def set_function_breakpoints(self, breakpoints: list[FunctionBreakpoint]) -> Sequence[FunctionBreakpoint]:
        with self.command_lock:
            try:
                for bpn in self.debugger.function_breakpoints:
                    self.debugger.clear_bpbynumber(bpn)
            except Exception:
                pass
            self.debugger.function_breakpoints = []
            for bp in breakpoints:
                name = bp.get("name")
                if name:
                    self.debugger.function_breakpoints.append(name)
            return cast("list[FunctionBreakpoint]", [{"verified": True} for _ in breakpoints])

    def set_exception_breakpoints(self, filters: list[str]) -> list[Breakpoint]:
        with self.command_lock:
            # Set boolean flags if present, fallback to dict otherwise
            try:
                self.debugger.exception_breakpoints_raised = "raised" in filters
                self.debugger.exception_breakpoints_uncaught = "uncaught" in filters
            except Exception:
                # If underlying debugger doesn't expose boolean attrs, ignore
                pass
            return cast("list[Breakpoint]", [{"verified": True} for _ in filters])

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

    def stack_trace(self, thread_id: int, start_frame: int = 0, levels: int = 0) -> StackTraceResponseBody:
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
        return cast("StackTraceResponseBody", {
            "stackFrames": frames_to_send,
            "totalFrames": total_frames,
        })

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
            variables: list[dict[str, Any]] = []
            if frame and scope == "locals":
                for name, value in frame.f_locals.items():
                    variables.append(self._make_var(name, value))
            elif frame and scope == "globals":
                for name, value in frame.f_globals.items():
                    variables.append(self._make_var(name, value))
            # The `make_variable_object` helper returns Variable-shaped dicts
            return cast("VariablesResponseBody", {"variables": variables})
        return cast("VariablesResponseBody", {"variables": []})

    def set_variable(self, variables_reference: int, name: str, value: str) -> SetVariableResponseBody | dict[str, Any]:
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

    # ---- Helpers ----

    def _make_var(self, name: str, value: Any) -> dict[str, Any]:
        """Delegates to shared `make_variable_object` to build variable dicts.

        Passes the in-process debugger so the helper can allocate var refs.
        """
        dbg = getattr(self, "debugger", None)
        return make_variable_object(name, value, dbg)
