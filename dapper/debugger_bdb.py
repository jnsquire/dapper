"""
DebuggerBDB class and related helpers for debug launcher.
"""

from __future__ import annotations

import bdb
import re
import threading
import traceback
from pathlib import Path

from dapper.debug_adapter_comm import process_queued_commands
from dapper.debug_adapter_comm import send_debug_message
from dapper.debug_helpers import frame_may_handle_exception

# Safety limit for stack walking to avoid infinite loops on mocked frames
MAX_STACK_DEPTH = 128


def evaluate_hit_condition(expr: str, hit_count: int) -> bool:
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


class DebuggerBDB(bdb.Bdb):
    def __init__(self, skip=None):
        super().__init__(skip)
        self.is_terminated = False
        self.breakpoints = {}
        self.function_breakpoints = []
        self.function_breakpoint_meta = {}
        # Exception breakpoint flags (separate booleans for clarity)
        self.exception_breakpoints_uncaught = False
        self.exception_breakpoints_raised = False
        self.custom_breakpoints = {}
        self.current_thread_id = threading.get_ident()
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
        self.current_exception_info = {}
        self.breakpoint_meta = {}
        # Data breakpoint Phase 2 (lightweight): watch names & last values per frame
        self.data_watch_names: set[str] = set()
        self._last_locals_by_frame: dict[int, dict[str, object]] = {}
        self.data_watch_meta: dict[str, list[dict]] = {}
        # Global fallback for tests / cases where new frame objects appear per line
        self._last_global_watch_values: dict[str, object] = {}

    # ---------------- Data Breakpoint (Watch) Support -----------------
    def register_data_watches(
        self, names: list[str], metas: list[tuple[str, dict]] | None = None
    ) -> None:
        """Replace the set of variable names to watch for changes.

        Optionally accepts metadata tuples (name, meta) mirroring adapter-side
        data breakpoint records containing 'condition' and 'hitCondition'.
        Multiple meta entries per variable name are stored in a list.
        """
        self.data_watch_names = {n for n in names if isinstance(n, str) and n}
        self.data_watch_meta = {n: [] for n in self.data_watch_names}
        if metas:
            for name, meta in metas:
                if name in self.data_watch_meta:
                    self.data_watch_meta[name].append(meta)

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
        if not self.data_watch_names or not isinstance(frame.f_locals, dict):
            return None

        frame_key = id(frame)
        current_locals = frame.f_locals
        prior = self._last_locals_by_frame.get(frame_key)

        for name in self.data_watch_names:
            if name not in current_locals:
                continue
            new_val = current_locals[name]
            old_val = None
            have_old = False

            if prior is not None and name in prior:
                old_val = prior.get(name, object())
                have_old = True
            elif name in self._last_global_watch_values:
                old_val = self._last_global_watch_values[name]
                have_old = True

            if have_old:
                try:
                    equal = new_val == old_val
                except Exception:  # pragma: no cover - defensive
                    equal = False
                if old_val is not new_val and not equal:
                    return name
        return None

    def _update_watch_snapshots(self, frame):
        """Update snapshots of watched variable values."""
        if not self.data_watch_names or not isinstance(frame.f_locals, dict):
            return

        frame_key = id(frame)
        current_locals = frame.f_locals

        # Snapshot current watched values per frame
        self._last_locals_by_frame[frame_key] = {
            n: current_locals.get(n) for n in self.data_watch_names
        }
        # Update global snapshot
        for n in self.data_watch_names:
            if n in current_locals:
                self._last_global_watch_values[n] = current_locals[n]

    def _should_stop_for_data_breakpoint(self, changed_name, frame):
        """Evaluate conditions and hitConditions for a changed variable."""
        metas = self.data_watch_meta.get(changed_name, [])

        for m in metas:
            # Increment hit counter per meta (change-based hit)
            m["hit"] = int(m.get("hit", 0)) + 1

            # Check hitCondition
            hc_expr = m.get("hitCondition")
            if hc_expr and not evaluate_hit_condition(str(hc_expr), m["hit"]):
                continue

            # Check condition
            cond_expr = m.get("condition")
            if cond_expr:
                try:
                    cond_ok = bool(eval(str(cond_expr), frame.f_globals, frame.f_locals))
                except Exception:  # pragma: no cover - defensive
                    cond_ok = False
                if not cond_ok:
                    continue
            return True

        # No metadata means default stop semantics
        return not metas

    def _ensure_thread_registered(self, thread_id):
        """Ensure the current thread is registered and send thread started event if needed."""
        if thread_id not in self.threads:
            thread_name = threading.current_thread().name
            self.threads[thread_id] = thread_name
            send_debug_message(
                "thread",
                threadId=thread_id,
                reason="started",
                name=thread_name,
            )

    def _handle_regular_breakpoint(self, filename, line, frame):
        """Handle regular line breakpoints with hit conditions and log messages."""
        if not (
            self.get_break(filename, line)
            or (filename in self.custom_breakpoints and line in self.custom_breakpoints[filename])
        ):
            return False

        meta = self.breakpoint_meta.get((filename, int(line)))
        if meta is not None:
            meta["hit"] = int(meta.get("hit", 0)) + 1
            hc_expr = meta.get("hitCondition")
            if hc_expr and not evaluate_hit_condition(str(hc_expr), meta["hit"]):
                self.set_continue()
                return True

            log_msg = meta.get("logMessage")
            if log_msg:
                try:
                    rendered = format_log_message(str(log_msg), frame)
                except Exception:
                    rendered = str(log_msg)
                send_debug_message("output", category="console", output=str(rendered))
                self.set_continue()
                return True
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

        send_debug_message("stopped", **event_args)

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
        process_queued_commands()
        self.set_continue()

    def user_exception(self, frame, exc_info):
        if not getattr(self, "exception_breakpoints_raised", False) and not getattr(
            self, "exception_breakpoints_uncaught", False
        ):
            return
        exc_type, exc_value, exc_traceback = exc_info
        is_uncaught = True
        res = frame_may_handle_exception(frame)
        if res is True or res is None:
            is_uncaught = False
        thread_id = threading.get_ident()
        break_mode = (
            "always" if getattr(self, "exception_breakpoints_raised", False) else "unhandled"
        )
        if (is_uncaught and getattr(self, "exception_breakpoints_uncaught", False)) or getattr(
            self, "exception_breakpoints_raised", False
        ):
            break_on_exception = True
        else:
            break_on_exception = False
        stack_trace = traceback.format_exception(exc_type, exc_value, exc_traceback)
        if break_on_exception:
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
            send_debug_message(
                "stopped",
                threadId=thread_id,
                reason="exception",
                text=f"{exc_type.__name__}: {exc_value!s}",
                allThreadsStopped=True,
            )
            process_queued_commands()
            try:
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

    def user_call(self, frame, argument_list):  # noqa: ARG002
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
        meta["hit"] = int(meta.get("hit", 0)) + 1
        hc_expr = meta.get("hitCondition")
        if hc_expr and not evaluate_hit_condition(str(hc_expr), meta["hit"]):
            return
        cond = meta.get("condition")
        if cond:
            try:
                if not eval(cond, frame.f_globals, frame.f_locals):
                    return
            except Exception:
                return
        log_msg = meta.get("logMessage")
        if log_msg:
            try:
                rendered = format_log_message(str(log_msg), frame)
            except Exception:
                rendered = str(log_msg)
            send_debug_message("output", category="console", output=str(rendered))
            return
        thread_id = threading.get_ident()
        if thread_id not in self.threads:
            thread_name = threading.current_thread().name
            self.threads[thread_id] = thread_name
            send_debug_message(
                "thread",
                threadId=thread_id,
                reason="started",
                name=thread_name,
            )
        self.current_frame = frame
        self.stopped_thread_ids.add(thread_id)
        stack_frames = self._get_stack_frames(frame)
        self.frames_by_thread[thread_id] = stack_frames
        send_debug_message(
            "stopped",
            threadId=thread_id,
            reason="function breakpoint",
            allThreadsStopped=True,
        )
        process_queued_commands()
        self.set_continue()
