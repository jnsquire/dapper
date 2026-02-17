# ruff: noqa: PLC0415
"""
DebuggerBDB class and related helpers for debug launcher.
"""

from __future__ import annotations

import bdb
from collections.abc import Mapping
import contextlib
import logging
import threading
from typing import TYPE_CHECKING
from typing import Any
from typing import Callable

from dapper.core.breakpoint_manager import BreakpointManager
from dapper.core.breakpoint_resolver import BreakpointResolver
from dapper.core.breakpoint_resolver import ResolveAction
from dapper.core.data_breakpoint_state import DataBreakpointState
from dapper.core.debug_utils import get_function_candidate_names
from dapper.core.exception_handler import ExceptionHandler
from dapper.core.stepping_controller import SteppingController
from dapper.core.thread_tracker import ThreadTracker
from dapper.core.variable_manager import VariableManager

if TYPE_CHECKING:
    import types

    from dapper.protocol.debugger_protocol import Variable as VariableDict
    from dapper.protocol.structures import StackFrame

try:
    from dapper._frame_eval.debugger_integration import integrate_debugger_bdb
except ImportError:  # pragma: no cover - optional integration
    integrate_debugger_bdb = None

logger = logging.getLogger(__name__)


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
        self.breakpoint_resolver = BreakpointResolver()

        # Centralized breakpoint state management
        self.bp_manager = BreakpointManager()

        self.is_terminated = False
        self.breakpoints = {}
        self.current_thread_id = threading.get_ident()

        if enable_frame_eval:
            try:
                # Dynamic import to avoid top-level cycles when frame eval is optional
                from dapper._frame_eval.debugger_integration import integrate_debugger_bdb

                integrate_debugger_bdb(self)
            except ImportError:
                pass

        # Consolidated stepping state
        self.stepping_controller = SteppingController()

        # Exception handling
        self.exception_handler = ExceptionHandler()

        # Consolidated thread and frame tracking
        self.thread_tracker = ThreadTracker()

        # Variable reference management
        self.var_manager = VariableManager()

        # Optional: adapter/launcher may store configured data breakpoints here
        # for simple bookkeeping. Not required for core BDB operation.
        self.data_breakpoints: list[dict[str, Any]] | None = None

        # Consolidated data breakpoint state
        self.data_bp_state = DataBreakpointState()

    # ---------------- Data Breakpoint (Watch) Support -----------------
    def register_data_watches(
        self, names: list[str], metas: list[tuple[str, dict]] | None = None
    ) -> None:
        """Replace the set of variable names to watch for changes.

        Optionally accepts metadata tuples (name, meta) mirroring adapter-side
        data breakpoint records containing 'condition' and 'hitCondition'.
        Multiple meta entries per variable name are stored in a list.
        """
        self.data_bp_state.register_watches(names, metas)

    def record_breakpoint(
        self,
        path: str,
        line: int,
        *,
        condition: str | None,
        hit_condition: str | None,
        log_message: str | None,
    ) -> None:
        """Record metadata for a line breakpoint.

        Delegates to BreakpointManager.record_line_breakpoint.
        """
        self.bp_manager.record_line_breakpoint(
            path,
            line,
            condition=condition,
            hit_condition=hit_condition,
            log_message=log_message,
        )

    def clear_break_meta_for_file(self, path: str) -> None:
        """Clear all breakpoint metadata for a file.

        Delegates to BreakpointManager.clear_line_meta_for_file.
        """
        self.bp_manager.clear_line_meta_for_file(path)

    def _check_data_watch_changes(self, frame: types.FrameType) -> list[str]:
        """Check for changes in watched variables and return list of changed names."""
        # Frame locals in CPython may be a FrameLocalsProxy; accept any
        # mapping-like object rather than requiring a plain dict.
        if not isinstance(frame.f_locals, Mapping):
            return []
        return self.data_bp_state.check_for_changes(id(frame), frame.f_locals)

    def _update_watch_snapshots(self, frame: types.FrameType) -> None:
        """Update snapshots of watched variable values."""
        if not isinstance(frame.f_locals, Mapping):
            return
        self.data_bp_state.update_snapshots(id(frame), frame.f_locals)

    # ---------------- Variable object helper -----------------
    def make_variable_object(
        self,
        name: Any,
        value: Any,
        frame: types.FrameType | None = None,
        *,
        max_string_length: int = 1000,
    ) -> VariableDict:
        """Create a Variable-shaped dict with presentationHint and optional var-ref allocation.

        Delegates to the VariableManager for unified variable object creation.
        """
        return self.var_manager.make_variable(
            name,
            value,
            max_string_length=max_string_length,
            data_bp_state=self.data_bp_state,
            frame=frame,
        )

    def _should_stop_for_data_breakpoint(self, changed_name: str, frame: types.FrameType) -> bool:
        """Evaluate conditions and hitConditions for a changed variable."""
        metas = (self.data_bp_state.watch_meta or {}).get(changed_name, [])

        # No metadata means default stop semantics
        if not metas:
            return True

        # Check each meta entry - stop if any passes all conditions
        for m in metas:
            result = self.breakpoint_resolver.resolve(m, frame)
            if result.action == ResolveAction.STOP:
                return True
            # For logpoints on data breakpoints, we still stop (data changed)
            # but the log message was already emitted by the resolver if emit_output was provided

        return False

    def _ensure_thread_registered(self, thread_id):
        """Ensure the current thread is registered and send thread started event if needed."""
        if thread_id not in self.thread_tracker.threads:
            thread_name = threading.current_thread().name
            self.thread_tracker.threads[thread_id] = thread_name
            self.send_message(
                "thread",
                threadId=thread_id,
                reason="started",
                name=thread_name,
            )

    def _handle_regular_breakpoint(self, filename: str, line: int, frame: types.FrameType) -> bool:
        """Handle regular line breakpoints with hit conditions and log messages.
        Returns True if the breakpoint was handled (either hit or skipped due to conditions),
        False if no breakpoint exists at this location.
        """
        canonical_filename = self.canonic(filename)
        has_line_in_break_table = False
        with contextlib.suppress(Exception):
            has_line_in_break_table = int(line) in [
                int(ln) for ln in self.breaks.get(filename, []) if ln is not None  # type: ignore[attr-defined]
            ] or int(line) in [
                int(ln)
                for ln in self.breaks.get(canonical_filename, [])  # type: ignore[attr-defined]
                if ln is not None
            ]

        if not (
            self.get_break(filename, line)
            or has_line_in_break_table
            or (filename in self.bp_manager.custom and line in self.bp_manager.custom[filename])
            or (
                canonical_filename in self.bp_manager.custom
                and line in self.bp_manager.custom[canonical_filename]
            )
        ):
            return False

        meta = self.bp_manager.line_meta.get((filename, int(line)))

        # Create an output emitter that sends to the debug client
        def emit_output(category: str, output: str) -> None:
            self.send_message("output", category=category, output=output)

        result = self.breakpoint_resolver.resolve(meta, frame, emit_output=emit_output)

        if result.action == ResolveAction.CONTINUE:
            # Condition not met or logpoint emitted - continue execution
            self.set_continue()
            return True

        # STOP action means conditions passed - stop with "breakpoint" reason
        thread_id = threading.get_ident()
        self._ensure_thread_registered(thread_id)
        self._emit_stopped_event(frame, thread_id, "breakpoint")
        self.process_commands()
        self.set_continue()
        return True

    def _emit_stopped_event(
        self, frame: types.FrameType, thread_id: int, reason: str, description: str | None = None
    ) -> None:
        """Emit a stopped event with proper bookkeeping."""
        self.stepping_controller.current_frame = frame
        self.thread_tracker.stopped_thread_ids.add(thread_id)
        stack_frames: list[StackFrame] = self._get_stack_frames(frame)
        self.thread_tracker.frames_by_thread[thread_id] = stack_frames

        event_args = {
            "threadId": thread_id,
            "reason": reason,
            "allThreadsStopped": True,
        }
        if description:
            event_args["description"] = description

        self.send_message("stopped", **event_args)

    def user_line(self, frame: types.FrameType) -> None:
        filename = frame.f_code.co_filename
        line = frame.f_lineno
        thread_id = threading.get_ident()

        self.botframe = frame  # to satisfy bdb expectations

        # Check for data watch changes first
        changed_names = self._check_data_watch_changes(frame)
        self._update_watch_snapshots(frame)

        if changed_names:
            for changed_name in changed_names:
                if self._should_stop_for_data_breakpoint(changed_name, frame):
                    self._ensure_thread_registered(thread_id)
                    self._emit_stopped_event(
                        frame, thread_id, "data breakpoint", f"{changed_name} changed"
                    )
            if changed_names:
                return

        # Handle regular breakpoints
        if self._handle_regular_breakpoint(filename, line, frame):
            return

        # Default stop behavior for stepping, entry, or normal breakpoints
        self._ensure_thread_registered(thread_id)

        # Get and consume the stop reason from stepping controller
        reason = self.stepping_controller.consume_stop_state().value

        self._emit_stopped_event(frame, thread_id, reason)
        self.process_commands()
        self.thread_tracker.clear_frames()
        self.set_continue()

    def user_exception(
        self,
        frame: types.FrameType,
        exc_info: tuple[type[BaseException], BaseException, types.TracebackType | None],
    ) -> None:
        """Handle exception breakpoints using the exception handler."""
        if not self.exception_handler.should_break(frame):
            return

        thread_id = threading.get_ident()

        # Build and store exception info for the adapter
        exception_info = self.exception_handler.build_exception_info(exc_info, frame)
        self.exception_handler.store_exception_info(thread_id, exception_info)

        # Emit stopped event
        self.stepping_controller.current_frame = frame
        self.thread_tracker.stopped_thread_ids.add(thread_id)
        stack_frames: list[StackFrame] = self._get_stack_frames(frame)
        self.thread_tracker.frames_by_thread[thread_id] = stack_frames

        self.send_message(
            "stopped",
            threadId=thread_id,
            reason="exception",
            text=self.exception_handler.get_exception_text(exc_info),
            allThreadsStopped=True,
        )
        self.process_commands()
        try:
            self.set_continue()
        except Exception:
            logger.debug("set_continue failed after exception stop", exc_info=True)

    def _get_stack_frames(self, frame: types.FrameType) -> list[StackFrame]:
        """Build stack frames for the given frame using the thread tracker."""
        return self.thread_tracker.build_stack_frames(frame)

    def set_custom_breakpoint(
        self, filename: str, line: int, condition: str | None = None
    ) -> None:
        custom = self.bp_manager.custom
        if filename not in custom:
            custom[filename] = {}
        custom[filename][line] = condition
        self.set_break(filename, line, cond=condition)

    def clear_custom_breakpoint(self, filename: str, line: int) -> None:
        custom = self.bp_manager.custom
        if filename in custom and line in custom[filename]:
            del custom[filename][line]
            self.clear_break(filename, line)

    def clear_all_custom_breakpoints(self):
        self.bp_manager.custom.clear()

    def clear_all_function_breakpoints(self):
        self.bp_manager.function_names = []
        self.bp_manager.function_meta.clear()

    # ---------------- Breakpoint housekeeping helpers -----------------
    def clear_breaks_for_file(self, path: str) -> None:
        """Clear all standard breakpoints for a given file and related metadata.

        Iterates bdb's internal break table and clears every breakpoint for
        the specified filename. Also clears adapter-side breakpoint metadata
        for that file.
        """
        canonical_path = self.canonic(path)

        def _clear_for_key(key: str) -> None:
            try:
                # bdb maintains a mapping filename -> list[int] of line numbers
                lines = list(self.breaks.get(key, []))  # type: ignore[attr-defined]
            except Exception:
                lines = []
            for ln in lines:
                if ln is None:
                    continue
                try:
                    iln = int(ln)
                except Exception:
                    continue
                with contextlib.suppress(Exception):
                    self.clear_break(key, iln)

        _clear_for_key(path)
        if canonical_path != path:
            _clear_for_key(canonical_path)

        with contextlib.suppress(Exception):
            self.clear_all_file_breaks(path)
        with contextlib.suppress(Exception):
            self.clear_all_file_breaks(canonical_path)
        # Clear DAP-specific metadata for this file, if any
        try:
            self.clear_break_meta_for_file(path)
        except Exception:
            logger.debug("Failed to clear breakpoint metadata for %s", path, exc_info=True)

    def user_call(self, frame: types.FrameType, argument_list: Any) -> None:
        """Handle function breakpoints.

        Checks if the current function call matches any registered function
        breakpoints and evaluates conditions/hit counts/log messages.
        """
        # Reference argument_list to avoid static analyzers reporting it as unused
        _ = argument_list

        if not self.bp_manager.function_names and not self.bp_manager.function_meta:
            return

        candidates = get_function_candidate_names(frame)
        match_name = None
        for name in self.bp_manager.function_names:
            if name in candidates:
                match_name = name
                break
        if match_name is None:
            return

        meta = self.bp_manager.function_meta.get(match_name, {})

        # Create an output emitter for logpoints
        def emit_output(category: str, output: str) -> None:
            self.send_message("output", category=category, output=output)

        result = self.breakpoint_resolver.resolve(meta, frame, emit_output=emit_output)

        if result.action != ResolveAction.STOP:
            # Condition not met or logpoint emitted - continue without stopping
            return

        # Stop at the function breakpoint
        thread_id = threading.get_ident()
        self._ensure_thread_registered(thread_id)
        self._emit_stopped_event(frame, thread_id, "function breakpoint")
        self.process_commands()
        self.set_continue()
