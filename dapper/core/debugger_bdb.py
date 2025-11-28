# ruff: noqa: PLC0415
"""
DebuggerBDB class and related helpers for debug launcher.
"""

from __future__ import annotations

import bdb
import contextlib
import threading
from typing import TYPE_CHECKING
from typing import Any
from typing import Callable

from dapper.core.breakpoint_resolver import BreakpointResolver
from dapper.core.breakpoint_resolver import ResolveAction
from dapper.core.data_breakpoint_state import DataBreakpointState
from dapper.core.debug_utils import get_function_candidate_names
from dapper.core.exception_handler import ExceptionHandler
from dapper.core.stepping_controller import SteppingController
from dapper.core.thread_tracker import ThreadTracker
from dapper.core.variable_manager import VariableManager

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
        # Exception handling
        self._exception_handler = ExceptionHandler()
        self.custom_breakpoints = {}
        self.current_thread_id = threading.get_ident()

        if enable_frame_eval:
            try:
                # Dynamic import to avoid top-level cycles when frame eval is optional
                from dapper._frame_eval.debugger_integration import integrate_debugger_bdb

                integrate_debugger_bdb(self)
            except ImportError:
                pass

        # Consolidated stepping state
        self._stepping_controller = SteppingController()

        # Consolidated thread and frame tracking
        self._thread_tracker = ThreadTracker()

        # Variable reference management
        self._var_manager = VariableManager()

        # Optional: adapter/launcher may store configured data breakpoints here
        # for simple bookkeeping. Not required for core BDB operation.
        self.data_breakpoints: list[dict[str, Any]] | None = None
        self.breakpoint_meta = {}

        # Consolidated data breakpoint state
        self._data_bp_state = DataBreakpointState()

    # --- Compatibility properties for stepping state ---
    @property
    def stepping(self) -> bool:
        """Whether the debugger is in stepping mode."""
        return self._stepping_controller.stepping

    @stepping.setter
    def stepping(self, value: bool) -> None:
        self._stepping_controller.stepping = value

    @property
    def stop_on_entry(self) -> bool:
        """Whether to stop at program entry."""
        return self._stepping_controller.stop_on_entry

    @stop_on_entry.setter
    def stop_on_entry(self, value: bool) -> None:
        self._stepping_controller.stop_on_entry = value

    @property
    def current_frame(self) -> Any:
        """The current frame we're stopped at."""
        return self._stepping_controller.current_frame

    @current_frame.setter
    def current_frame(self, value: Any) -> None:
        self._stepping_controller.current_frame = value

    # --- Compatibility properties for exception handling ---
    @property
    def exception_breakpoints_raised(self) -> bool:
        """Whether to break on any raised exception."""
        return self._exception_handler.config.break_on_raised

    @exception_breakpoints_raised.setter
    def exception_breakpoints_raised(self, value: bool) -> None:
        self._exception_handler.config.break_on_raised = value

    @property
    def exception_breakpoints_uncaught(self) -> bool:
        """Whether to break on uncaught exceptions."""
        return self._exception_handler.config.break_on_uncaught

    @exception_breakpoints_uncaught.setter
    def exception_breakpoints_uncaught(self, value: bool) -> None:
        self._exception_handler.config.break_on_uncaught = value

    @property
    def current_exception_info(self) -> dict[int, ExceptionInfo]:
        """Per-thread exception info storage."""
        return self._exception_handler.exception_info_by_thread

    @current_exception_info.setter
    def current_exception_info(self, value: dict[int, ExceptionInfo]) -> None:
        self._exception_handler.exception_info_by_thread = value

    # --- Compatibility properties for var_refs/next_var_ref ---
    @property
    def next_var_ref(self) -> int:
        """Next variable reference ID to allocate."""
        return self._var_manager.next_var_ref

    @next_var_ref.setter
    def next_var_ref(self, value: int) -> None:
        self._var_manager.next_var_ref = value

    @property
    def var_refs(self) -> dict[int, Any]:
        """Mapping of variable reference IDs to stored data."""
        return self._var_manager.var_refs

    @var_refs.setter
    def var_refs(self, value: dict[int, Any]) -> None:
        self._var_manager.var_refs = value

    # --- Compatibility properties for thread/frame tracking ---
    @property
    def threads(self) -> dict[int, str]:
        """Mapping of thread ID to thread name."""
        return self._thread_tracker.threads

    @threads.setter
    def threads(self, value: dict[int, str]) -> None:
        self._thread_tracker.threads = value

    @property
    def thread_ids(self) -> dict[int, int]:
        """Legacy thread ID mapping."""
        return self._thread_tracker.thread_ids

    @thread_ids.setter
    def thread_ids(self, value: dict[int, int]) -> None:
        self._thread_tracker.thread_ids = value

    @property
    def thread_count(self) -> int:
        """Thread counter."""
        return self._thread_tracker.thread_count

    @thread_count.setter
    def thread_count(self, value: int) -> None:
        self._thread_tracker.thread_count = value

    @property
    def stopped_thread_ids(self) -> set[int]:
        """Set of thread IDs that are currently stopped."""
        return self._thread_tracker.stopped_thread_ids

    @stopped_thread_ids.setter
    def stopped_thread_ids(self, value: set[int]) -> None:
        self._thread_tracker.stopped_thread_ids = value

    @property
    def frames_by_thread(self) -> dict[int, list[dict[str, Any]]]:
        """Mapping of thread ID to stack frames."""
        return self._thread_tracker.frames_by_thread

    @frames_by_thread.setter
    def frames_by_thread(self, value: dict[int, list[dict[str, Any]]]) -> None:
        self._thread_tracker.frames_by_thread = value

    @property
    def next_frame_id(self) -> int:
        """Next frame ID to allocate."""
        return self._thread_tracker.next_frame_id

    @next_frame_id.setter
    def next_frame_id(self, value: int) -> None:
        self._thread_tracker.next_frame_id = value

    @property
    def frame_id_to_frame(self) -> dict[int, Any]:
        """Mapping of frame ID to Python frame object."""
        return self._thread_tracker.frame_id_to_frame

    @frame_id_to_frame.setter
    def frame_id_to_frame(self, value: dict[int, Any]) -> None:
        self._thread_tracker.frame_id_to_frame = value

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

        Delegates to the VariableManager for unified variable object creation.
        """
        return self._var_manager.make_variable(
            name,
            value,
            max_string_length=max_string_length,
            data_bp_state=self._data_bp_state,
            frame=frame,
        )

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

        # Get and consume the stop reason from stepping controller
        reason = self._stepping_controller.consume_stop_state().value

        self._emit_stopped_event(frame, thread_id, reason)
        self.process_commands()
        self.set_continue()

    def user_exception(self, frame, exc_info):
        """Handle exception breakpoints using the exception handler."""
        if not self._exception_handler.should_break(frame):
            return

        thread_id = threading.get_ident()

        # Build and store exception info for the adapter
        exception_info = self._exception_handler.build_exception_info(exc_info, frame)
        self._exception_handler.store_exception_info(thread_id, exception_info)

        # Emit stopped event
        self.current_frame = frame
        self.stopped_thread_ids.add(thread_id)
        stack_frames = self._get_stack_frames(frame)
        self.frames_by_thread[thread_id] = stack_frames

        self.send_message(
            "stopped",
            threadId=thread_id,
            reason="exception",
            text=self._exception_handler.get_exception_text(exc_info),
            allThreadsStopped=True,
        )
        self.process_commands()
        try:
            self.set_continue()
        except Exception:
            pass

    def _get_stack_frames(self, frame):
        """Build stack frames for the given frame using the thread tracker."""
        return self._thread_tracker.build_stack_frames(frame)

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
