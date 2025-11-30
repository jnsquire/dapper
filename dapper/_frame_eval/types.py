"""
Type definitions for the frame evaluator API.

This module provides type hints for the Cython-accelerated frame evaluator.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING or sys.version_info < (3, 8):
    pass
else:
    pass

if TYPE_CHECKING:
    from types import CodeType
    from types import FrameType

# Type aliases
FrameStats = dict[str, Any]
BreakpointLines = set[int]


class ThreadInfo:
    """Thread-local debugging information for frame evaluation."""

    inside_frame_eval: int
    fully_initialized: bool
    is_pydevd_thread: bool
    thread_trace_func: Any | None  # Callable[[FrameType, str, Any], Any] | None
    additional_info: Any | None
    recursion_depth: int
    skip_all_frames: bool

    def __init__(self) -> None: ...
    def enter_frame_eval(self) -> None: ...
    def exit_frame_eval(self) -> None: ...
    def should_skip_frame(self, frame: FrameType) -> bool: ...


class FuncCodeInfo:
    """Code object breakpoint information with caching."""

    co_filename: bytes
    real_path: str
    always_skip_code: bool
    breakpoint_found: bool
    new_code: CodeType | None
    breakpoints_mtime: float
    breakpoint_lines: BreakpointLines
    last_check_time: float
    is_valid: bool

    def __init__(self) -> None: ...
    def update_breakpoint_info(self, code_obj: CodeType) -> None: ...


# Public API function type hints
def get_thread_info() -> ThreadInfo: ...


def get_func_code_info(frame_obj: FrameType, code_obj: CodeType) -> FuncCodeInfo: ...


def frame_eval_func() -> None:
    """Enable frame evaluation by setting the eval_frame hook."""


def stop_frame_eval() -> None:
    """Disable frame evaluation by restoring the default eval_frame hook."""


def clear_thread_local_info() -> None:
    """Clear thread-local debugging information."""


def get_frame_eval_stats() -> dict[str, int | float | bool]:
    """Get statistics about frame evaluation performance.

    Returns:
        A dictionary containing frame evaluation statistics with the following keys:
        - 'frames_evaluated': Number of frames evaluated
        - 'cache_hits': Number of cache hits
        - 'cache_misses': Number of cache misses
        - 'evaluation_time': Total time spent in frame evaluation (in seconds)
        - 'is_active': Whether frame evaluation is currently active
    """
    return {
        "frames_evaluated": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "evaluation_time": 0.0,
        "is_active": False,
    }


def mark_thread_as_pydevd() -> None:
    """Mark the current thread as a pydevd thread that should be skipped."""


def unmark_thread_as_pydevd() -> None:
    """Unmark the current thread as a pydevd thread."""


def set_thread_skip_all(skip: bool) -> None:
    """Set whether current thread should skip all frames."""


