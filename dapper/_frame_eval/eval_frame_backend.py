"""Placeholder eval-frame backend used during Phase 1.

This implementation simply provides the same interface as a tracing backend
but performs no real work; its purpose is to let the manager exercise the
new backend-abstraction code paths without yet having a working eval-frame
hook.  Once the low-level hook is implemented this file should be replaced
or extended with the real logic.
"""

from __future__ import annotations

from typing import Any

from dapper._frame_eval import install_eval_frame_hook
from dapper._frame_eval import uninstall_eval_frame_hook
from dapper._frame_eval._frame_evaluator import _clear_thread_trace_func
from dapper._frame_eval._frame_evaluator import _set_thread_trace_func
from dapper._frame_eval.backend import FrameEvalBackend
from dapper._frame_eval.cache_manager import set_breakpoints as _set_breakpoints
from dapper._frame_eval.selective_tracer import get_selective_trace_function
from dapper._frame_eval.selective_tracer import update_breakpoints as _update_breakpoints
from dapper._frame_eval.types import clear_thread_local_info
from dapper._frame_eval.types import get_thread_info

_CONTINUE_MODES = frozenset({"", "CONTINUE", "RESUME", "RUN"})


def _normalize_step_mode(mode: Any) -> str:
    if isinstance(mode, bool):
        return "STEP_IN" if mode else "CONTINUE"

    mode_name = getattr(mode, "name", mode)
    if mode_name is None:
        return "CONTINUE"

    if isinstance(mode_name, str):
        normalized = mode_name.strip().upper()
        return normalized or "CONTINUE"

    return str(mode_name).strip().upper() or "CONTINUE"


def _is_stepping_mode_active(mode: Any) -> bool:
    return _normalize_step_mode(mode) not in _CONTINUE_MODES


class EvalFrameBackend(FrameEvalBackend):
    def __init__(self) -> None:
        self._installed = False
        self._debugger = None
        self._step_mode = "CONTINUE"
        self._breakpoints: dict[str, set[int]] = {}
        self._exception_breakpoint_filters: tuple[str, ...] = ()

    def install(self, debugger_instance: object) -> None:
        self._debugger = debugger_instance
        self._step_mode = "CONTINUE"
        self._exception_breakpoint_filters = ()
        get_thread_info().step_mode = False
        trace_callback = getattr(debugger_instance, "trace_dispatch", None)
        if not callable(trace_callback):
            trace_callback = get_selective_trace_function()
        if callable(trace_callback):
            _set_thread_trace_func(trace_callback)
        install_eval_frame_hook()
        self._installed = True

    def shutdown(self) -> None:
        uninstall_eval_frame_hook()
        _clear_thread_trace_func()
        self._step_mode = "CONTINUE"
        self._breakpoints.clear()
        self._exception_breakpoint_filters = ()
        get_thread_info().step_mode = False
        clear_thread_local_info()
        self._installed = False
        self._debugger = None

    def update_breakpoints(self, filepath: str, lines: set[int]) -> None:
        normalized_lines = {int(line) for line in lines}
        self._breakpoints[filepath] = normalized_lines
        _set_breakpoints(filepath, normalized_lines)
        _update_breakpoints(filepath, normalized_lines)

    def set_stepping(self, mode: Any) -> None:
        self._step_mode = _normalize_step_mode(mode)
        get_thread_info().step_mode = self._step_mode not in _CONTINUE_MODES

    def set_exception_breakpoints(self, filters: list[str]) -> None:
        normalized_filters: list[str] = []
        seen_filters: set[str] = set()

        for filter_name in filters:
            normalized = str(filter_name).strip().lower()
            if not normalized or normalized in seen_filters:
                continue
            seen_filters.add(normalized)
            normalized_filters.append(normalized)

        self._exception_breakpoint_filters = tuple(normalized_filters)

    def get_statistics(self) -> dict[str, Any]:
        return {
            "backend": "eval_frame",
            "installed": self._installed,
            "step_mode": self._step_mode,
            "stepping_active": bool(get_thread_info().step_mode),
            "breakpoint_files": len(self._breakpoints),
            "breakpoint_lines": sum(len(lines) for lines in self._breakpoints.values()),
            "exception_breakpoint_filters": list(self._exception_breakpoint_filters),
        }
