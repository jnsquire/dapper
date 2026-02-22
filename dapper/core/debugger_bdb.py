# ruff: noqa: PLC0415
"""DebuggerBDB class and related helpers for debug launcher."""

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
from dapper.core.just_my_code import is_user_frame
from dapper.core.just_my_code import is_user_path
from dapper.core.stepping_controller import StepGranularity
from dapper.core.stepping_controller import SteppingController
from dapper.core.thread_tracker import ThreadTracker
from dapper.core.variable_manager import VariableManager
from dapper.shared.runtime_source_registry import annotate_stack_frames_with_source_refs

if TYPE_CHECKING:
    import types

    from dapper.protocol.debugger_protocol import Variable as VariableDict
    from dapper.protocol.requests import GotoTarget
    from dapper.protocol.structures import StackFrame

try:
    from dapper._frame_eval.debugger_integration import integrate_debugger_bdb
except ImportError:  # pragma: no cover - optional integration
    integrate_debugger_bdb = None

logger = logging.getLogger(__name__)

# Filename substrings that identify asyncio / event-loop internal frames.
# Normalise to forward slashes so the check works identically on Windows and
# POSIX without importing `os` at module level for this one purpose.
_EVENT_LOOP_PATH_MARKERS = ("/asyncio/", "/concurrent/futures/")


def _is_event_loop_frame(frame: types.FrameType) -> bool:
    """Return True if *frame* is inside asyncio or concurrent.futures internals."""
    filename = frame.f_code.co_filename.replace("\\", "/")
    return any(marker in filename for marker in _EVENT_LOOP_PATH_MARKERS)


