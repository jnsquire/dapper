"""Runtime-compatible frame evaluator API shims.

This module preserves a stable import surface for the frame evaluator.
Both the Cython extension and the pure-Python fallback expose
``_FrameEvalModuleState`` and a module-level ``_state`` singleton.
Typing-only declarations live in ``types.pyi``.
"""

from __future__ import annotations

from typing import Union

from dapper._frame_eval._frame_evaluator import FuncCodeInfo
from dapper._frame_eval._frame_evaluator import ThreadInfo
from dapper._frame_eval._frame_evaluator import _FrameEvalModuleState
from dapper._frame_eval._frame_evaluator import _state
from dapper._frame_eval._frame_evaluator import get_func_code_info

FrameStats = dict[str, Union[int, float, bool]]
BreakpointLines = set[int]


# Convenience aliases kept for backward compatibility — thin delegates to _state.
def frame_eval_func() -> None:
    _state.enable()


def stop_frame_eval() -> None:
    _state.disable()


def get_thread_info() -> ThreadInfo:
    return _state.get_thread_info()


def clear_thread_local_info() -> None:
    _state.clear_thread_local_info()


def get_frame_eval_stats() -> FrameStats:
    return _state.get_stats()


def mark_thread_as_pydevd() -> None:
    _state.get_thread_info().is_pydevd_thread = True


def unmark_thread_as_pydevd() -> None:
    _state.get_thread_info().is_pydevd_thread = False


def set_thread_skip_all(skip: bool) -> None:
    info = _state.get_thread_info()
    info.skip_all_frames = skip


__all__ = [
    "BreakpointLines",
    "FrameStats",
    "FuncCodeInfo",
    "ThreadInfo",
    "_FrameEvalModuleState",
    "_state",
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
