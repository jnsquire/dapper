"""
Frame evaluation optimization module for Dapper debugger.

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

import sys
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any
    from typing import Optional

# Import main entry point
from dapper._frame_eval.frame_eval_main import check_environment_compatibility
from dapper._frame_eval.frame_eval_main import get_compatible_python_versions
from dapper._frame_eval.frame_eval_main import get_debug_info
from dapper._frame_eval.frame_eval_main import get_frame_eval_config
from dapper._frame_eval.frame_eval_main import setup_frame_eval
from dapper._frame_eval.frame_eval_main import should_use_frame_eval
from dapper._frame_eval.frame_eval_main import shutdown_frame_eval
from dapper._frame_eval.frame_eval_main import update_frame_eval_config

# Frame evaluation state
_frame_eval_enabled = False
_frame_eval_available = False
_frame_eval_func = None
_stop_frame_eval = None
_dummy_trace_dispatch = None
_clear_thread_local_info = None

# Thread-local storage for frame evaluation state
_thread_local = threading.local()

# Export main functions
__all__ = [
    # Main interface
    "is_frame_eval_available",
    "is_frame_eval_enabled", 
    "enable_frame_eval",
    "disable_frame_eval",
    "get_frame_eval_status",
    "initialize_frame_eval",
    
    # Configuration and setup
    "setup_frame_eval",
    "should_use_frame_eval",
    "get_compatible_python_versions",
    "check_environment_compatibility",
    "get_frame_eval_config",
    "update_frame_eval_config",
    "shutdown_frame_eval",
    "get_debug_info",
    
    # Advanced functions
    "get_frame_eval_stats",
    "mark_thread_as_pydevd",
    "unmark_thread_as_pydevd",
    "set_thread_skip_all",
]


def is_frame_eval_available() -> bool:
    """Check if frame evaluation is available in the current Python environment."""
    return _frame_eval_available


def is_frame_eval_enabled() -> bool:
    """Check if frame evaluation is currently enabled."""
    return _frame_eval_enabled


def enable_frame_eval() -> bool:
    """
    Enable frame evaluation if available.
    
    Returns:
        bool: True if frame evaluation was successfully enabled, False otherwise.
    """
    global _frame_eval_enabled, _frame_eval_func, _stop_frame_eval, _dummy_trace_dispatch, _clear_thread_local_info
    
    if not _frame_eval_available:
        return False
    
    try:
        # Import the Cython implementation
        from dapper._frame_eval._cython_wrapper import clear_thread_local_info
        from dapper._frame_eval._cython_wrapper import dummy_trace_dispatch
        from dapper._frame_eval._cython_wrapper import frame_eval_func
        from dapper._frame_eval._cython_wrapper import get_frame_eval_stats
        from dapper._frame_eval._cython_wrapper import mark_thread_as_pydevd
        from dapper._frame_eval._cython_wrapper import set_thread_skip_all
        from dapper._frame_eval._cython_wrapper import stop_frame_eval
        from dapper._frame_eval._cython_wrapper import unmark_thread_as_pydevd
        
        _frame_eval_func = frame_eval_func
        _stop_frame_eval = stop_frame_eval
        _dummy_trace_dispatch = dummy_trace_dispatch
        _clear_thread_local_info = clear_thread_local_info
        
        # Enable frame evaluation
        _frame_eval_func()
        _frame_eval_enabled = True
        
        return True
    except ImportError:
        return False
    except Exception:
        # Any other error during enablement
        return False


def disable_frame_eval() -> bool:
    """
    Disable frame evaluation if currently enabled.
    
    Returns:
        bool: True if frame evaluation was successfully disabled, False otherwise.
    """
    global _frame_eval_enabled
    
    if not _frame_eval_enabled or _stop_frame_eval is None:
        return False
    
    try:
        _stop_frame_eval()
        _frame_eval_enabled = False
        return True
    except Exception:
        return False


def get_frame_eval_status() -> dict[str, Any]:
    """
    Get the current status of frame evaluation.
    
    Returns:
        dict: Status information including availability, enabled state, and Python version.
    """
    return {
        "available": _frame_eval_available,
        "enabled": _frame_eval_enabled,
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "platform": sys.platform,
        "compatibility": check_environment_compatibility(),
        "config": get_frame_eval_config(),
    }


def initialize_frame_eval() -> None:
    """Initialize frame evaluation availability check."""
    global _frame_eval_available
    
    # Check Python version compatibility (3.6-3.10)
    if not (3, 6) <= sys.version_info[:2] <= (3, 10):
        _frame_eval_available = False
        return
    
    # Check for required C API features
    try:
        # Test if we can access the frame evaluation API
        import _imp
        _imp._fix_co_filename
        _frame_eval_available = True
    except (AttributeError, ImportError):
        _frame_eval_available = False


def initialize_with_config(config: dict[str, Any]) -> bool:
    """
    Initialize frame evaluation with a specific configuration.
    
    Args:
        config: Configuration dictionary for frame evaluation
        
    Returns:
        bool: True if initialization was successful
    """
    # First check basic availability
    initialize_frame_eval()
    
    if not _frame_eval_available:
        return config.get("fallback_to_tracing", True)
    
    # Set up with configuration
    return setup_frame_eval(config)


# Initialize on module import
initialize_frame_eval()


def get_frame_eval_stats() -> dict[str, Any]:
    """
    Get statistics about frame evaluation performance.
    
    Returns:
        dict: Statistics including active status, code extra index, etc.
    """
    if not _frame_eval_available:
        return {"available": False}
    
    try:
        from dapper._frame_eval._cython_wrapper import get_frame_eval_stats
        return get_frame_eval_stats()
    except ImportError:
        return {"available": False, "error": "Cython wrapper not available"}


def mark_thread_as_pydevd() -> None:
    """Mark the current thread as a pydevd thread that should be skipped."""
    if not _frame_eval_available:
        return
    
    try:
        from dapper._frame_eval._cython_wrapper import mark_thread_as_pydevd
        mark_thread_as_pydevd()
    except ImportError:
        pass


def unmark_thread_as_pydevd() -> None:
    """Unmark the current thread as a pydevd thread."""
    if not _frame_eval_available:
        return
    
    try:
        from dapper._frame_eval._cython_wrapper import unmark_thread_as_pydevd
        unmark_thread_as_pydevd()
    except ImportError:
        pass


def set_thread_skip_all(skip: bool) -> None:
    """
    Set whether current thread should skip all frames.
    
    Args:
        skip: True to skip all frames in this thread
    """
    if not _frame_eval_available:
        return
    
    try:
        from dapper._frame_eval._cython_wrapper import set_thread_skip_all
        set_thread_skip_all(skip)
    except ImportError:
        pass
