"""Pure-Python fallback implementation of frame-evaluator extension API.

This module now re-exports the shared runtime logic used by both backends. The
only backend-specific code lives in the optional Cython extension wrapper.
"""

from __future__ import annotations

from importlib import import_module
from types import CodeType

from dapper._frame_eval._frame_evaluator_shared import BreakpointLines
from dapper._frame_eval._frame_evaluator_shared import FrameStats
from dapper._frame_eval._frame_evaluator_shared import FuncCodeInfo
from dapper._frame_eval._frame_evaluator_shared import ThreadInfo
from dapper._frame_eval._frame_evaluator_shared import _FrameEvalModuleState
from dapper._frame_eval._frame_evaluator_shared import _state
from dapper._frame_eval._frame_evaluator_shared import dummy_trace_dispatch
from dapper._frame_eval._frame_evaluator_shared import (
    get_func_code_info as _shared_get_func_code_info,
)
from dapper._frame_eval.cache_manager import get_cached_code
from dapper._frame_eval.cache_manager import set_cached_code
from dapper._frame_eval.telemetry import telemetry

_code_extra_fallback: dict[CodeType, object] = {}


def install_eval_frame_hook() -> bool:
    return _state.install_hook()


def uninstall_eval_frame_hook() -> bool:
    return _state.uninstall_hook()


def get_eval_frame_hook_status() -> dict[str, str | bool | None]:
    return _state.get_hook_status()


def _collect_code_lines(code_obj: CodeType) -> set[int]:
    try:
        return {line for _, _, line in code_obj.co_lines() if line is not None}
    except Exception:
        return {code_obj.co_firstlineno}


def _should_trace_code_for_eval_frame(code_obj: CodeType, lineno: int) -> bool:
    return _should_trace_code_for_eval_frame_with_frame(code_obj, lineno, None)


def _should_trace_code_for_eval_frame_with_frame(
    code_obj: CodeType,
    lineno: int,
    frame_obj=None,
) -> bool:
    selective_tracer = import_module("dapper._frame_eval.selective_tracer")

    decision = selective_tracer.should_trace_code_location(code_obj, lineno, frame_obj)
    return decision["path"] == "breakpointed"


def _set_thread_trace_func(trace_func) -> None:
    _state.get_thread_info().thread_trace_func = trace_func


def _clear_thread_trace_func() -> None:
    _state.get_thread_info().thread_trace_func = None


def _dispatch_trace_callback(frame_obj, event: str = "line", arg=None) -> bool:
    info = _state.get_thread_info()
    trace_func = getattr(frame_obj, "f_trace", None)
    if trace_func is None:
        trace_func = info.thread_trace_func
    if trace_func is None:
        return False
    next_trace_func = trace_func(frame_obj, event, arg)
    frame_obj.f_trace = next_trace_func
    return True


def _dispatch_eval_frame_entry_trace(frame_obj) -> bool:
    had_local_trace = getattr(frame_obj, "f_trace", None) is not None

    if not had_local_trace:
        if not _dispatch_trace_callback(frame_obj, "call", None):
            return False
        if getattr(frame_obj, "f_trace", None) is None:
            return True

    return _dispatch_trace_callback(frame_obj, "line", None)


def _dispatch_eval_frame_return_trace(frame_obj, arg=None) -> bool:
    if getattr(frame_obj, "f_trace", None) is None:
        return False
    return _dispatch_trace_callback(frame_obj, "return", arg)


def _get_current_eval_frame_address() -> int:
    return 0


def _get_code_extra_metadata(code_obj: CodeType):
    if not isinstance(code_obj, CodeType):
        raise TypeError("code argument must be a code object")
    return _code_extra_fallback.get(code_obj)


def _store_code_extra_metadata(code_obj: CodeType, metadata: object) -> bool:
    if not isinstance(code_obj, CodeType):
        raise TypeError("code argument must be a code object")
    _code_extra_fallback[code_obj] = metadata
    return True


def _clear_code_extra_metadata(code_obj: CodeType) -> bool:
    if not isinstance(code_obj, CodeType):
        raise TypeError("code argument must be a code object")
    return _code_extra_fallback.pop(code_obj, None) is not None


def _store_modified_code_for_evaluation(
    original_code: CodeType,
    modified_code: CodeType,
    breakpoint_lines=None,
) -> bool:
    if not isinstance(modified_code, CodeType):
        raise TypeError("modified_code argument must be a code object")
    set_cached_code(original_code, modified_code)
    return _store_code_extra_metadata(
        original_code,
        {
            "modified_code": modified_code,
            "breakpoint_lines": set(breakpoint_lines or ()),
        },
    )


def _get_modified_code_for_evaluation(code_obj: CodeType) -> CodeType | None:
    metadata = _get_code_extra_metadata(code_obj)
    if isinstance(metadata, dict):
        modified_code = metadata.get("modified_code")
        if isinstance(modified_code, CodeType):
            telemetry.record_cache_hit(source="code_extra", filename=code_obj.co_filename)
            return modified_code
    cached_code = get_cached_code(code_obj)
    if isinstance(cached_code, CodeType):
        telemetry.record_cache_hit(source="cache_manager", filename=code_obj.co_filename)
        return cached_code
    telemetry.record_cache_miss(filename=code_obj.co_filename)
    return None


def get_func_code_info(frame_obj, code_obj: CodeType | object) -> FuncCodeInfo:
    info = _shared_get_func_code_info(frame_obj, code_obj)
    if isinstance(code_obj, CodeType):
        info.new_code = _get_modified_code_for_evaluation(code_obj)
    return info


__all__ = [
    "BreakpointLines",
    "FrameStats",
    "FuncCodeInfo",
    "ThreadInfo",
    "_FrameEvalModuleState",
    "_clear_code_extra_metadata",
    "_clear_thread_trace_func",
    "_collect_code_lines",
    "_dispatch_eval_frame_entry_trace",
    "_dispatch_eval_frame_return_trace",
    "_dispatch_trace_callback",
    "_get_code_extra_metadata",
    "_get_current_eval_frame_address",
    "_get_modified_code_for_evaluation",
    "_set_thread_trace_func",
    "_should_trace_code_for_eval_frame",
    "_should_trace_code_for_eval_frame_with_frame",
    "_state",
    "_store_code_extra_metadata",
    "_store_modified_code_for_evaluation",
    "dummy_trace_dispatch",
    "get_eval_frame_hook_status",
    "get_func_code_info",
    "install_eval_frame_hook",
    "uninstall_eval_frame_hook",
]
