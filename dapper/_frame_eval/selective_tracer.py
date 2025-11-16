"""
Selective frame tracing system for Dapper frame evaluation.

This module provides intelligent frame tracing that only enables tracing
on frames that have breakpoints, dramatically improving debugging performance
by avoiding unnecessary trace function calls on frames without breakpoints.
"""

from __future__ import annotations

import dis
import threading
from collections import defaultdict
from typing import TYPE_CHECKING
from typing import Any
from typing import Callable
from typing import Protocol
from typing import TypedDict

from dapper._frame_eval.cache_manager import get_breakpoints
from dapper._frame_eval.cache_manager import invalidate_breakpoints
from dapper._frame_eval.cache_manager import set_breakpoints


class ThreadInfo(Protocol):
    """Protocol defining the interface for thread information objects."""

    fully_initialized: bool
    step_mode: bool

    def should_skip_frame(self, filename: str) -> bool:
        """Determine if a frame should be skipped based on its filename."""
        ...


if TYPE_CHECKING:
    from types import FrameType
else:
    try:
        from typing_extensions import TypedDict
    except ImportError:
        from typing import TypedDict


# Import frame evaluation functions if available
try:
    from dapper._frame_eval._frame_evaluator import (
        get_thread_info,  # type: ignore[import-not-found]
    )
except ImportError:
    # Fallback implementation for when C extensions are not available
    class _FallbackThreadInfo:
        """Fallback implementation of ThreadInfo protocol."""

        fully_initialized: bool = False
        step_mode: bool = False

        def should_skip_frame(self, _filename: str) -> bool:
            """Never skip frames in fallback mode.

            Args:
                _filename: The filename to check (unused in fallback)
            """
            return False

    def get_thread_info() -> _FallbackThreadInfo:
        """Get thread information with fallback implementation."""
        return _FallbackThreadInfo()


class TraceDecision(TypedDict):
    """TypedDict for trace decision results."""

    should_trace: bool
    reason: str
    breakpoint_lines: set[int]
    frame_info: dict[str, Any]


