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
        self.exception_breakpoints = {"uncaught": False, "raised": False}
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

    def user_line(self, frame):
        filename = frame.f_code.co_filename
        line = frame.f_lineno
        if self.get_break(filename, line) or (
            filename in self.custom_breakpoints and line in self.custom_breakpoints[filename]
        ):
            meta = self.breakpoint_meta.get((filename, int(line)))
            if meta is not None:
                meta["hit"] = int(meta.get("hit", 0)) + 1
                hc_expr = meta.get("hitCondition")
                if hc_expr and not evaluate_hit_condition(str(hc_expr), meta["hit"]):
                    self.set_continue()
                    return
                log_msg = meta.get("logMessage")
                if log_msg:
                    try:
                        rendered = format_log_message(str(log_msg), frame)
                    except Exception:
                        rendered = str(log_msg)
                    send_debug_message("output", category="console", output=str(rendered))
                    self.set_continue()
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
        reason = "breakpoint"
        if self.stop_on_entry:
            reason = "entry"
            self.stop_on_entry = False
        elif self.stepping:
            reason = "step"
            self.stepping = False
        send_debug_message(
            "stopped",
            threadId=thread_id,
            reason=reason,
            allThreadsStopped=True,
        )
        process_queued_commands()
        self.set_continue()

    def user_exception(self, frame, exc_info):
        if not self.exception_breakpoints["raised"] and not self.exception_breakpoints["uncaught"]:
            return
        exc_type, exc_value, exc_traceback = exc_info
        is_uncaught = True
        res = frame_may_handle_exception(frame)
        if res is True or res is None:
            is_uncaught = False
        thread_id = threading.get_ident()
        break_mode = "always" if self.exception_breakpoints["raised"] else "unhandled"
        if (is_uncaught and self.exception_breakpoints["uncaught"]) or self.exception_breakpoints[
            "raised"
        ]:
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
        while f is not None:
            frame_id = self.next_frame_id
            self.next_frame_id += 1
            self.frame_id_to_frame[frame_id] = f
            filename = f.f_code.co_filename
            lineno = f.f_lineno
            stack_frame = {
                "id": frame_id,
                "name": f.f_code.co_name or "<unknown>",
                "line": lineno,
                "column": 0,
                "source": {
                    "name": Path(filename).name,
                    "path": filename,
                },
            }
            stack_frames.append(stack_frame)
            f = f.f_back
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
