# ruff: noqa: PLC0415
"""
DebuggerBDB class and related helpers for debug launcher.
"""

from __future__ import annotations

import bdb
import contextlib
import threading
import traceback
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import Callable
from typing import cast

from dapper.core.breakpoint_resolver import BreakpointResolver
from dapper.core.breakpoint_resolver import ResolveAction
from dapper.core.data_breakpoint_state import DataBreakpointState
from dapper.core.debug_helpers import frame_may_handle_exception
from dapper.core.debug_utils import MAX_STACK_DEPTH
from dapper.core.debug_utils import get_function_candidate_names

if TYPE_CHECKING:
    from dapper.protocol.debugger_protocol import ExceptionInfo
    from dapper.protocol.debugger_protocol import Variable

try:
    from dapper._frame_eval.debugger_integration import integrate_debugger_bdb
except Exception:  # pragma: no cover - optional integration
    integrate_debugger_bdb = None

def _noop_send_message(*args, **kwargs):
    pass

def _noop_process_commands():
    pass

class DebuggerBDB(bdb.Bdb):
    def __init__(
        self,
        skip=None,
        enable_frame_eval: bool = False,
        send_message: Callable[..., Any] = _noop_send_message,
        process_commands: Callable[[], Any] = _noop_process_commands,
    ):
        super().__init__(skip)
        # Use injected callbacks or fall back to no-ops
        self.send_message = send_message
        self.process_commands = process_commands

        # Unified breakpoint resolver for condition/hit/log evaluation
        self._breakpoint_resolver = BreakpointResolver()

        self.is_terminated = False
        self.breakpoints = {}
        self.function_breakpoints = []
        self.function_breakpoint_meta = {}
        # Exception breakpoint flags (separate booleans for clarity)
        self.exception_breakpoints_uncaught = False
        self.exception_breakpoints_raised = False
        self.custom_breakpoints = {}
        self.current_thread_id = threading.get_ident()

        if enable_frame_eval:
            try:
                # Dynamic import to avoid top-level cycles when frame eval is optional
                from dapper._frame_eval.debugger_integration import integrate_debugger_bdb

                integrate_debugger_bdb(self)
            except ImportError:
                pass
        self.current_frame = None
        self.stepping = False
        self.stop_on_entry = False
        self.frames_by_thread = {}
        self.threads = {}
        self.thread_ids = {}
        self.thread_count = 1
        self.stopped_thread_ids = set()
        self.next_frame_id = 1
        self.frame_id_to_frame = {}
        self.next_var_ref = 1000
        self.var_refs = {}
        # Optional: adapter/launcher may store configured data breakpoints here
        # for simple bookkeeping. Not required for core BDB operation.
        self.data_breakpoints: list[dict[str, Any]] | None = None
        # Mapping thread id -> structured exception info captured when we break on
        # exceptions.
        self.current_exception_info: dict[int, ExceptionInfo] = {}
        self.breakpoint_meta = {}

        # Consolidated data breakpoint state
        self._data_bp_state = DataBreakpointState()

    # --- Compatibility properties for existing code that accesses the old attributes ---
    @property
    def data_watch_names(self) -> set[str]:
        """Set of variable names being watched for changes."""
        return self._data_bp_state.watch_names

    @data_watch_names.setter
    def data_watch_names(self, value: set[str] | list[str] | None) -> None:
        if value is None:
            self._data_bp_state.watch_names = set()
        elif isinstance(value, set):
            self._data_bp_state.watch_names = value
        else:
            self._data_bp_state.watch_names = set(value)

    @property
    def data_watch_meta(self) -> dict[str, Any]:
        """Metadata mapping for watched variable names."""
        return self._data_bp_state.watch_meta

    @data_watch_meta.setter
    def data_watch_meta(self, value: dict[str, Any] | None) -> None:
        if value is None:
            self._data_bp_state.watch_meta = {}
        else:
            self._data_bp_state.watch_meta = value

    @property
    def _last_locals_by_frame(self) -> dict[int, dict[str, object]]:
        """Per-frame snapshot of watched variable values."""
        return self._data_bp_state.last_values_by_frame

    @property
    def _last_global_watch_values(self) -> dict[str, object]:
        """Global fallback snapshot of watched variable values."""
        return self._data_bp_state.global_values

    @property
    def _data_watches(self) -> dict[str, Any]:
        """Server-style mapping of dataId -> watch metadata."""
        return self._data_bp_state.data_watches

    @_data_watches.setter
    def _data_watches(self, value: dict[str, Any] | None) -> None:
        if value is None:
            self._data_bp_state.data_watches = {}
        else:
            self._data_bp_state.data_watches = value

    @property
    def _frame_watches(self) -> dict[int, list[str]]:
        """Server-style mapping of frameId -> list of dataIds."""
        return self._data_bp_state.frame_watches

    @_frame_watches.setter
    def _frame_watches(self, value: dict[int, list[str]] | None) -> None:
        if value is None:
            self._data_bp_state.frame_watches = {}
        else:
            self._data_bp_state.frame_watches = value

    # ---------------- Data Breakpoint (Watch) Support -----------------
    def register_data_watches(
        self, names: list[str], metas: list[tuple[str, dict]] | None = None
    ) -> None:
        """Replace the set of variable names to watch for changes.

        Optionally accepts metadata tuples (name, meta) mirroring adapter-side
        data breakpoint records containing 'condition' and 'hitCondition'.
        Multiple meta entries per variable name are stored in a list.
        """
        self._data_bp_state.register_watches(names, metas)

    def record_breakpoint(self, path, line, *, condition, hit_condition, log_message):
        key = (path, int(line))
        meta = self.breakpoint_meta.get(key, {})
        meta.setdefault("hit", 0)
        meta["condition"] = condition
        meta["hitCondition"] = hit_condition
        meta["logMessage"] = log_message
        self.breakpoint_meta[key] = meta

    def clear_break_meta_for_file(self, path):
        to_del = [k for k in self.breakpoint_meta if k[0] == path]
        for k in to_del:
            self.breakpoint_meta.pop(k, None)

    def _check_data_watch_changes(self, frame):
        """Check for changes in watched variables and return changed variable name if any."""
        if not isinstance(frame.f_locals, dict):
            return None
        return self._data_bp_state.check_for_changes(id(frame), frame.f_locals)

    def _update_watch_snapshots(self, frame):
        """Update snapshots of watched variable values."""
        if not isinstance(frame.f_locals, dict):
            return
        self._data_bp_state.update_snapshots(id(frame), frame.f_locals)

    # ---------------- Variable object helper -----------------
    def make_variable_object(
        self, name: Any, value: Any, frame: Any | None = None, *, max_string_length: int = 1000
    ) -> Variable:
        """Create a Variable-shaped dict with presentationHint and optional var-ref allocation.

        This mirrors the module-level helper previously stored in debug_shared.
        When used via this method, variablesReference bookkeeping will use this
        debugger instance's next_var_ref and var_refs.
        """

        # Helper implementations copied from debug_shared module-level helpers
        def _format_value_str(v: Any, max_len: int) -> str:
            try:
                s = repr(v)
            except Exception:
                return "<Error getting value>"
            else:
                if len(s) > max_len:
                    return s[:max_len] + "..."
                return s

        def _allocate_var_ref(v: Any) -> int:
            if not (hasattr(v, "__dict__") or isinstance(v, (dict, list, tuple))):
                return 0
            try:
                ref = self.next_var_ref
                self.next_var_ref = ref + 1
                self.var_refs[ref] = ("object", v)
            except Exception:
                return 0
            else:
                return ref

        def _detect_kind_and_attrs(v: Any) -> tuple[str, list[str]]:
            attrs: list[str] = []
            if callable(v):
                attrs.append("hasSideEffects")
                return "method", attrs
            if isinstance(v, type):
                return "class", attrs
            if isinstance(v, (list, tuple, dict, set)):
                return "data", attrs
            if isinstance(v, (str, bytes)):
                sval = v.decode() if isinstance(v, bytes) else v
                if isinstance(sval, str) and ("\n" in sval or len(sval) > max_string_length):
                    attrs.append("rawString")
                return "data", attrs
            return "data", attrs

        def _visibility(n: Any) -> str:
            try:
                return "private" if str(n).startswith("_") else "public"
            except Exception:
                return "public"

        def _detect_has_data_breakpoint(n: Any, fr: Any | None) -> bool:
            name_str = str(n)
            frame_id = id(fr) if fr is not None else None
            return self._data_bp_state.has_data_breakpoint_for_name(name_str, frame_id)

        val_str = _format_value_str(value, max_string_length)
        var_ref = _allocate_var_ref(value)
        type_name = type(value).__name__
        kind, attrs = _detect_kind_and_attrs(value)
        if _detect_has_data_breakpoint(name, frame) and "hasDataBreakpoint" not in attrs:
            attrs.append("hasDataBreakpoint")
        presentation = {
            "kind": kind,
            "attributes": attrs,
            "visibility": _visibility(name),
        }

        return cast(
            "Variable",
            {
                "name": str(name),
                "value": val_str,
                "type": type_name,
                "variablesReference": var_ref,
                "presentationHint": presentation,
            },
        )

    # Note: create_variable_object alias removed. Use `make_variable_object` on debugger instances.

    def _should_stop_for_data_breakpoint(self, changed_name, frame):
        """Evaluate conditions and hitConditions for a changed variable.
        """
        metas = (self.data_watch_meta or {}).get(changed_name, [])

        # No metadata means default stop semantics
        if not metas:
            return True

        # Check each meta entry - stop if any passes all conditions
        for m in metas:
            result = self._breakpoint_resolver.resolve(m, frame)
            if result.action == ResolveAction.STOP:
                return True
            # For logpoints on data breakpoints, we still stop (data changed)
            # but the log message was already emitted by the resolver if emit_output was provided

        return False

    def _ensure_thread_registered(self, thread_id):
        """Ensure the current thread is registered and send thread started event if needed."""
        if thread_id not in self.threads:
            thread_name = threading.current_thread().name
            self.threads[thread_id] = thread_name
            self.send_message(
                "thread",
                threadId=thread_id,
                reason="started",
                name=thread_name,
            )

    def _handle_regular_breakpoint(self, filename, line, frame):
        """Handle regular line breakpoints with hit conditions and log messages.
        Returns True if the breakpoint was handled (either hit or skipped due to conditions),
        False if no breakpoint exists at this location.
        """
        if not (
            self.get_break(filename, line)
            or (filename in self.custom_breakpoints and line in self.custom_breakpoints[filename])
        ):
            return False

        meta = self.breakpoint_meta.get((filename, int(line)))

        # Create an output emitter that sends to the debug client
        def emit_output(category: str, output: str) -> None:
            self.send_message("output", category=category, output=output)

        result = self._breakpoint_resolver.resolve(meta, frame, emit_output=emit_output)

        if result.action == ResolveAction.CONTINUE:
            # Condition not met or logpoint emitted - continue execution
            self.set_continue()
            return True

        # STOP action means conditions passed - let caller handle the stop
        return False

    def _emit_stopped_event(self, frame, thread_id, reason, description=None):
        """Emit a stopped event with proper bookkeeping."""
        self.current_frame = frame
        self.stopped_thread_ids.add(thread_id)
        stack_frames = self._get_stack_frames(frame)
        self.frames_by_thread[thread_id] = stack_frames

        event_args = {
            "threadId": thread_id,
            "reason": reason,
            "allThreadsStopped": True,
        }
        if description:
            event_args["description"] = description

        self.send_message("stopped", **event_args)

    def user_line(self, frame):
        filename = frame.f_code.co_filename
        line = frame.f_lineno
        thread_id = threading.get_ident()

        self.botframe = frame  # to satisfy bdb expectations

        # Check for data watch changes first
        changed_name = self._check_data_watch_changes(frame)
        self._update_watch_snapshots(frame)

        if changed_name and self._should_stop_for_data_breakpoint(changed_name, frame):
            self._ensure_thread_registered(thread_id)
            self._emit_stopped_event(
                frame, thread_id, "data breakpoint", f"{changed_name} changed"
            )
            return

        # Handle regular breakpoints
        if self._handle_regular_breakpoint(filename, line, frame):
            return

        # Default stop behavior for stepping, entry, or normal breakpoints
        self._ensure_thread_registered(thread_id)

        reason = "breakpoint"
        if self.stop_on_entry:
            reason = "entry"
            self.stop_on_entry = False
        elif self.stepping:
            reason = "step"
            self.stepping = False

        self._emit_stopped_event(frame, thread_id, reason)
        self.process_commands()
        self.set_continue()

    def user_exception(self, frame, exc_info):
        if not self.exception_breakpoints_raised and not self.exception_breakpoints_uncaught:
            return
        exc_type, exc_value, exc_traceback = exc_info
        is_uncaught = True
        # Ask the helper whether the current frame will handle this exception. If it reports
        # True (or "unknown" via None) we treat the exception as handled and skip uncaught logic.
        res = frame_may_handle_exception(frame)
        if res is True or res is None:
            is_uncaught = False
        thread_id = threading.get_ident()
        break_mode = "always" if self.exception_breakpoints_raised else "unhandled"
        # Decide whether we should interrupt execution. A configured "uncaught" breakpoint only
        # triggers when the exception bubbles out of the current frame, while the "raised" mode
        # triggers immediately.
        if (
            is_uncaught and self.exception_breakpoints_uncaught
        ) or self.exception_breakpoints_raised:
            break_on_exception = True
        else:
            break_on_exception = False

        if break_on_exception:
            # Cache the exception details so the adapter can surface comprehensive information
            # (including formatted stack trace) in subsequent protocol requests.
            stack_trace = traceback.format_exception(exc_type, exc_value, exc_traceback)
            self.current_exception_info[thread_id] = {
                "exceptionId": exc_type.__name__,
                "description": str(exc_value),
                "breakMode": break_mode,
                "details": {
                    "message": str(exc_value),
                    "typeName": exc_type.__name__,
                    "fullTypeName": (exc_type.__module__ + "." + exc_type.__name__),
                    "source": frame.f_code.co_filename,
                    "stackTrace": stack_trace,
                },
            }
        if break_on_exception:
            self.current_frame = frame
            self.stopped_thread_ids.add(thread_id)
            stack_frames = self._get_stack_frames(frame)
            self.frames_by_thread[thread_id] = stack_frames
            # Notify the client that execution has paused. The adapter inspects the text/frames
            # payload to populate the exception UI.
            self.send_message(
                "stopped",
                threadId=thread_id,
                reason="exception",
                text=f"{exc_type.__name__}: {exc_value!s}",
                allThreadsStopped=True,
            )
            self.process_commands()
            try:
                # Resume the interpreter once the client responds (mirrors line breakpoint flow).
                self.set_continue()
            except Exception:
                pass

    def _get_stack_frames(self, frame):
        stack_frames = []
        f = frame
        visited = set()
        depth = 0
        while f is not None and depth < MAX_STACK_DEPTH:
            # Break if cycle detected
            fid = id(f)
            if fid in visited:
                break
            visited.add(fid)
            depth += 1
            try:
                code = f.f_code
                filename = getattr(code, "co_filename", "<unknown>")
                lineno = getattr(f, "f_lineno", 0)
                name = getattr(code, "co_name", "<unknown>") or "<unknown>"
            except Exception:
                break
            frame_id = self.next_frame_id
            self.next_frame_id += 1
            self.frame_id_to_frame[frame_id] = f
            stack_frame = {
                "id": frame_id,
                "name": name,
                "line": lineno,
                "column": 0,
                "source": {
                    "name": Path(filename).name if isinstance(filename, str) else str(filename),
                    "path": filename,
                },
            }
            stack_frames.append(stack_frame)
            # Next frame with defensive getattr
            try:
                f = getattr(f, "f_back", None)
            except Exception:
                break
        return stack_frames

    def set_custom_breakpoint(self, filename, line, condition=None):
        if filename not in self.custom_breakpoints:
            self.custom_breakpoints[filename] = {}
        self.custom_breakpoints[filename][line] = condition
        self.set_break(filename, line, cond=condition)

    def clear_custom_breakpoint(self, filename, line):
        if filename in self.custom_breakpoints and line in self.custom_breakpoints[filename]:
            del self.custom_breakpoints[filename][line]
            self.clear_break(filename, line)

    def clear_all_custom_breakpoints(self):
        self.custom_breakpoints.clear()

    def clear_all_function_breakpoints(self):
        self.function_breakpoints = []
        self.function_breakpoint_meta.clear()

    # ---------------- Breakpoint housekeeping helpers -----------------
    def clear_breaks_for_file(self, path: str) -> None:
        """Clear all standard breakpoints for a given file and related metadata.

        Iterates bdb's internal break table and clears every breakpoint for
        the specified filename. Also clears adapter-side breakpoint metadata
        for that file.
        """
        try:
            # bdb maintains a mapping filename -> list[int] of line numbers
            lines = self.breaks.get(path, [])  # type: ignore[attr-defined]
        except Exception:
            lines = []
        for ln in lines:
            # Best-effort clearing of breakpoints per line
            if ln is None:
                continue
            try:
                iln = int(ln)
            except Exception:
                continue
            with contextlib.suppress(Exception):
                self.clear_break(path, iln)
        # Clear DAP-specific metadata for this file, if any
        try:
            self.clear_break_meta_for_file(path)
        except Exception:
            pass

    def user_call(self, frame, argument_list):
        """Handle function breakpoints.

        Checks if the current function call matches any registered function
        breakpoints and evaluates conditions/hit counts/log messages.
        """
        # Reference argument_list to avoid static analyzers reporting it as unused
        _ = argument_list

        if not self.function_breakpoints and not self.function_breakpoint_meta:
            return

        candidates = get_function_candidate_names(frame)
        match_name = None
        for name in self.function_breakpoints:
            if name in candidates:
                match_name = name
                break
        if match_name is None:
            return

        meta = self.function_breakpoint_meta.get(match_name, {})

        # Create an output emitter for logpoints
        def emit_output(category: str, output: str) -> None:
            self.send_message("output", category=category, output=output)

        result = self._breakpoint_resolver.resolve(meta, frame, emit_output=emit_output)

        if result.action != ResolveAction.STOP:
            # Condition not met or logpoint emitted - continue without stopping
            return

        # Stop at the function breakpoint
        thread_id = threading.get_ident()
        self._ensure_thread_registered(thread_id)
        self._emit_stopped_event(frame, thread_id, "function breakpoint")
        self.process_commands()
        self.set_continue()
