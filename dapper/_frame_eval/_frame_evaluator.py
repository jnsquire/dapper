"""Pure-Python fallback implementation of frame-evaluator extension API.

This module mirrors the public symbols from the optional compiled
`_frame_evaluator` extension so import sites can operate in environments
where C extensions are not built.
"""

from __future__ import annotations

import contextvars
from typing import TYPE_CHECKING
from typing import Any
from typing import Union

if TYPE_CHECKING:
    from types import CodeType
    from types import FrameType

BreakpointLines = set[int]
FrameStats = dict[str, Union[int, float, bool]]


# Module-level mutable state (not per-context)
_frame_eval_active: bool = False

# Context-local storage — mirrors the Cython ContextVar so that
# ``Context.run()`` gives each context its own ThreadInfo.
_thread_info_var: contextvars.ContextVar[ThreadInfo | None] = contextvars.ContextVar(
    "thread_info", default=None
)


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
    thread_info = _thread_info_var.get()
    if thread_info is None:
        thread_info = ThreadInfo()
        _thread_info_var.set(thread_info)
    return thread_info


def get_func_code_info(frame_obj: FrameType, code_obj: CodeType) -> FuncCodeInfo:
    del frame_obj
    info = FuncCodeInfo()
    info.update_breakpoint_info(code_obj)
    return info


def frame_eval_func() -> None:
    global _frame_eval_active
    _frame_eval_active = True


def stop_frame_eval() -> None:
    global _frame_eval_active
    _frame_eval_active = False


def clear_thread_local_info() -> None:
    _thread_info_var.set(None)


def get_frame_eval_stats() -> FrameStats:
    return {
        "active": _frame_eval_active,
        "has_breakpoint_manager": False,
        "frames_evaluated": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "evaluation_time": 0.0,
        "is_active": _frame_eval_active,
    }



def mark_thread_as_pydevd() -> None:
    get_thread_info().is_pydevd_thread = True


def unmark_thread_as_pydevd() -> None:
    get_thread_info().is_pydevd_thread = False


def set_thread_skip_all(skip: bool) -> None:
    info = get_thread_info()
    info.skip_all_frames = skip
    info.step_mode = skip


def dummy_trace_dispatch(frame: FrameType, event: str, arg: Any) -> Any:
    """Fallback dummy trace dispatch function.

    Args:
        frame: The frame object.
        event: The event name (e.g. 'call', 'line', 'return').
        arg: The event argument.

    Returns:
        The trace function itself or None.
    """
    del frame, event, arg
    return None


__all__ = [
    "BreakpointLines",
    "FrameStats",
    "FuncCodeInfo",
    "ThreadInfo",
    "clear_thread_local_info",
    "dummy_trace_dispatch",
    "frame_eval_func",
    "get_frame_eval_stats",
    "get_func_code_info",
    "get_thread_info",
    "mark_thread_as_pydevd",
    "set_thread_skip_all",
    "stop_frame_eval",
    "unmark_thread_as_pydevd",
]
