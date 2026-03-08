"""Shared runtime logic for frame-evaluator backends.

This module holds the Python-visible state and helper types used by both the
optional Cython extension backend and the pure-Python fallback. Keeping the
shared pieces here avoids maintaining two near-identical implementations of the
same bookkeeping logic.
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


class _FrameEvalModuleState:
    """Mutable state shared by frame-evaluation backends."""

    __slots__ = ("active", "hook_available", "hook_error", "hook_installed", "thread_info_var")

    def __init__(self) -> None:
        self.active: bool = False
        self.hook_available: bool = True
        self.hook_installed: bool = False
        self.hook_error: str | None = None
        self.thread_info_var: contextvars.ContextVar[ThreadInfo | None] = contextvars.ContextVar(
            "thread_info", default=None
        )

    def enable(self) -> None:
        self.active = True

    def disable(self) -> None:
        self.active = False

    def install_hook(self) -> bool:
        self.hook_error = None
        self.hook_installed = True
        return True

    def uninstall_hook(self) -> bool:
        self.hook_error = None
        self.hook_installed = False
        return True

    def get_hook_status(self) -> dict[str, str | bool | None]:
        return {
            "available": self.hook_available,
            "installed": self.hook_installed,
            "error": self.hook_error,
        }

    def get_thread_info(self) -> ThreadInfo:
        thread_info = self.thread_info_var.get()
        if thread_info is None:
            thread_info = ThreadInfo()
            self.thread_info_var.set(thread_info)
        return thread_info

    def clear_thread_local_info(self) -> None:
        self.thread_info_var.set(None)

    def get_stats(self) -> FrameStats:
        return {
            "active": self.active,
            "has_breakpoint_manager": False,
            "frames_evaluated": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "evaluation_time": 0.0,
            "is_active": self.active,
            "hook_available": self.hook_available,
            "hook_installed": self.hook_installed,
        }


_state = _FrameEvalModuleState()


class ThreadInfo:
    """Thread-local debugging information for frame evaluation."""

    inside_frame_eval: int
    fully_initialized: bool
    is_debugger_internal_thread: bool
    thread_trace_func: Any | None
    additional_info: Any | None
    recursion_depth: int
    skip_all_frames: bool
    step_mode: bool

    def __init__(self) -> None:
        self.inside_frame_eval = 0
        self.fully_initialized = True
        self.is_debugger_internal_thread = False
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


def get_func_code_info(frame_obj: FrameType, code_obj: CodeType) -> FuncCodeInfo:
    del frame_obj
    info = FuncCodeInfo()
    info.update_breakpoint_info(code_obj)
    return info


def dummy_trace_dispatch(frame: FrameType, event: str, arg: Any) -> Any:
    del frame, event, arg
    return None


__all__ = [
    "BreakpointLines",
    "FrameStats",
    "FuncCodeInfo",
    "ThreadInfo",
    "_FrameEvalModuleState",
    "_state",
    "dummy_trace_dispatch",
    "get_func_code_info",
]
