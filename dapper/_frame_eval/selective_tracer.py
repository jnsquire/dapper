"""Selective frame tracing system for Dapper frame evaluation.

This module provides intelligent frame tracing that only enables tracing
on frames that have breakpoints, dramatically improving debugging performance
by avoiding unnecessary trace function calls on frames without breakpoints.
"""

from __future__ import annotations

from collections import defaultdict
import dis
import threading
from typing import TYPE_CHECKING
from typing import Any
from typing import Callable
from typing import Literal
from typing import Protocol
from typing import TypedDict

from dapper._frame_eval.cache_manager import get_breakpoints
from dapper._frame_eval.cache_manager import invalidate_breakpoints
from dapper._frame_eval.cache_manager import set_breakpoints
from dapper._frame_eval.condition_evaluator import get_condition_evaluator


def _safe_int(value: object, default: int) -> int:
    """Return *value* when it is an int, otherwise use *default*."""
    return value if isinstance(value, int) else default


def _decision_should_trace(decision: Mapping[str, Any]) -> bool:
    """Support both modern and legacy trace-decision shapes."""
    path = decision.get("path")
    if path is not None:
        return path == "breakpointed"
    return bool(decision.get("should_trace", False))


class ThreadInfo(Protocol):
    """Protocol defining the interface for thread information objects."""

    inside_frame_eval: int
    fully_initialized: bool
    is_debugger_internal_thread: bool
    skip_all_frames: bool
    step_mode: bool

    def should_skip_frame(self, frame: FrameType) -> bool:
        """Determine if a frame should be skipped based on its filename."""
        ...


class FrameDebugInfo(TypedDict):
    """Type definition for basic frame debugging information."""

    filename: str
    function: str
    lineno: int
    is_module: bool


if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Mapping
    from types import CodeType
    from types import FrameType
else:
    try:
        from typing_extensions import TypedDict
    except ImportError:
        from typing import TypedDict


# Import frame evaluation state if available
try:
    from dapper._frame_eval._frame_evaluator import _state as _frame_eval_state
except ImportError:
    _frame_eval_state = None

    # Fallback implementation for when C extensions are not available
    class _FallbackThreadInfo:
        """Fallback implementation of ThreadInfo protocol."""

        inside_frame_eval: int = 0
        fully_initialized: bool = False
        is_debugger_internal_thread: bool = False
        skip_all_frames: bool = False
        step_mode: bool = False

        def should_skip_frame(self, frame: FrameType) -> bool:  # noqa: ARG002
            """Never skip frames in fallback mode.

            Args:
                frame: The frame to check (unused in fallback)

            """
            return False


def get_thread_info() -> ThreadInfo:
    """Get thread information, delegating to _state when available."""
    if _frame_eval_state is not None:
        return _frame_eval_state.get_thread_info()
    return _FallbackThreadInfo()


class TraceDecision(TypedDict):
    """TypedDict for trace decision results."""

    path: Literal["skip", "original", "breakpointed"]
    should_trace: bool
    reason: str
    breakpoint_lines: set[int]
    frame_info: FrameDebugInfo


class _ConditionalBreakpointSpecRequired(TypedDict):
    """Required keys for :class:`ConditionalBreakpointSpec`."""

    lineno: int


class ConditionalBreakpointSpec(_ConditionalBreakpointSpecRequired, total=False):
    """Specification for a breakpoint, optionally with a condition expression.

    Attributes:
        lineno: Line number of the breakpoint (required).
        condition: Optional Python expression.  When present the breakpoint
            only triggers when the expression evaluates to a truthy value in
            the frame's context.  ``None`` means unconditional.

    """

    condition: str | None


