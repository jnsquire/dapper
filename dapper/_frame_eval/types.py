"""Runtime-compatible frame evaluator API shims.

This module preserves a stable import surface even when the Cython extension
is unavailable. Typing-only declarations live in `types.pyi`.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING
from typing import Any
from typing import Union

if TYPE_CHECKING:
    from types import CodeType
    from types import FrameType

FrameStats = dict[str, Union[int, float, bool]]
BreakpointLines = set[int]


_CYTHON_AVAILABLE = False

try:
    from dapper._frame_eval._frame_evaluator import FuncCodeInfo as _CythonFuncCodeInfo
    from dapper._frame_eval._frame_evaluator import ThreadInfo as _CythonThreadInfo
    from dapper._frame_eval._frame_evaluator import (
        clear_thread_local_info as _cy_clear_thread_local_info,
    )
    from dapper._frame_eval._frame_evaluator import frame_eval_func as _cy_frame_eval_func
    from dapper._frame_eval._frame_evaluator import (
        get_frame_eval_stats as _cy_get_frame_eval_stats,
    )
    from dapper._frame_eval._frame_evaluator import get_func_code_info as _cy_get_func_code_info
    from dapper._frame_eval._frame_evaluator import get_thread_info as _cy_get_thread_info
    from dapper._frame_eval._frame_evaluator import (
        mark_thread_as_pydevd as _cy_mark_thread_as_pydevd,
    )
    from dapper._frame_eval._frame_evaluator import set_thread_skip_all as _cy_set_thread_skip_all
    from dapper._frame_eval._frame_evaluator import stop_frame_eval as _cy_stop_frame_eval
    from dapper._frame_eval._frame_evaluator import (
        unmark_thread_as_pydevd as _cy_unmark_thread_as_pydevd,
    )

    ThreadInfo = _CythonThreadInfo
    FuncCodeInfo = _CythonFuncCodeInfo
    _CYTHON_AVAILABLE = True
except ImportError:

    class _FallbackState:
        def __init__(self) -> None:
            self.thread_local = threading.local()
            self.frame_eval_active = False

    _fallback_state = _FallbackState()

    class ThreadInfo:
        """Thread-local debugging information for frame evaluation."""

        inside_frame_eval: int
        fully_initialized: bool
        is_pydevd_thread: bool
        thread_trace_func: Any | None
        additional_info: Any | None
        recursion_depth: int
        skip_all_frames: bool

        def __init__(self) -> None:
            self.inside_frame_eval = 0
            self.fully_initialized = True
            self.is_pydevd_thread = False
            self.thread_trace_func = None
            self.additional_info = None
            self.recursion_depth = 0
            self.skip_all_frames = False

        def enter_frame_eval(self) -> None:
            self.inside_frame_eval += 1
            self.recursion_depth += 1

        def exit_frame_eval(self) -> None:
            if self.inside_frame_eval > 0:
                self.inside_frame_eval -= 1
            if self.recursion_depth > 0:
                self.recursion_depth -= 1

        def should_skip_frame(self, frame: FrameType) -> bool:
            del frame
            return self.skip_all_frames

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

        def __init__(self) -> None:
            self.co_filename = b""
            self.real_path = ""
            self.always_skip_code = False
            self.breakpoint_found = False
            self.new_code = None
            self.breakpoints_mtime = 0.0
            self.breakpoint_lines = set()
            self.last_check_time = 0.0
            self.is_valid = True

        def update_breakpoint_info(self, code_obj: CodeType) -> None:
            self.co_filename = code_obj.co_filename.encode("utf-8", errors="ignore")
            self.real_path = code_obj.co_filename
            self.always_skip_code = not bool(self.breakpoint_lines)


def get_thread_info() -> ThreadInfo:
    """Get thread-local debugging information."""
    if _CYTHON_AVAILABLE:
        return _cy_get_thread_info()

    thread_info = getattr(_fallback_state.thread_local, "thread_info", None)
    if thread_info is None:
        thread_info = ThreadInfo()
        _fallback_state.thread_local.thread_info = thread_info
    return thread_info


def get_func_code_info(frame_obj: FrameType, code_obj: CodeType) -> FuncCodeInfo:
    """Get code object breakpoint information with caching.

    Keeps the public two-argument signature for compatibility.
    """
    if _CYTHON_AVAILABLE:
        return _cy_get_func_code_info(frame_obj, code_obj)

    del frame_obj

    info = FuncCodeInfo()
    info.update_breakpoint_info(code_obj)
    return info


def frame_eval_func() -> None:
    """Enable frame evaluation by setting the eval_frame hook."""
    if _CYTHON_AVAILABLE:
        _cy_frame_eval_func()
        return

    _fallback_state.frame_eval_active = True


def stop_frame_eval() -> None:
    """Disable frame evaluation by restoring the default eval_frame hook."""
    if _CYTHON_AVAILABLE:
        _cy_stop_frame_eval()
        return

    _fallback_state.frame_eval_active = False


def clear_thread_local_info() -> None:
    """Clear thread-local debugging information."""
    if _CYTHON_AVAILABLE:
        _cy_clear_thread_local_info()
        return

    _fallback_state.thread_local = threading.local()


def get_frame_eval_stats() -> FrameStats:
    """Get statistics about frame evaluation performance."""
    if _CYTHON_AVAILABLE:
        stats = _cy_get_frame_eval_stats()
        if isinstance(stats, dict):
            return stats

    return {
        "frames_evaluated": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "evaluation_time": 0.0,
        "is_active": _fallback_state.frame_eval_active,
    }


def mark_thread_as_pydevd() -> None:
    """Mark the current thread as a pydevd thread that should be skipped."""
    if _CYTHON_AVAILABLE:
        _cy_mark_thread_as_pydevd()
        return

    get_thread_info().is_pydevd_thread = True


def unmark_thread_as_pydevd() -> None:
    """Unmark the current thread as a pydevd thread."""
    if _CYTHON_AVAILABLE:
        _cy_unmark_thread_as_pydevd()
        return

    get_thread_info().is_pydevd_thread = False


def set_thread_skip_all(skip: bool) -> None:
    """Set whether current thread should skip all frames."""
    if _CYTHON_AVAILABLE:
        _cy_set_thread_skip_all(skip)
        return

    get_thread_info().skip_all_frames = skip


__all__ = [
    "BreakpointLines",
    "FrameStats",
    "FuncCodeInfo",
    "ThreadInfo",
    "clear_thread_local_info",
    "frame_eval_func",
    "get_frame_eval_stats",
    "get_func_code_info",
    "get_thread_info",
    "mark_thread_as_pydevd",
    "set_thread_skip_all",
    "stop_frame_eval",
    "unmark_thread_as_pydevd",
]
