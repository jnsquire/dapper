"""Pure-Python fallback implementation of frame-evaluator extension API.

This module now re-exports the shared runtime logic used by both backends. The
only backend-specific code lives in the optional Cython extension wrapper.
"""

from __future__ import annotations

from dapper._frame_eval._frame_evaluator_shared import BreakpointLines
from dapper._frame_eval._frame_evaluator_shared import FrameStats
from dapper._frame_eval._frame_evaluator_shared import FuncCodeInfo
from dapper._frame_eval._frame_evaluator_shared import ThreadInfo
from dapper._frame_eval._frame_evaluator_shared import _FrameEvalModuleState
from dapper._frame_eval._frame_evaluator_shared import _state
from dapper._frame_eval._frame_evaluator_shared import dummy_trace_dispatch
from dapper._frame_eval._frame_evaluator_shared import get_func_code_info


def install_eval_frame_hook() -> bool:
    return _state.install_hook()


def uninstall_eval_frame_hook() -> bool:
    return _state.uninstall_hook()


def get_eval_frame_hook_status() -> dict[str, str | bool | None]:
    return _state.get_hook_status()


__all__ = [
    "BreakpointLines",
    "FrameStats",
    "FuncCodeInfo",
    "ThreadInfo",
    "_FrameEvalModuleState",
    "_state",
    "dummy_trace_dispatch",
    "get_eval_frame_hook_status",
    "get_func_code_info",
    "install_eval_frame_hook",
    "uninstall_eval_frame_hook",
]