class FrameTraceAnalyzer:
    """Analyzes frames to determine if they should be traced.

    Uses multiple strategies to efficiently determine if a frame
    contains breakpoints and should be traced.
    """

    def __init__(self):
        self._analysis_cache = {}
        self._cache_lock = threading.RLock()
        # Maps filename -> {lineno -> condition expression}
        self._breakpoint_conditions: dict[str, dict[int, str]] = {}
        self._stats = {
            "total_frames": 0,
            "traced_frames": 0,
            "cache_hits": 0,
            "fast_path_hits": 0,
        }

    def _create_trace_decision(
        self,
        should_trace: bool,
        reason: str,
        frame_info: FrameDebugInfo,
        breakpoint_lines: set[int] | None = None,
        update_stats: bool = False,
        path: Literal["skip", "original", "breakpointed"] | None = None,
    ) -> TraceDecision:
        """Helper to create a TraceDecision with consistent defaults."""
        if update_stats and should_trace:
            self._stats["traced_frames"] += 1

        if path is None:
            path = "breakpointed" if should_trace else "original"

        return TraceDecision(
            path=path,
            should_trace=should_trace,
            reason=reason,
            breakpoint_lines=breakpoint_lines or set(),
            frame_info=frame_info,
        )

    def _check_skip_frame(self, frame: FrameType) -> TraceDecision | None:
        """Check if frame should be skipped based on thread info."""
        thread_info = get_thread_info()
        if hasattr(thread_info, "should_skip_frame") and thread_info.should_skip_frame(
            frame,
        ):
            return self._create_trace_decision(
                should_trace=False,
                reason="thread_skip_frame",
                frame_info=self._get_frame_info(frame),
                path="skip",
            )
        return None

    def _handle_no_breakpoints(self, filename: str, frame_info: FrameDebugInfo) -> TraceDecision:
        """Handle case when no breakpoints are found for a file."""
        if self._should_track_file(filename):
            return self._create_trace_decision(
                should_trace=False,
                reason="no_breakpoints_in_file",
                frame_info=frame_info,
                path="original",
            )
        return self._create_trace_decision(
            should_trace=False,
            reason="file_not_tracked",
            frame_info=frame_info,
            path="skip",
        )

    def _get_code_info(self, code_obj: CodeType, lineno: int) -> FrameDebugInfo:
        """Build frame-style debug info from a code object and line number."""
        return {
            "filename": code_obj.co_filename,
            "function": code_obj.co_name,
            "lineno": lineno,
            "is_module": code_obj.co_name == "<module>",
        }

    def _should_skip_code_location(
        self,
        code_obj: CodeType,
        *,
        frame: Any | None,
        allow_current_eval_frame: bool,
        frame_info: FrameDebugInfo,
    ) -> TraceDecision | None:
        """Apply shared thread-level skip rules for a code location."""
        thread_info = get_thread_info()

        if not allow_current_eval_frame and bool(getattr(thread_info, "inside_frame_eval", 0)):
            return self._create_trace_decision(
                should_trace=False,
                reason="inside_frame_eval",
                frame_info=frame_info,
                path="skip",
            )

        if not bool(getattr(thread_info, "fully_initialized", True)):
            return self._create_trace_decision(
                should_trace=False,
                reason="thread_not_initialized",
                frame_info=frame_info,
                path="skip",
            )

        if bool(getattr(thread_info, "is_debugger_internal_thread", False)):
            return self._create_trace_decision(
                should_trace=False,
                reason="debugger_internal_thread",
                frame_info=frame_info,
                path="skip",
            )

        if bool(getattr(thread_info, "skip_all_frames", False)):
            return self._create_trace_decision(
                should_trace=False,
                reason="thread_skip_frame",
                frame_info=frame_info,
                path="skip",
            )

        if frame is not None:
            skip_decision = self._check_skip_frame(frame)
            if skip_decision is not None:
                return skip_decision

        del code_obj
        return None

    def _get_code_breakpoints(
        self,
        code_obj: CodeType,
        file_breakpoints: set[int],
        frame: FrameType | None = None,
    ) -> set[int]:
        """Return tracked breakpoint lines that belong to *code_obj*."""
        try:
            code_lines = {line for _, _, line in code_obj.co_lines() if line is not None}
        except Exception:
            code_lines = set()

        if code_lines:
            return file_breakpoints.intersection(code_lines)

        default_start = getattr(frame, "f_lineno", 0) if frame is not None else 0
        func_start = _safe_int(getattr(code_obj, "co_firstlineno", None), default_start)
        func_end = self._estimate_function_end(frame) if frame is not None else func_start + 100
        return {line for line in file_breakpoints if func_start <= line <= func_end}

    def should_trace_code(
        self,
        code_obj: CodeType,
        lineno: int,
        frame: Any | None = None,
        *,
        allow_current_eval_frame: bool = False,
    ) -> TraceDecision:
        """Determine if a code object location should take the debugger path.

        This is the shared decision entry point used by both selective tracing
        and the eval-frame hook.
        """
        self._stats["total_frames"] += 1
        frame_info = self._get_code_info(code_obj, lineno)
        filename = frame_info["filename"]

        skip_decision = self._should_skip_code_location(
            code_obj,
            frame=frame,
            allow_current_eval_frame=allow_current_eval_frame,
            frame_info=frame_info,
        )
        if skip_decision is not None:
            decision = skip_decision
        else:
            file_breakpoints = get_breakpoints(filename)
            if file_breakpoints is None or not file_breakpoints:
                decision = self._handle_no_breakpoints(filename, frame_info)
            elif lineno in file_breakpoints:
                condition = self._breakpoint_conditions.get(filename, {}).get(lineno)
                if condition is not None and frame is None:
                    decision = self._create_trace_decision(
                        should_trace=True,
                        reason="conditional_breakpoint_pending",
                        frame_info=frame_info,
                        breakpoint_lines={lineno},
                        update_stats=True,
                        path="breakpointed",
                    )
                elif condition is not None:
                    result = get_condition_evaluator().evaluate(condition, frame)
                    if not result["passed"] and not result["fallback"]:
                        decision = self._create_trace_decision(
                            should_trace=False,
                            reason="condition_not_met",
                            frame_info=frame_info,
                            path="original",
                        )
                    else:
                        decision = self._create_trace_decision(
                            should_trace=True,
                            reason="breakpoint_on_line",
                            frame_info=frame_info,
                            breakpoint_lines={lineno},
                            update_stats=True,
                            path="breakpointed",
                        )
                else:
                    decision = self._create_trace_decision(
                        should_trace=True,
                        reason="breakpoint_on_line",
                        frame_info=frame_info,
                        breakpoint_lines={lineno},
                        update_stats=True,
                        path="breakpointed",
                    )
            else:
                func_breakpoints = self._get_code_breakpoints(code_obj, file_breakpoints, frame)
                if func_breakpoints and self._should_trace_function_for_step(frame):
                    decision = self._create_trace_decision(
                        should_trace=True,
                        reason="function_has_breakpoints",
                        frame_info=frame_info,
                        breakpoint_lines=func_breakpoints,
                        update_stats=True,
                        path="breakpointed",
                    )
                else:
                    decision = self._create_trace_decision(
                        should_trace=False,
                        reason="no_breakpoints_in_function",
                        frame_info=frame_info,
                        path="original",
                    )

        return decision

    def should_trace_frame(self, frame: FrameType) -> TraceDecision:
        """Determine if a frame should be traced based on breakpoints.

        Args:
            frame: The frame to analyze

        Returns:
            TraceDecision containing the decision and reasoning

        """
        return self.should_trace_code(
            frame.f_code,
            frame.f_lineno,
            frame=frame,
        )

    def _should_track_file(self, filename: str) -> bool:
        """Determine if a file should be tracked for breakpoints."""
        # Skip system and library files
        skip_patterns = [
            "<",
            "site-packages/",
            "python3.",
            "lib/python",
            "Python/Lib",
            "importlib",
            "dapper/_frame_eval/",
        ]

        for pattern in skip_patterns:
            if pattern in filename:
                return False

        # Track user code files
        return filename.endswith(".py")

    def _get_function_breakpoints(self, frame: FrameType, file_breakpoints: set[int]) -> set[int]:
        """Get breakpoints within the current function's line range."""
        try:
            code_obj = frame.f_code
            func_start = code_obj.co_firstlineno

            # Try to get function end line from disassembly or other means
            func_end = self._estimate_function_end(frame)

            # Find breakpoints within function range
            return {line for line in file_breakpoints if func_start <= line <= func_end}

        except Exception:
            return set()

    def _estimate_function_end(self, frame: FrameType) -> int:
        """Estimate the end line of a function."""
        default_start = _safe_int(getattr(frame, "f_lineno", None), 0)
        code_obj = getattr(frame, "f_code", None)
        fallback_end = _safe_int(getattr(code_obj, "co_firstlineno", None), default_start) + 100

        try:
            if code_obj is None:
                return fallback_end

            # Get all line numbers from the code object
            instructions = list(dis.get_instructions(code_obj))
            line_numbers: set[int] = set()

            for instr in instructions:
                # Handle different Python versions where lineno might be in different attributes
                line = getattr(instr, "starts_line", None) or getattr(instr, "lineno", None)
                if line is not None:
                    line_numbers.add(line)

            if not line_numbers:
                return fallback_end
            return max(line_numbers)
        except Exception:
            return fallback_end

    def _should_trace_function_for_step(self, _frame: FrameType | None) -> bool:
        """Determine if a function should be traced for step-over functionality."""
        thread_info = get_thread_info()

        # Only trace for step if we're actively debugging
        if not thread_info.fully_initialized:
            return False

        # Check if we're in step-over mode using getattr for safety
        return bool(getattr(thread_info, "step_mode", False))

    def _get_frame_info(self, frame: FrameType) -> FrameDebugInfo:
        """Extract basic frame information for debugging."""
        return {
            "filename": frame.f_code.co_filename,
            "function": frame.f_code.co_name,
            "lineno": frame.f_lineno,
            "is_module": frame.f_code.co_name == "<module>",
        }

    def update_breakpoints(self, filename: str, breakpoints: Iterable[int]) -> None:
        """Update breakpoint information for a file."""
        set_breakpoints(filename, breakpoints)

        # Invalidate any cached analysis for this file
        with self._cache_lock:
            keys_to_remove = [
                key for key in self._analysis_cache if key.startswith(f"{filename}:")
            ]
            for key in keys_to_remove:
                del self._analysis_cache[key]

    def set_breakpoint_conditions(self, filename: str, conditions: dict[int, str | None]) -> None:
        """Store condition expressions for breakpoints in *filename*.

        Args:
            filename: Absolute path of the source file.
            conditions: Mapping of line number → condition expression.  A
                value of ``None`` removes any existing condition for that line.

        """
        active = {ln: expr for ln, expr in conditions.items() if expr is not None}
        with self._cache_lock:
            if active:
                self._breakpoint_conditions[filename] = active
            else:
                self._breakpoint_conditions.pop(filename, None)

    def invalidate_file(self, filename: str) -> None:
        """Invalidate cached breakpoint information for a file."""
        invalidate_breakpoints(filename)

        # Clear analysis cache and conditions for this file
        with self._cache_lock:
            keys_to_remove = [
                key for key in self._analysis_cache if key.startswith(f"{filename}:")
            ]
            for key in keys_to_remove:
                del self._analysis_cache[key]
            self._breakpoint_conditions.pop(filename, None)

    def get_statistics(self) -> dict[str, Any]:
        """Get tracing statistics."""
        total = self._stats["total_frames"]
        traced = self._stats["traced_frames"]

        return {
            **self._stats,
            "trace_rate": traced / total if total > 0 else 0,
            "cache_size": len(self._analysis_cache),
        }

    def clear_statistics(self) -> None:
        """Clear tracing statistics."""
        self._stats = {
            "total_frames": 0,
            "traced_frames": 0,
            "cache_hits": 0,
            "fast_path_hits": 0,
        }


