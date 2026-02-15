"""Pure-Python fallback implementation of frame-evaluator extension API.

This module mirrors the public symbols from the optional compiled
`_frame_evaluator` extension so import sites can operate in environments
where C extensions are not built.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING
from typing import Any
from typing import Union

if TYPE_CHECKING:
    from types import CodeType
    from types import FrameType

BreakpointLines = set[int]
FrameStats = dict[str, Union[int, float, bool]]


class _FallbackState:
    def __init__(self) -> None:
        self.thread_local = threading.local()
        self.frame_eval_active = False


_state = _FallbackState()


class ThreadInfo:
    """Thread-local debugging information for frame evaluation."""

    inside_frame_eval: int
    fully_initialized: bool
    is_pydevd_thread: bool
    thread_trace_func: Any | None
    additional_info: Any | None
    recursion_depth: int
    skip_all_frames: bool
    step_mode: bool

    def __init__(self) -> None:
        self.inside_frame_eval = 0
        self.fully_initialized = True
        self.is_pydevd_thread = False
        self.thread_trace_func = None
        self.additional_info = None
        self.recursion_depth = 0
        self.skip_all_frames = False
        self.step_mode = False

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
    """Code object breakpoint information with caching metadata."""

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
    thread_info = getattr(_state.thread_local, "thread_info", None)
    if thread_info is None:
        thread_info = ThreadInfo()
        _state.thread_local.thread_info = thread_info
    return thread_info


def get_func_code_info(frame_obj: FrameType, code_obj: CodeType) -> FuncCodeInfo:
    del frame_obj
    info = FuncCodeInfo()
    info.update_breakpoint_info(code_obj)
    return info


def frame_eval_func() -> None:
    _state.frame_eval_active = True


def stop_frame_eval() -> None:
    _state.frame_eval_active = False


def clear_thread_local_info() -> None:
    _state.thread_local = threading.local()


def get_frame_eval_stats() -> FrameStats:
    return {
        "active": _state.frame_eval_active,
        "has_breakpoint_manager": False,
        "frames_evaluated": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "evaluation_time": 0.0,
        "is_active": _state.frame_eval_active,
    }


def mark_thread_as_pydevd() -> None:
    get_thread_info().is_pydevd_thread = True


def unmark_thread_as_pydevd() -> None:
    get_thread_info().is_pydevd_thread = False


def set_thread_skip_all(skip: bool) -> None:
    info = get_thread_info()
    info.skip_all_frames = skip
    info.step_mode = skip


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
