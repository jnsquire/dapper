"""
Internal type definitions for the frame evaluator API.

This module contains internal implementation details that are not part of the public API.
"""

from __future__ import annotations

from typing import Any


class _FrameEvalState:
    """Internal state management for frame evaluation."""

    _frame_eval_active: bool
    _breakpoint_manager: Any | None
    _frame_eval_lock: Any  # threading.Lock
    _thread_local_info: Any  # threading.local

    def _initialize_global_state(self) -> None: ...


def _should_trace_frame(frame_obj: Any) -> bool: ...


def _dummy_trace_dispatch(_frame: Any, _event: str, _arg: Any) -> None:
    """Dummy trace function for when frame evaluation is active."""