class SelectiveTraceDispatcher:
    """Dispatches trace functions only when necessary.

    Acts as a smart intermediary that decides whether to call
    the actual debugger trace function based on frame analysis.
    """

    def __init__(self, debugger_trace_func: Callable | None = None):
        self.debugger_trace_func = debugger_trace_func
        self.analyzer = FrameTraceAnalyzer()
        self._dispatch_stats = {
            "total_calls": 0,
            "dispatched_calls": 0,
            "skipped_calls": 0,
        }
        self._lock = threading.RLock()

    def set_debugger_trace_func(
        self,
        trace_func: Callable[[FrameType, str, Any], Callable | None] | None,
    ) -> None:
        """Set the actual debugger trace function."""
        with self._lock:
            self.debugger_trace_func = trace_func

    def selective_trace_dispatch(self, frame: FrameType, event: str, arg: Any) -> Callable | None:
        """Dispatch trace function only when frame should be traced.

        Args:
            frame: The current frame
            event: The trace event ('call', 'line', 'return', 'exception')
            arg: Event-specific argument

        Returns:
            Trace function or None if frame should not be traced

        """
        with self._lock:
            self._dispatch_stats["total_calls"] += 1
            trace_func = self.debugger_trace_func

        # Quick check for debugger availability
        if trace_func is None:
            return None

        # Handle None frame gracefully
        if frame is None:
            return None

        # Analyze frame to determine if tracing is needed
        decision = self.analyzer.should_trace_frame(frame)

        if not _decision_should_trace(decision):
            with self._lock:
                self._dispatch_stats["skipped_calls"] += 1
            return None

        # Frame should be traced, call the actual debugger.
        # Keep lock scope narrow: callback may be slow/user-controlled.
        with self._lock:
            self._dispatch_stats["dispatched_calls"] += 1
        return trace_func(frame, event, arg)

    def update_breakpoints(self, filename: str, breakpoints: Iterable[int]) -> None:
        """Update breakpoint information."""
        self.analyzer.update_breakpoints(filename, breakpoints)

    def invalidate_file(self, filename: str) -> None:
        """Invalidate cached information for a file."""
        self.analyzer.invalidate_file(filename)

    def get_statistics(self) -> dict[str, Any]:
        """Get comprehensive dispatch statistics."""
        analyzer_stats = self.analyzer.get_statistics()

        total = self._dispatch_stats["total_calls"]
        dispatched = self._dispatch_stats["dispatched_calls"]
        skipped = self._dispatch_stats["skipped_calls"]

        return {
            "dispatcher_stats": {
                **self._dispatch_stats,
                "dispatch_rate": dispatched / total if total > 0 else 0,
                "skip_rate": skipped / total if total > 0 else 0,
            },
            "analyzer_stats": analyzer_stats,
        }

    def clear_statistics(self) -> None:
        """Clear all statistics."""
        self._dispatch_stats = {
            "total_calls": 0,
            "dispatched_calls": 0,
            "skipped_calls": 0,
        }
        self.analyzer.clear_statistics()


