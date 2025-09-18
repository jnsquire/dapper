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
from typing import Any

from dapper.debug_launcher import DebuggerBDB

# Length of (frame_id, scope) tuple used in var_refs
SCOPE_TUPLE_LEN = 2

logger = logging.getLogger(__name__)


class InProcessDebugger:
    """Lightweight wrapper around DebuggerBDB with explicit APIs.

    Event callbacks (callable attributes) can be set by the adapter to
    forward DAP events without going through JSON/stdio.
    """

    def __init__(self) -> None:
        self.debugger = DebuggerBDB()
        self.command_lock = threading.RLock()

        # Optional event callbacks (set by adapter)
        self.on_stopped = None  # (data: dict) -> None
        self.on_thread = None  # (data: dict) -> None
        self.on_exited = None  # (data: dict) -> None
        self.on_output = None  # (category: str, output: str) -> None

        # Internal caches similar to debug_launcher
        self.frames_by_thread: dict[int, list[dict[str, Any]]] = {}
        self.var_refs: dict[int, Any] = {}
        self.frame_id_to_frame: dict[int, Any] = {}

    # ---- Commands mirrored from the launcher ----

    def set_breakpoints(
        self, path: str, breakpoints: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
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
        return [{"verified": True, "line": bp.get("line")} for bp in breakpoints]

    def set_function_breakpoints(self, breakpoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
        return [{"verified": True} for _ in breakpoints]

    def set_exception_breakpoints(self, filters: list[str]) -> list[dict[str, Any]]:
        with self.command_lock:
            # Set boolean flags if present, fallback to dict otherwise
            try:
                self.debugger.exception_breakpoints_raised = "raised" in filters
                self.debugger.exception_breakpoints_uncaught = "uncaught" in filters
            except Exception:
                # If underlying debugger doesn't expose boolean attrs, ignore
                pass
        return [{"verified": True} for _ in filters]

    def continue_(self, thread_id: int) -> dict[str, Any]:
        with self.command_lock:
            dbg = self.debugger
            if thread_id in dbg.stopped_thread_ids:
                try:
                    dbg.stopped_thread_ids.remove(thread_id)
                except Exception:
                    pass
            if not dbg.stopped_thread_ids:
                dbg.set_continue()
        return {"allThreadsContinued": True}

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

    def stack_trace(self, thread_id: int, start_frame: int = 0, levels: int = 0) -> dict[str, Any]:
        dbg = self.debugger
        if thread_id not in getattr(dbg, "frames_by_thread", {}):
            return {"stackFrames": [], "totalFrames": 0}

        frames = dbg.frames_by_thread[thread_id]
        total_frames = len(frames)
        if levels > 0:
            end_frame = min(start_frame + levels, total_frames)
            frames_to_send = frames[start_frame:end_frame]
        else:
            frames_to_send = frames[start_frame:]
        return {
            "stackFrames": frames_to_send,
            "totalFrames": total_frames,
        }

    def variables(
        self,
        variables_reference: int,
        *,
        _filter: str | None = None,  # unused
        _start: int | None = None,  # unused
        _count: int | None = None,  # unused
    ) -> dict[str, Any]:
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
            return {"variables": variables}
        return {"variables": []}

    def set_variable(self, variables_reference: int, name: str, value: str) -> dict[str, Any]:
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

    def evaluate(self, expression: str, frame_id: int, _context: str = "hover") -> dict[str, Any]:
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

    @staticmethod
    def _make_var(name: str, value: Any) -> dict[str, Any]:
        try:
            vtype = type(value).__name__
            return {
                "name": name,
                "value": repr(value),
                "type": vtype,
                "variablesReference": 0,
            }
        except Exception:  # pragma: no cover - defensive
            return {
                "name": name,
                "value": "<error>",
                "type": "unknown",
                "variablesReference": 0,
            }