class FrameTraceAnalyzer:
    """
    Analyzes frames to determine if they should be traced.

    Uses multiple strategies to efficiently determine if a frame
    contains breakpoints and should be traced.
    """

    def __init__(self):
        self._analysis_cache = {}
        self._cache_lock = threading.RLock()
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
        frame_info: dict[str, Any],
        breakpoint_lines: set[int] | None = None,
        update_stats: bool = False,
    ) -> TraceDecision:
        """Helper to create a TraceDecision with consistent defaults."""
        if update_stats and should_trace:
            self._stats["traced_frames"] += 1

        return TraceDecision(
            should_trace=should_trace,
            reason=reason,
            breakpoint_lines=breakpoint_lines or set(),
            frame_info=frame_info,
        )

    def _check_skip_frame(self, frame: FrameType) -> TraceDecision | None:
        """Check if frame should be skipped based on thread info."""
        thread_info = get_thread_info()
        if hasattr(thread_info, "should_skip_frame") and thread_info.should_skip_frame(
            frame.f_code.co_filename
        ):
            return self._create_trace_decision(
                should_trace=False,
                reason="thread_skip_frame",
                frame_info=self._get_frame_info(frame),
            )
        return None

    def _handle_no_breakpoints(self, filename: str, frame_info: dict[str, Any]) -> TraceDecision:
        """Handle case when no breakpoints are found for a file."""
        if self._should_track_file(filename):
            return self._create_trace_decision(
                should_trace=False, reason="no_breakpoints_in_file", frame_info=frame_info
            )
        return self._create_trace_decision(
            should_trace=False, reason="file_not_tracked", frame_info=frame_info
        )

    def should_trace_frame(self, frame: FrameType) -> TraceDecision:
        """
        Determine if a frame should be traced based on breakpoints.

        Args:
            frame: The frame to analyze

        Returns:
            TraceDecision containing the decision and reasoning
        """
        self._stats["total_frames"] += 1
        frame_info = self._get_frame_info(frame)
        filename = frame_info["filename"]
        lineno = frame_info["lineno"]

        # Check if frame should be skipped
        skip_decision = self._check_skip_frame(frame)
        if skip_decision is not None:
            return skip_decision

        # Get breakpoints for the file
        file_breakpoints = get_breakpoints(filename)

        # Handle cases with no breakpoints or no file tracking
        if file_breakpoints is None or not file_breakpoints:
            return self._handle_no_breakpoints(filename, frame_info)

        # Check for breakpoint on current line
        if lineno in file_breakpoints:
            return self._create_trace_decision(
                should_trace=True,
                reason="breakpoint_on_line",
                frame_info=frame_info,
                breakpoint_lines={lineno},
                update_stats=True,
            )

        # Check for function breakpoints that might need tracing
        func_breakpoints = self._get_function_breakpoints(frame, file_breakpoints)
        if func_breakpoints and self._should_trace_function_for_step(frame):
            return self._create_trace_decision(
                should_trace=True,
                reason="function_has_breakpoints",
                frame_info=frame_info,
                breakpoint_lines=func_breakpoints,
                update_stats=True,
            )

        # Default case: no tracing needed
        return self._create_trace_decision(
            should_trace=False, reason="no_breakpoints_in_function", frame_info=frame_info
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
        try:
            # Get all line numbers from the code object
            instructions = list(dis.get_instructions(frame.f_code))
            line_numbers: set[int] = set()

            for instr in instructions:
                # Handle different Python versions where lineno might be in different attributes
                line = getattr(instr, "starts_line", None) or getattr(instr, "lineno", None)
                if line is not None:
                    line_numbers.add(line)

            if not line_numbers:
                return frame.f_code.co_firstlineno + 100  # Fallback estimate
            return max(line_numbers)
        except Exception:
            return frame.f_code.co_firstlineno + 100  # Fallback estimate

    def _should_trace_function_for_step(self, _frame: FrameType) -> bool:
        """Determine if a function should be traced for step-over functionality."""
        thread_info = get_thread_info()

        # Only trace for step if we're actively debugging
        if not thread_info.fully_initialized:
            return False

        # Check if we're in step-over mode using getattr for safety
        return bool(getattr(thread_info, "step_mode", False))

    def _get_frame_info(self, frame: FrameType) -> dict[str, Any]:
        """Extract basic frame information for debugging."""
        return {
            "filename": frame.f_code.co_filename,
            "function": frame.f_code.co_name,
            "lineno": frame.f_lineno,
            "is_module": frame.f_code.co_name == "<module>",
        }

    def update_breakpoints(self, filename: str, breakpoints: set[int]) -> None:
        """Update breakpoint information for a file."""
        set_breakpoints(filename, breakpoints)

        # Invalidate any cached analysis for this file
        with self._cache_lock:
            keys_to_remove = [
                key for key in self._analysis_cache if key.startswith(f"{filename}:")
            ]
            for key in keys_to_remove:
                del self._analysis_cache[key]

    def invalidate_file(self, filename: str) -> None:
        """Invalidate cached breakpoint information for a file."""
        invalidate_breakpoints(filename)

        # Clear analysis cache for this file
        with self._cache_lock:
            keys_to_remove = [
                key for key in self._analysis_cache if key.startswith(f"{filename}:")
            ]
            for key in keys_to_remove:
                del self._analysis_cache[key]

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
    """
    Dispatches trace functions only when necessary.

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
        self, trace_func: Callable[[FrameType, str, Any], Callable | None] | None
    ) -> None:
        """Set the actual debugger trace function."""
        with self._lock:
            self.debugger_trace_func = trace_func

    def selective_trace_dispatch(self, frame: FrameType, event: str, arg: Any) -> Callable | None:
        """
        Dispatch trace function only when frame should be traced.

        Args:
            frame: The current frame
            event: The trace event ('call', 'line', 'return', 'exception')
            arg: Event-specific argument

        Returns:
            Trace function or None if frame should not be traced
        """
        with self._lock:
            self._dispatch_stats["total_calls"] += 1

            # Quick check for debugger availability
            if self.debugger_trace_func is None:
                return None

            # Handle None frame gracefully
            if frame is None:
                return None

            # Analyze frame to determine if tracing is needed
            decision = self.analyzer.should_trace_frame(frame)

            if not decision["should_trace"]:
                self._dispatch_stats["skipped_calls"] += 1
                return None

            # Frame should be traced, call the actual debugger
            self._dispatch_stats["dispatched_calls"] += 1
            return self.debugger_trace_func(frame, event, arg)

    def update_breakpoints(self, filename: str, breakpoints: set[int]) -> None:
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
    """
    High-level manager for selective frame tracing.

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
                self.dispatcher.update_breakpoints(filename, set())
            else:
                self._global_breakpoints.clear()
                for fname in list(self._global_breakpoints.keys()):
                    self.dispatcher.update_breakpoints(fname, set())

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