class FrameTraceManager:
    """High-level manager for selective frame tracing.

    Coordinates between the frame evaluator, breakpoint manager,
    and trace dispatcher to provide optimal tracing performance.
    """

    def __init__(self):
        self.dispatcher = SelectiveTraceDispatcher()
        self._enabled = False
        self._lock = threading.RLock()
        self._global_breakpoints: dict[str, set[int]] = defaultdict(set)

    def enable_selective_tracing(self, debugger_trace_func: Callable) -> None:
        """Enable selective tracing with the given debugger trace function."""
        with self._lock:
            self.dispatcher.set_debugger_trace_func(debugger_trace_func)
            self._enabled = True

    def disable_selective_tracing(self) -> None:
        """Disable selective tracing."""
        with self._lock:
            self._enabled = False
            self.dispatcher.set_debugger_trace_func(None)

    def is_enabled(self) -> bool:
        """Check if selective tracing is enabled."""
        return self._enabled

    def get_trace_function(self) -> Callable | None:
        """Get the selective trace function for sys.settrace()."""
        if self._enabled:
            return self.dispatcher.selective_trace_dispatch
        return None

    def update_file_breakpoints(self, filename: str, breakpoints: set[int]) -> None:
        """Update breakpoints for a specific file."""
        with self._lock:
            self._global_breakpoints[filename] = set(breakpoints)
            self.dispatcher.update_breakpoints(filename, breakpoints)

    def set_conditional_breakpoints(
        self,
        filename: str,
        specs: list[ConditionalBreakpointSpec],
    ) -> None:
        """Set breakpoints with optional condition expressions for *filename*.

        Unconditional breakpoints (``condition=None``) are treated identically
        to plain breakpoints registered via :meth:`update_file_breakpoints`.
        Conditional ones additionally store the expression so the
        :class:`~dapper._frame_eval.condition_evaluator.ConditionEvaluator`
        can gate dispatch.

        Args:
            filename: Absolute path of the source file.
            specs: List of :class:`ConditionalBreakpointSpec` dicts, each
                containing at least a ``lineno`` key and optionally a
                ``condition`` key.

        """
        lines: set[int] = set()
        conditions: dict[int, str | None] = {}
        for spec in specs:
            lineno = spec["lineno"]
            lines.add(lineno)
            conditions[lineno] = spec.get("condition")

        with self._lock:
            self._global_breakpoints[filename] = lines
            self.dispatcher.update_breakpoints(filename, lines)
            self.dispatcher.analyzer.set_breakpoint_conditions(filename, conditions)

    def update_all_breakpoints(self, breakpoint_map: dict[str, set[int]]) -> None:
        """Update breakpoints for all files."""
        with self._lock:
            self._global_breakpoints.clear()
            self._global_breakpoints.update(breakpoint_map)

            for filename, breakpoints in breakpoint_map.items():
                self.dispatcher.update_breakpoints(filename, breakpoints)

    def add_breakpoint(self, filename: str, lineno: int) -> None:
        """Add a single breakpoint."""
        with self._lock:
            self._global_breakpoints[filename].add(lineno)
            self.dispatcher.update_breakpoints(filename, self._global_breakpoints[filename])

    def remove_breakpoint(self, filename: str, lineno: int) -> None:
        """Remove a single breakpoint."""
        with self._lock:
            self._global_breakpoints[filename].discard(lineno)
            self.dispatcher.update_breakpoints(filename, self._global_breakpoints[filename])

    def clear_breakpoints(self, filename: str | None = None) -> None:
        """Clear breakpoints, either for a specific file or all files."""
        with self._lock:
            if filename:
                self._global_breakpoints[filename].clear()
                self.dispatcher.update_breakpoints(filename, [])
            else:
                self._global_breakpoints.clear()
                for fname in list(self._global_breakpoints.keys()):
                    self.dispatcher.update_breakpoints(fname, [])

    def invalidate_file_cache(self, filename: str) -> None:
        """Invalidate cached information for a file."""
        self.dispatcher.invalidate_file(filename)

    def get_breakpoints(self, filename: str) -> set[int]:
        """Get current breakpoints for a file."""
        return self._global_breakpoints.get(filename, set()).copy()

    def get_all_breakpoints(self) -> dict[str, set[int]]:
        """Get all current breakpoints."""
        return {k: v.copy() for k, v in self._global_breakpoints.items()}

    def get_statistics(self) -> dict[str, Any]:
        """Get comprehensive tracing statistics."""
        return {
            "enabled": self._enabled,
            "total_files_with_breakpoints": len(self._global_breakpoints),
            "total_breakpoints": sum(len(bp) for bp in self._global_breakpoints.values()),
            "dispatcher_stats": self.dispatcher.get_statistics(),
        }

    def clear_statistics(self) -> None:
        """Clear all statistics."""
        self.dispatcher.clear_statistics()