def _annotate_library_frames(stack_frames: list) -> None:
    """Mark non-user-code frames with ``presentationHint: "subtle"``.

    Mutates *stack_frames* in-place so that DAP clients can dim library frames
    when ``justMyCode`` is enabled.  Frames without a ``source.path`` are left
    unchanged (they are typically synthetic / already annotated).
    """
    for sf in stack_frames:
        path: str = (sf.get("source") or {}).get("path", "")
        if path and not is_user_path(path):
            sf["presentationHint"] = "subtle"


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
        just_my_code: bool = True,
        strict_expression_watch_policy: bool = False,
    ):
        super().__init__(skip)
        # Use injected callbacks or fall back to no-ops
        self.send_message = send_message
        self.process_commands = process_commands

        # When True, skip library / stdlib frames during stepping and mark them
        # as subtle in stack traces (debugpy-compatible ``justMyCode`` semantics).
        self.just_my_code = just_my_code

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
        self.data_bp_state.set_strict_expression_watch_policy(strict_expression_watch_policy)

    # ---------------- Data Breakpoint (Watch) Support -----------------
    def register_data_watches(
        self,
        names: list[str],
        metas: list[tuple[str, dict]] | None = None,
        expressions: list[str] | None = None,
        expression_metas: list[tuple[str, dict]] | None = None,
    ) -> None:
        """Replace the set of variable names to watch for changes.

        Optionally accepts metadata tuples (name, meta) mirroring adapter-side
        data breakpoint records containing 'condition' and 'hitCondition'.
        Multiple meta entries per variable name are stored in a list.
        """
        self.data_bp_state.register_watches(names, metas)
        self.data_bp_state.register_expression_watches(expressions or [], expression_metas)
        monitoring_backend = getattr(self, "_sys_monitoring_backend", None)
        sync = getattr(monitoring_backend, "sync_read_watchpoints", None)
        if callable(sync):
            sync()

    def goto_targets(self, frame_id: int, line: int) -> list[GotoTarget]:
        """Resolve goto targets for a frame/line pair.

        Current implementation exposes a single line-level target when the
        frame is known and line is positive.
        """
        frame = self.thread_tracker.get_frame(int(frame_id))
        if frame is None:
            return []
        try:
            target_line = int(line)
        except Exception:
            return []
        if target_line <= 0:
            return []
        target: GotoTarget = {
            "id": target_line,
            "label": f"Line {target_line}",
            "line": target_line,
        }
        return [target]

    def _resolve_top_frame_for_thread(self, thread_id: int) -> types.FrameType | None:
        """Resolve the top frame for a stopped thread id."""
        stack = self.thread_tracker.frames_by_thread.get(thread_id) or []
        if not stack:
            return None
        top = stack[0]
        if not isinstance(top, dict):
            return None
        frame_id = top.get("id")
        if not isinstance(frame_id, int):
            return None
        frame = self.thread_tracker.get_frame(frame_id)
        return frame if frame is not None else None

    def goto(self, thread_id: int, target_id: int) -> None:
        """Jump a stopped thread to a target line via frame.f_lineno."""
        frame = self._resolve_top_frame_for_thread(int(thread_id))
        if frame is None:
            msg = f"No stopped frame found for thread {thread_id}"
            raise ValueError(msg)

        target_line = int(target_id)
        if target_line <= 0:
            msg = f"Invalid target line {target_line}"
            raise ValueError(msg)

        try:
            frame_any: Any = frame
            frame_any.f_lineno = target_line
        except Exception as exc:
            msg = f"Cannot jump to line {target_line}: {exc!s}"
            raise ValueError(msg) from exc

        self._ensure_thread_registered(int(thread_id))
        self._emit_stopped_event(
            frame,
            int(thread_id),
            "goto",
            f"Jumped to line {target_line}",
        )

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

    def _check_expression_watch_changes(self, frame: types.FrameType) -> list[str]:
        """Check for changes in watched expressions and return changed expressions."""
        return self.data_bp_state.check_expression_changes(id(frame), frame)

    def _update_watch_snapshots(self, frame: types.FrameType) -> None:
        """Update snapshots of watched variable values."""
        if not isinstance(frame.f_locals, Mapping):
            return
        self.data_bp_state.update_snapshots(id(frame), frame.f_locals)
        self.data_bp_state.update_expression_snapshots(id(frame), frame)

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

    def _meta_matches_access_type(self, meta: dict[str, Any], access_type: str) -> bool:
        """Return whether breakpoint metadata applies to the requested access mode."""
        mode = str(meta.get("accessType", "write") or "write").strip().lower()
        if mode in {"readwrite", "read_write", "read-write"}:
            return True
        if access_type == "read":
            return mode == "read"
        return mode == "write"

    def _should_stop_for_data_breakpoint(
        self,
        changed_name: str,
        frame: types.FrameType,
        *,
        access_type: str = "write",
    ) -> bool:
        """Evaluate conditions and hitConditions for a changed variable."""
        metas = (self.data_bp_state.watch_meta or {}).get(changed_name, [])

        # No metadata means default stop semantics
        if not metas:
            return True

        # Check each meta entry - stop if any passes all conditions
        for m in metas:
            if not self._meta_matches_access_type(m, access_type):
                continue
            result = self.breakpoint_resolver.resolve(m, frame)
            if result.action == ResolveAction.STOP:
                return True
            # For logpoints on data breakpoints, we still stop (data changed)
            # but the log message was already emitted by the resolver if emit_output was provided

        return False

    def handle_read_watch_access(self, name: str, frame: types.FrameType) -> bool:
        """Handle a read-access watchpoint hit from a monitoring backend callback."""
        if not self.data_bp_state.is_read_watching(name):
            return False
        if not self._should_stop_for_data_breakpoint(name, frame, access_type="read"):
            return False

        thread_id = threading.get_ident()
        self._ensure_thread_registered(thread_id)
        self._emit_stopped_event(
            frame,
            thread_id,
            "data breakpoint",
            f"{name} read",
        )
        return True

    def _should_stop_for_expression_breakpoint(
        self,
        changed_expression: str,
        frame: types.FrameType,
    ) -> bool:
        """Evaluate conditions and hitConditions for a changed watched expression."""
        metas = (self.data_bp_state.watch_expression_meta or {}).get(changed_expression, [])

        if not metas:
            return True

        for m in metas:
            result = self.breakpoint_resolver.resolve(m, frame)
            if result.action == ResolveAction.STOP:
                return True

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
                int(ln)
                for ln in self.breaks.get(filename, [])
                if ln is not None  # type: ignore[attr-defined]
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
        self,
        frame: types.FrameType,
        thread_id: int,
        reason: str,
        description: str | None = None,
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
        # Async-aware stepping: when we're stepping over/into an await expression
        # the event loop resumes before the user coroutine does.  Skip any
        # internal asyncio / concurrent.futures frames so the debugger stops at
        # the next line of *user* code instead of inside the event loop.
        if self.stepping_controller.async_step_over and _is_event_loop_frame(frame):
            self.set_continue()
            return

        # Just My Code: when enabled and the frame is library / stdlib code,
        # keep stepping without stopping.  Explicit breakpoints set inside
        # library code are still honoured (checked later via _handle_regular_breakpoint).
        if self.just_my_code and not is_user_frame(frame):
            filename = frame.f_code.co_filename
            line = frame.f_lineno
            canonical = self.canonic(filename)
            # Only honour an explicit breakpoint; otherwise transparently skip.
            has_explicit_bp = bool(
                self.get_break(filename, line)
                or self.get_break(canonical, line)
                or (
                    filename in self.bp_manager.custom and line in self.bp_manager.custom[filename]
                ),
            )
            if not has_explicit_bp:
                self.set_step()
                return

        # Arriving at user code — clear the flag so subsequent steps are
        # unaffected regardless of whether the frame is a coroutine.
        self.stepping_controller.async_step_over = False

        filename = frame.f_code.co_filename
        line = frame.f_lineno
        thread_id = threading.get_ident()

        self.botframe = frame  # to satisfy bdb expectations

        # Check for data watch changes first
        changed_names = self._check_data_watch_changes(frame)
        changed_expressions = self._check_expression_watch_changes(frame)
        self._update_watch_snapshots(frame)

        if changed_names or changed_expressions:
            for changed_name in changed_names:
                if self._should_stop_for_data_breakpoint(changed_name, frame):
                    self._ensure_thread_registered(thread_id)
                    self._emit_stopped_event(
                        frame,
                        thread_id,
                        "data breakpoint",
                        f"{changed_name} changed",
                    )
            for changed_expression in changed_expressions:
                if self._should_stop_for_expression_breakpoint(changed_expression, frame):
                    self._ensure_thread_registered(thread_id)
                    self._emit_stopped_event(
                        frame,
                        thread_id,
                        "data breakpoint",
                        f"{changed_expression} changed",
                    )
            if changed_names or changed_expressions:
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

    def user_opcode(self, frame: types.FrameType) -> None:
        """Stop at each bytecode instruction during instruction-level stepping.

        Called by ``bdb.Bdb.dispatch_opcode`` when ``frame.f_trace_opcodes``
        is ``True`` and the debugger is handling an ``opcode`` trace event.
        Only stops when ``stepping_controller.granularity`` is
        :attr:`~dapper.core.stepping_controller.StepGranularity.INSTRUCTION`
        and a step is in progress; otherwise returns immediately.
        """
        if not self.stepping_controller.stepping:
            return
        if self.stepping_controller.granularity is not StepGranularity.INSTRUCTION:
            return

        # Respect async step-over: skip event-loop frames.
        if self.stepping_controller.async_step_over and _is_event_loop_frame(frame):
            return

        self.stepping_controller.async_step_over = False

        # Required by bdb.set_continue() to locate the bottom frame.
        self.botframe = frame

        thread_id = threading.get_ident()
        self._ensure_thread_registered(thread_id)

        # Get and consume stop reason (clears stepping flag).
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
        stack_frames = self.thread_tracker.build_stack_frames(frame)
        annotate_stack_frames_with_source_refs(stack_frames)  # type: ignore[arg-type]
        if self.just_my_code:
            _annotate_library_frames(stack_frames)
        return stack_frames

    def set_custom_breakpoint(
        self,
        filename: str,
        line: int,
        condition: str | None = None,
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
