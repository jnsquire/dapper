"""
DebuggerBDB class and related helpers for debug launcher.
"""

from __future__ import annotations

import bdb
import contextlib
import importlib
import logging
import re
import sys
import threading
import traceback
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from dapper.debug_helpers import frame_may_handle_exception

if TYPE_CHECKING:
    from dapper.debugger_protocol import Variable

# Cached resolvers for the two external helpers. We prefer the launcher
# helpers when that module is present (tests commonly patch
# `dapper.debug_launcher.send_debug_message`) and fall back to the adapter
# communication helpers otherwise. The resolver updates the cached target if
# the launcher module appears or its attribute is replaced, so unittest.patch
# usage continues to work.
_impl_cache: dict[str, Any | None] = {
    "cached_send": None,
    "cached_process": None,
    "registered_send": None,
}


def send_debug_message(*args, **kwargs):
    """Call the best available send_debug_message implementation.

    This checks `sys.modules` for `dapper.debug_launcher` and prefers
    its `send_debug_message` attribute when present (this allows tests that
    patch that attribute to be observed). If not available, we fall back to
    `dapper.debug_adapter_comm.send_debug_message` and cache that.
    """
    # Prefer explicit registered helper first (tests may call register_debug_helpers)
    registered = _impl_cache.get("registered_send")
    if registered is not None:
        return registered(*args, **kwargs)

    # Prefer patched launcher helper when present in sys.modules
    mod = sys.modules.get("dapper.debug_launcher")
    if mod is not None:
        fn = getattr(mod, "send_debug_message", None)
        if callable(fn):
            if fn is not _impl_cache.get("cached_send"):
                _impl_cache["cached_send"] = fn
            impl = _impl_cache.get("cached_send")
            assert impl is not None
            return impl(*args, **kwargs)

    # Fallback to adapter comm helper
    impl = _impl_cache.get("cached_send")
    if impl is None or getattr(impl, "__module__", "") == "dapper.debug_adapter_comm":
        try:
            mod_fallback = importlib.import_module("dapper.debug_adapter_comm")
            _fallback = getattr(mod_fallback, "send_debug_message", None)
            if callable(_fallback):
                if impl is not _fallback:
                    _impl_cache["cached_send"] = _fallback
                impl = _impl_cache.get("cached_send")
        except Exception:
            # Last resort: try dynamic import path again (very rare)
            try:
                mod2 = importlib.import_module("dapper.debug_adapter_comm")
                fn2 = getattr(mod2, "send_debug_message", None)
                if callable(fn2):
                    _impl_cache["cached_send"] = fn2
                    impl = fn2
            except Exception:
                _impl_cache["cached_send"] = None
                impl = None

    if impl is None:
        msg = "No send_debug_message implementation available"
        raise RuntimeError(msg)

    return impl(*args, **kwargs)


def process_queued_commands():
    """Call the best available process_queued_commands implementation.

    Works similarly to send_debug_message: prefer launcher helper if present,
    otherwise use adapter comm helper.
    """
    # Use the single adapter-side implementation. Import lazily to avoid
    # circular imports when this module is imported early in tests.
    try:
        mod = importlib.import_module("dapper.debug_adapter_comm")
        fn = getattr(mod, "process_queued_commands", None)
        if callable(fn):
            return fn()
    except Exception:
        # Fall through to error below
        pass

    msg = "No process_queued_commands implementation available"
    raise RuntimeError(msg)


def register_debug_helpers(send_fn=None):
    """Register explicit debug helper functions.

    Tests can call this to inject mocks directly (preferred over patching
    other modules). Passing None leaves the corresponding helper untouched.
    """
    if send_fn is not None:
        _impl_cache["registered_send"] = send_fn


def unregister_debug_helpers():
    """Remove any registered debug helpers so the module falls back to
    the normal resolution behavior (launcher helper or adapter comm).
    """
    _impl_cache["registered_send"] = None


# Module logger for diagnostic messages (merged from alternate implementation)
logger = logging.getLogger(__name__)

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
        # Optional: adapter/launcher may store configured data breakpoints here
        # for simple bookkeeping. Not required for core BDB operation.
        self.data_breakpoints: list[dict[str, Any]] | None = None
        self.current_exception_info = {}
        self.breakpoint_meta = {}
        # Data breakpoint Phase 2 (lightweight): watch names & last values per frame
        # Use types compatible with DebuggerLike: allow None or concrete types
        self.data_watch_names: set[str] | list[str] | None = set()
        self._last_locals_by_frame: dict[int, dict[str, object]] = {}
        self.data_watch_meta: dict[str, Any] | None = {}
        # PyDebugger/server style mappings
        self._data_watches: dict[str, Any] | None = None
        self._frame_watches: dict[int, list[str]] | None = None
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
            # Direct attributes now assumed to exist
            dw_names = self.data_watch_names
            if isinstance(dw_names, (set, list)) and name_str in dw_names:
                return True
            dw_meta = self.data_watch_meta
            if isinstance(dw_meta, dict) and name_str in dw_meta:
                return True
            frame_watches = self._frame_watches
            if fr is not None and isinstance(frame_watches, dict):
                for data_ids in frame_watches.values():
                    if not isinstance(data_ids, list):
                        continue
                    for did in data_ids:
                        if isinstance(did, str) and (f":var:{name_str}" in did or name_str in did):
                            return True
            return False

        val_str = _format_value_str(value, max_string_length)
        var_ref = _allocate_var_ref(value)
        type_name = type(value).__name__
        kind, attrs = _detect_kind_and_attrs(value)
        if _detect_has_data_breakpoint(name, frame) and "hasDataBreakpoint" not in attrs:
            attrs.append("hasDataBreakpoint")
        presentation = {"kind": kind, "attributes": attrs, "visibility": _visibility(name)}

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
        """Evaluate conditions and hitConditions for a changed variable."""
        metas = (self.data_watch_meta or {}).get(changed_name, [])

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
        if not self.exception_breakpoints_raised and not self.exception_breakpoints_uncaught:
            return
        exc_type, exc_value, exc_traceback = exc_info
        is_uncaught = True
        res = frame_may_handle_exception(frame)
        if res is True or res is None:
            is_uncaught = False
        thread_id = threading.get_ident()
        break_mode = "always" if self.exception_breakpoints_raised else "unhandled"
        if (is_uncaught and self.exception_breakpoints_uncaught) or self.exception_breakpoints_raised:
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