# Global instance
_trace_manager = FrameTraceManager()


def get_trace_manager() -> FrameTraceManager:
    """Get the global trace manager instance."""
    return _trace_manager


def enable_selective_tracing(debugger_trace_func: Callable) -> None:
    """Enable selective frame tracing."""
    _trace_manager.enable_selective_tracing(debugger_trace_func)


def disable_selective_tracing() -> None:
    """Disable selective frame tracing."""
    _trace_manager.disable_selective_tracing()


def get_selective_trace_function() -> Callable | None:
    """Get the selective trace function for sys.settrace()."""
    return _trace_manager.get_trace_function()


def should_trace_code_location(
    code_obj: CodeType,
    lineno: int,
    frame: Any | None = None,
    *,
    allow_current_eval_frame: bool = False,
) -> TraceDecision:
    """Return the shared tracing decision for a code object location."""
    return _trace_manager.dispatcher.analyzer.should_trace_code(
        code_obj,
        lineno,
        frame=frame,
        allow_current_eval_frame=allow_current_eval_frame,
    )


def update_breakpoints(filename: str, breakpoints: set[int]) -> None:
    """Update breakpoints for a file."""
    _trace_manager.update_file_breakpoints(filename, breakpoints)


def add_breakpoint(filename: str, lineno: int) -> None:
    """Add a breakpoint."""
    _trace_manager.add_breakpoint(filename, lineno)


def remove_breakpoint(filename: str, lineno: int) -> None:
    """Remove a breakpoint."""
    _trace_manager.remove_breakpoint(filename, lineno)


def get_tracing_statistics() -> dict[str, Any]:
    """Get comprehensive tracing statistics."""
    return _trace_manager.get_statistics()
