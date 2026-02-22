"""Frame evaluation optimization module for Dapper debugger.

This module provides Cython-based frame evaluation to minimize the performance
overhead of Python's sys.settrace() mechanism by:

1. Selective Frame Tracing: Only enable tracing on frames with breakpoints
2. Bytecode Modification: Inject breakpoints directly into bytecode
3. Caching Mechanisms: Store breakpoint information in code objects
4. Fast Path Optimizations: Skip debugger frames using C-level hooks

The implementation is inspired by debugpy's frame evaluation approach and
provides significant performance improvements for debugging scenarios.
"""

from __future__ import annotations

# Standard library imports
import threading
from typing import Any
from typing import Callable

# Local application imports
from dapper._frame_eval.frame_eval_main import frame_eval_manager

# Type aliases for Cython functions
CythonFuncType = Callable[..., Any]

# Initialize Cython functions with type hints
_cython_enable_frame_eval: CythonFuncType | None = None
_cython_get_stats: CythonFuncType | None = None
_cython_mark_pydevd: CythonFuncType | None = None
_cython_set_skip_all: CythonFuncType | None = None
_cython_unmark_pydevd: CythonFuncType | None = None

# Try to import Cython functions
# Note: These are imported at module level to avoid import cycles
# and ensure thread safety. The imports are wrapped in a try/except
# to handle cases where the Cython extensions are not available.
try:
    from dapper._frame_eval._frame_evaluator import (
        frame_eval_func as _cython_enable_frame_eval_func,
    )
    from dapper._frame_eval._frame_evaluator import get_frame_eval_stats as _cython_get_stats_func
    from dapper._frame_eval._frame_evaluator import (
        mark_thread_as_pydevd as _cython_mark_pydevd_func,
    )
    from dapper._frame_eval._frame_evaluator import (
        set_thread_skip_all as _cython_set_skip_all_func,
    )
    from dapper._frame_eval._frame_evaluator import (
        unmark_thread_as_pydevd as _cython_unmark_pydevd_func,
    )

    _cython_enable_frame_eval = _cython_enable_frame_eval_func
    _cython_get_stats = _cython_get_stats_func
    _cython_mark_pydevd = _cython_mark_pydevd_func
    _cython_set_skip_all = _cython_set_skip_all_func
    _cython_unmark_pydevd = _cython_unmark_pydevd_func
    CYTHON_AVAILABLE = True
except ImportError:
    CYTHON_AVAILABLE = False


class FrameEvalState:
    """Singleton class to manage frame evaluation state."""

    # Class-level references to Cython functions
    _cython_enable_frame_eval = _cython_enable_frame_eval
    _cython_get_stats = _cython_get_stats
    _cython_mark_pydevd = _cython_mark_pydevd
    _cython_set_skip_all = _cython_set_skip_all
    _cython_unmark_pydevd = _cython_unmark_pydevd

    def __init__(self):
        self.available = False
        self.enabled = False
        self.func = None
        self.stop_func = None
        self.dummy_trace_dispatch = None
        self.clear_thread_local_info = None
        self.cython_stats_func = None
        self.thread_local = threading.local()
        self._cython_imported = False

    def _import_cython(self) -> bool:
        """Check if Cython imports are available.

        Returns:
            bool: True if Cython imports are available, False otherwise.
        """
        self._cython_imported = CYTHON_AVAILABLE
        return self._cython_imported

    def check_environment_compatibility(self):
        return frame_eval_manager.check_environment_compatibility()

    def setup_frame_eval(self, config: dict[str, Any] | None = None) -> bool:
        """Set up frame evaluation with the given configuration.

        Args:
            config: Optional configuration dictionary

        Returns:
            bool: True if setup was successful
        """
        return frame_eval_manager.setup_frame_eval(config or {})

    def get_debug_info(self):
        return frame_eval_manager.get_debug_info()

    def get_frame_eval_stats(self) -> dict[str, Any]:
        """Get frame evaluation statistics.

        Returns:
            dict: Statistics or error information if Cython is not available
        """
        if not self._import_cython():
            return {"available": False, "error": "Cython wrapper not available"}

        if FrameEvalState._cython_get_stats is not None:
            return FrameEvalState._cython_get_stats()
        return {"available": False, "error": "Cython stats function not available"}

    def mark_thread_as_pydevd(self) -> None:
        """Mark the current thread as a pydevd thread."""
        if self._import_cython() and FrameEvalState._cython_mark_pydevd:
            FrameEvalState._cython_mark_pydevd()

    def unmark_thread_as_pydevd(self) -> None:
        """Remove pydevd thread marking from current thread."""
        if self._import_cython() and FrameEvalState._cython_unmark_pydevd:
            FrameEvalState._cython_unmark_pydevd()

    def set_thread_skip_all(self, skip: bool) -> None:
        """Set whether current thread should skip all frames.

        Args:
            skip: If True, skip all frames in this thread
        """
        if self._import_cython() and FrameEvalState._cython_set_skip_all:
            FrameEvalState._cython_set_skip_all(skip)


