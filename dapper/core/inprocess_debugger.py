"""In-process debugger bridge (no stdio).

This module exposes a simple object-oriented wrapper over DebuggerBDB that
mirrors the command handlers from `debug_launcher.py` without using stdin/
stdout. It is intended to be called by `PyDebugger` directly when running in
"in-process" mode (debugee is main, adapter is background thread).
"""

from __future__ import annotations

import builtins
import inspect
import logging
import threading
import types
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from dapper.core.debugger_bdb import DebuggerBDB
from dapper.core.stepping_controller import StepGranularity
from dapper.ipc.ipc_receiver import process_queued_commands
from dapper.shared.value_conversion import evaluate_with_policy
from dapper.utils.events import EventEmitter

if TYPE_CHECKING:
    from collections.abc import Mapping
    from collections.abc import Sequence

    from dapper.adapter.types import CompletionItem
    from dapper.adapter.types import CompletionsResponseBody

    # TypedDict for variable-shaped dicts
    from dapper.protocol.debugger_protocol import Variable
    from dapper.protocol.requests import CompletionItemKind
    from dapper.protocol.requests import ContinueResponseBody
    from dapper.protocol.requests import EvaluateResponseBody
    from dapper.protocol.requests import FunctionBreakpoint
    from dapper.protocol.requests import SetVariableResponseBody
    from dapper.protocol.requests import StackTraceResponseBody
    from dapper.protocol.requests import VariablesResponseBody
    from dapper.protocol.structures import Breakpoint
    from dapper.protocol.structures import SourceBreakpoint

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

    def __init__(
        self,
        *,
        just_my_code: bool = True,
        strict_expression_watch_policy: bool = False,
    ) -> None:
        # Optional event callbacks (set by adapter).
        self.on_stopped = EventEmitter()
        self.on_thread = EventEmitter()
        self.on_exited = EventEmitter()
        self.on_output = EventEmitter()

        self.debugger: DebuggerBDB = DebuggerBDB(
            send_message=self._handle_debug_message,
            process_commands=process_queued_commands,
            just_my_code=just_my_code,
            strict_expression_watch_policy=strict_expression_watch_policy,
        )
        self.command_lock = threading.RLock()

    def _handle_debug_message(self, event_type: str, **kwargs: Any) -> None:
        """Route debug messages to the appropriate EventEmitter."""
        if event_type == "stopped":
            self.on_stopped.emit(kwargs)
        elif event_type == "thread":
            self.on_thread.emit(kwargs)
        elif event_type == "exited":
            self.on_exited.emit(kwargs)
        elif event_type == "output":
            self.on_output.emit(kwargs.get("category"), kwargs.get("output"))

    def set_breakpoints(self, path: str, breakpoints: list[SourceBreakpoint]) -> list[Breakpoint]:
        """Set line breakpoints for a file."""
        with self.command_lock:
            # Clear existing breakpoints for this file (helper on DebuggerBDB)
            try:
                self.debugger.clear_breaks_for_file(path)  # type: ignore[attr-defined]
            except AttributeError:
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
        self,
        breakpoints: list[FunctionBreakpoint],
    ) -> Sequence[FunctionBreakpoint]:
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
                    self.debugger.bp_manager.function_names.append(name)
                except Exception:
                    # If attribute missing or wrong type, try to set fresh list
                    try:
                        self.debugger.bp_manager.function_names = [name]
                    except Exception:
                        pass

                # The debugger is expected to expose a dict for
                # function_breakpoint_meta; update it directly.
                fbm = self.debugger.bp_manager.function_meta
                meta = fbm.get(name, {})
                meta.setdefault("hit", 0)
                meta["condition"] = condition
                meta["hitCondition"] = hit_condition
                meta["logMessage"] = log_message
                fbm[name] = meta

            # Build per-breakpoint verification results by checking whether
            # the debugger's function_breakpoints list contains the name.
            results: list[FunctionBreakpoint] = []
            fb_list = self.debugger.bp_manager.function_names
            for bp in breakpoints:
                name = bp.get("name")
                verified = False
                if name and isinstance(fb_list, list):
                    try:
                        verified = name in fb_list
                    except Exception:
                        verified = False
                results.append({"verified": verified})
            return results

    def set_exception_breakpoints(self, filters: list[str]) -> list[Breakpoint]:
        with self.command_lock:
            # Set boolean flags if present, fallback to dict otherwise
            verified_all = True
            try:
                self.debugger.exception_handler.config.break_on_raised = "raised" in filters
                self.debugger.exception_handler.config.break_on_uncaught = "uncaught" in filters
            except Exception:
                # If setting flags fails, mark all as unverified
                verified_all = False
            return cast("list[Breakpoint]", [{"verified": verified_all} for _ in filters])

    def continue_(self, thread_id: int) -> ContinueResponseBody:
        with self.command_lock:
            dbg = self.debugger
            if thread_id in dbg.thread_tracker.stopped_thread_ids:
                try:
                    dbg.thread_tracker.stopped_thread_ids.remove(thread_id)
                except Exception:
                    pass
            if not dbg.thread_tracker.stopped_thread_ids:
                dbg.set_continue()
            return cast("ContinueResponseBody", {"allThreadsContinued": True})

    def next_(self, thread_id: int, *, granularity: str = "line") -> None:
        with self.command_lock:
            dbg = self.debugger
            if thread_id == threading.get_ident():
                dbg.stepping_controller.stepping = True
                dbg.stepping_controller.set_granularity(granularity)
                frame = dbg.stepping_controller.current_frame
                if frame is not None:
                    if dbg.stepping_controller.granularity is StepGranularity.INSTRUCTION:
                        # Enable per-instruction trace events on the current frame.
                        frame.f_trace_opcodes = True
                        dbg.set_step()
                    else:
                        # LINE and STATEMENT: step over to the next source line.
                        # (STATEMENT is treated as LINE until column tracking is added.)
                        dbg.set_next(frame)

    def step_in(
        self,
        thread_id: int,
        _target_id: int | None = None,
        *,
        granularity: str = "line",
    ) -> None:
        # _target_id is accepted for DAP compatibility but not yet implemented.
        with self.command_lock:
            dbg = self.debugger
            if thread_id == threading.get_ident():
                dbg.stepping_controller.stepping = True
                dbg.stepping_controller.set_granularity(granularity)
                if dbg.stepping_controller.granularity is StepGranularity.INSTRUCTION:
                    frame = dbg.stepping_controller.current_frame
                    if frame is not None:
                        frame.f_trace_opcodes = True
                dbg.set_step()

    def step_out(self, thread_id: int, *, granularity: str = "line") -> None:
        with self.command_lock:
            dbg = self.debugger
            if thread_id == threading.get_ident():
                dbg.stepping_controller.stepping = True
                dbg.stepping_controller.set_granularity(granularity)
                if dbg.stepping_controller.current_frame is not None:
                    dbg.set_return(dbg.stepping_controller.current_frame)

    # Variables/Stack/Evaluate
    # These follow the launcher semantics, but return dicts directly.

    def stack_trace(
        self,
        thread_id: int,
        start_frame: int = 0,
        levels: int = 0,
    ) -> StackTraceResponseBody:
        dbg = self.debugger
        thread_tracker = getattr(dbg, "thread_tracker", None)
        frames_by_thread = getattr(thread_tracker, "frames_by_thread", {})
        if thread_id not in frames_by_thread:
            return cast("StackTraceResponseBody", {"stackFrames": [], "totalFrames": 0})

        frames = frames_by_thread[thread_id]
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
        if var_ref not in dbg.var_manager.var_refs:
            return {"variables": []}

        frame_info = dbg.var_manager.var_refs[var_ref]
        # scope ref is a tuple of (frame_id, scope)
        if isinstance(frame_info, tuple) and len(frame_info) == (SCOPE_TUPLE_LEN):
            frame_id, scope = frame_info
            frame = None
            if isinstance(frame_id, int):
                frame = getattr(getattr(dbg, "thread_tracker", None), "frame_id_to_frame", {}).get(
                    frame_id,
                )
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
        self,
        variables_reference: int,
        name: str,
        value: str,
    ) -> SetVariableResponseBody | dict[str, Any]:
        dbg = self.debugger
        var_ref = variables_reference
        if var_ref not in dbg.var_manager.var_refs:
            return {
                "success": False,
                "message": f"Invalid variable reference: {var_ref}",
            }

        frame_info = dbg.var_manager.var_refs[var_ref]
        if isinstance(frame_info, tuple) and len(frame_info) == (SCOPE_TUPLE_LEN):
            frame_id, scope = frame_info
            frame = None
            if isinstance(frame_id, int):
                frame = getattr(getattr(dbg, "thread_tracker", None), "frame_id_to_frame", {}).get(
                    frame_id,
                )
            if not frame:
                return {"success": False, "message": "Frame not found"}
            try:
                # Evaluate through policy checker to block dangerous expressions
                target = frame.f_locals if scope == "locals" else frame.f_globals
                target[name] = evaluate_with_policy(value, frame, allow_builtins=True)
                return {
                    "value": target[name],
                    "type": type(target[name]).__name__,
                    "variablesReference": 0,
                }
            except Exception as exc:  # pragma: no cover - defensive
                return {"success": False, "message": str(exc)}
        return {"success": False, "message": "Invalid reference"}

    def evaluate(
        self,
        expression: str,
        frame_id: int | None = None,
        _context: str | None = None,
    ) -> EvaluateResponseBody:
        dbg = self.debugger
        frame = None
        if isinstance(frame_id, int):
            frame = getattr(getattr(dbg, "thread_tracker", None), "frame_id_to_frame", {}).get(
                frame_id,
            )
        if not frame:
            return {
                "result": f"<evaluation of '{expression}' not available>",
                "type": "string",
                "variablesReference": 0,
            }
        try:
            result = evaluate_with_policy(expression, frame, allow_builtins=True)
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

    def completions(
        self,
        text: str,
        column: int,
        frame_id: int | None = None,
        line: int = 1,
    ) -> CompletionsResponseBody:
        """Get expression completions based on runtime frame context.

        Provides intelligent auto-completions by introspecting the current
        frame's local and global namespaces. Supports:
        - Simple name completions (variables, functions, classes)
        - Attribute completions (obj.attr)
        - Module member completions (module.member)

        Args:
            text: The input text to complete
            column: Cursor position (1-based)
            frame_id: Stack frame ID for scope context
            line: Line number (1-based) for multi-line text

        Returns:
            Dict with 'targets' containing completion items

        """
        targets: list[CompletionItem] = []

        # Get frame context
        dbg = self.debugger
        frame = (
            dbg.thread_tracker.frame_id_to_frame.get(frame_id) if frame_id is not None else None
        )

        # Extract the relevant line and prefix
        lines = text.split("\n")
        line_idx = max(0, min(line - 1, len(lines) - 1))
        current_line = lines[line_idx] if lines else ""

        # Convert 1-based column to 0-based index
        col_idx = max(0, column - 1)
        prefix_text = current_line[:col_idx]

        # Find the expression to complete
        expr_to_complete = self._extract_completion_expr(prefix_text)

        if frame is not None:
            # Runtime completions using frame locals/globals
            targets = self._get_runtime_completions(
                expr_to_complete,
                frame.f_locals,
                frame.f_globals,
            )
        else:
            # Fallback: use builtins only
            targets = self._get_runtime_completions(expr_to_complete, {}, vars(builtins))

        return {"targets": targets}

    def _extract_completion_expr(self, text: str) -> str:
        """Extract the expression/identifier to complete from text.

        Handles cases like:
        - "x" -> "x" (simple identifier)
        - "obj." -> "obj." (attribute access)
        - "obj.att" -> "obj.att" (partial attribute)
        - "print(x" -> "x" (function argument)
        - "x + y" -> "y" (binary op)
        """
        if not text:
            return ""

        # Walk backwards to find expression start
        i = len(text) - 1
        depth = 0  # Track parentheses/brackets

        while i >= 0:
            ch = text[i]
            if ch in ")]}>":
                depth += 1
            elif ch in "([{<":
                if depth > 0:
                    depth -= 1
                else:
                    # Found unmatched open bracket - expression starts after
                    return text[i + 1 :].lstrip()
            elif depth == 0 and ch in " \t,;:=+-*/%&|^~!":
                # Expression delimiter (not inside brackets)
                return text[i + 1 :].lstrip()
            i -= 1

        return text.lstrip()

    def _get_runtime_completions(
        self,
        expr: str,
        local_ns: Mapping[str, Any],
        global_ns: Mapping[str, Any],
    ) -> list[CompletionItem]:
        """Get completions using runtime introspection.

        Args:
            expr: Expression prefix to complete
            local_ns: Frame's local namespace
            global_ns: Frame's global namespace

        Returns:
            List of completion items

        """
        targets: list[CompletionItem] = []

        if "." in expr:
            # Attribute completion: evaluate everything before the last dot
            parts = expr.rsplit(".", 1)
            base_expr = parts[0]
            attr_prefix = parts[1] if len(parts) > 1 else ""

            try:
                # Safely evaluate the base expression
                # Cast Mapping to dict for eval() which requires dict
                base_obj = eval(base_expr, dict(global_ns), dict(local_ns))
                targets = self._complete_attributes(base_obj, attr_prefix)
            except Exception:
                # Can't evaluate base - return empty
                pass
        else:
            # Name completion: search locals, globals, and builtins
            prefix = expr
            seen: set[str] = set()

            # Collect from locals
            for name in local_ns:
                if name.startswith(prefix) and name not in seen:
                    seen.add(name)
                    obj = local_ns[name]
                    kind = self._infer_completion_type(obj)
                    targets.append(self._make_completion_item(name, obj, kind))

            # Collect from globals
            for name in global_ns:
                if name.startswith(prefix) and name not in seen:
                    seen.add(name)
                    obj = global_ns[name]
                    kind = self._infer_completion_type(obj)
                    targets.append(self._make_completion_item(name, obj, kind))

            # Collect from builtins
            for name in dir(builtins):
                if name.startswith(prefix) and name not in seen:
                    seen.add(name)
                    obj = getattr(builtins, name, None)
                    kind = self._infer_completion_type(obj)
                    targets.append(self._make_completion_item(name, obj, kind))

        # Sort by label for consistent ordering
        targets.sort(key=lambda x: x.get("label", ""))
        return targets

    def _complete_attributes(self, obj: Any, prefix: str) -> list[CompletionItem]:
        """Complete attributes of an object."""
        targets: list[CompletionItem] = []
        try:
            # Get all attributes (including from __dir__ if defined)
            attrs = dir(obj)
        except Exception:
            return targets

        for attr in attrs:
            if attr.startswith(prefix):
                try:
                    value = getattr(obj, attr, None)
                    kind = self._infer_completion_type(value)
                    targets.append(self._make_completion_item(attr, value, kind))
                except Exception:
                    # Some attributes may raise on access
                    targets.append(
                        {
                            "label": attr,
                            "type": "property",
                        },
                    )

        return targets

    def _make_completion_item(self, name: str, obj: Any, kind: str) -> CompletionItem:
        """Create a DAP completion item."""
        item: CompletionItem = {
            "label": name,
            "type": cast("CompletionItemKind", kind),
        }

        # Add type detail for better UX
        try:
            type_name = type(obj).__name__
            if kind == "function" and callable(obj):
                # Try to get signature for functions
                try:
                    sig = inspect.signature(obj)
                    item["detail"] = f"{name}{sig}"
                except (ValueError, TypeError):
                    item["detail"] = f"{name}(...)"
            elif kind in ("class", "module"):
                item["detail"] = type_name
            else:
                item["detail"] = f": {type_name}"
        except Exception:
            pass

        return item

    def _infer_completion_type(self, obj: Any) -> str:  # noqa: PLR0911
        """Infer DAP completion item type from Python object."""
        if obj is None:
            return "value"
        if isinstance(obj, type):
            return "class"
        if isinstance(obj, types.ModuleType):
            return "module"
        if isinstance(obj, (types.FunctionType, types.BuiltinFunctionType)):
            return "function"
        if isinstance(obj, types.MethodType):
            return "method"
        if callable(obj):
            return "function"
        return "variable"