# Singleton instance
_state = FrameEvalState()


def is_frame_eval_available() -> bool:
    """Check if frame evaluation is available in the current Python environment."""
    return _state.available


def is_frame_eval_enabled() -> bool:
    """Check if frame evaluation is currently enabled."""
    return _state.enabled


def enable_frame_eval() -> bool:
    """Enable frame evaluation if available.

    Returns:
        bool: True if frame evaluation was successfully enabled, False otherwise.
    """
    if _state.enabled:
        return True

    if not _state.available:
        return False

    if _state.setup_frame_eval({}):  # Pass empty config by default
        _state.enabled = True
        return True

    _state.enabled = False
    return False


def disable_frame_eval() -> bool:
    """Disable frame evaluation if currently enabled.

    Returns:
        bool: True if frame evaluation was successfully disabled, False otherwise.
    """
    if not _state.enabled:
        return True

    try:
        frame_eval_manager.shutdown_frame_eval()
    except Exception:  # pylint: disable=broad-except
        _state.enabled = False
        return False
    else:
        _state.enabled = False
        return True


def get_frame_eval_status() -> dict[str, Any]:
    """Get the current status of frame evaluation.

    Returns:
        dict: Status information including availability, enabled state, and Python version.
    """
    debug_info = _state.get_debug_info()
    return {
        "available": _state.available,
        "enabled": _state.enabled,
        "python_version": debug_info.get("python_version", "unknown"),
        "platform": debug_info.get("platform", "unknown"),
        "implementation": debug_info.get("implementation", "unknown"),
    }


def initialize_frame_eval() -> None:
    """Initialize frame evaluation availability check."""
    _state.available = _state._import_cython()  # noqa: SLF001


def initialize_with_config(config: dict[str, Any]) -> bool:
    """Initialize frame evaluation with a specific configuration.

    Args:
        config: Configuration dictionary for frame evaluation

    Returns:
        bool: True if initialization was successful
    """
    if not isinstance(config, dict):
        return False

    if not _state.available:
        return False

    return frame_eval_manager.setup_frame_eval(config)


# Initialize on module import
initialize_frame_eval()


def get_frame_eval_stats() -> dict[str, Any]:
    """Get statistics about frame evaluation performance.

    Returns:
        dict: Statistics including active status, code extra index, etc.
    """
    return _state.get_frame_eval_stats()


def mark_thread_as_pydevd() -> None:
    """Mark the current thread as a pydevd thread that should be skipped."""
    _state.mark_thread_as_pydevd()


def unmark_thread_as_pydevd() -> None:
    """Unmark the current thread as a pydevd thread."""
    _state.unmark_thread_as_pydevd()


def set_thread_skip_all(skip: bool) -> None:
    """Set whether current thread should skip all frames.

    Args:
        skip: True to skip all frames in this thread
    """
    _state.set_thread_skip_all(skip)
