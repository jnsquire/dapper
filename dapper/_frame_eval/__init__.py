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
import importlib.machinery
import threading
from typing import Any

# Local application imports
from dapper._frame_eval.frame_eval_main import frame_eval_manager
from dapper._frame_eval.types import get_frame_eval_capabilities

# Initialize Cython functions with type hints
_cython_state: Any | None = None
_EXTENSION_SUFFIXES = tuple(importlib.machinery.EXTENSION_SUFFIXES)


def _is_compiled_frame_evaluator(module: Any) -> bool:
    spec = getattr(module, "__spec__", None)
    loader = getattr(spec, "loader", None)
    origin = getattr(module, "__file__", None) or getattr(spec, "origin", None)

    if isinstance(loader, importlib.machinery.ExtensionFileLoader):
        return True
    return bool(origin and origin.endswith(_EXTENSION_SUFFIXES))


# Try to import the _state singleton from the extension module.
# The pure-Python fallback always provides _state, so this import
# only truly fails if _frame_evaluator itself is broken.
try:
    from dapper._frame_eval import _frame_evaluator as _cython_module

    _cython_state = _cython_module._state  # noqa: SLF001
    _install_eval_frame_hook = _cython_module.install_eval_frame_hook
    _uninstall_eval_frame_hook = _cython_module.uninstall_eval_frame_hook
    _get_eval_frame_hook_status = _cython_module.get_eval_frame_hook_status

    CYTHON_AVAILABLE = _is_compiled_frame_evaluator(_cython_module)
except ImportError:
    _cython_module = None
    _install_eval_frame_hook = None
    _uninstall_eval_frame_hook = None
    _get_eval_frame_hook_status = None
    CYTHON_AVAILABLE = False


class FrameEvalState:
    """Singleton class to manage frame evaluation state."""

    _cython_state = _cython_state

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
        # these two mirrors attributes defined on the Cython/Python
        # ``_FrameEvalModuleState``; keeping them here for type checking
        # makes assignments below error-free.
        self.hook_reason: str | None = None
        self.hook_error: str | None = None

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
        if not self._import_cython() or FrameEvalState._cython_state is None:
            return {"available": False, "error": "Cython wrapper not available"}

        return FrameEvalState._cython_state.get_stats()

    def install_eval_frame_hook(self) -> bool:
        if not self._import_cython() or _install_eval_frame_hook is None:
            return False
        return bool(_install_eval_frame_hook())

    def uninstall_eval_frame_hook(self) -> bool:
        if not self._import_cython() or _uninstall_eval_frame_hook is None:
            return False
        return bool(_uninstall_eval_frame_hook())

    def get_eval_frame_hook_status(self) -> dict[str, Any]:
        if not self._import_cython() or _get_eval_frame_hook_status is None:
            return {
                "available": False,
                "installed": False,
                "error": "Cython wrapper not available",
            }
        return dict(_get_eval_frame_hook_status())

    def mark_thread_as_debugger_internal(self) -> None:
        """Mark the current thread as debugger-internal."""
        if self._import_cython() and FrameEvalState._cython_state is not None:
            FrameEvalState._cython_state.get_thread_info().is_debugger_internal_thread = True

    def unmark_thread_as_debugger_internal(self) -> None:
        """Remove debugger-internal marking from the current thread."""
        if self._import_cython() and FrameEvalState._cython_state is not None:
            FrameEvalState._cython_state.get_thread_info().is_debugger_internal_thread = False

    def set_thread_skip_all(self, skip: bool) -> None:
        """Set whether current thread should skip all frames.

        Args:
            skip: If True, skip all frames in this thread
        """
        if self._import_cython() and FrameEvalState._cython_state is not None:
            info = FrameEvalState._cython_state.get_thread_info()
            info.skip_all_frames = skip


# Singleton instance
_state = FrameEvalState()


def is_frame_eval_available() -> bool:
    """Check if frame evaluation is available in the current Python environment.

    ``FrameEvalState`` caches the availability flag at import time, which
    normally mirrors the runtime capabilities extracted by
    ``get_frame_eval_capabilities``.  in CI we hit a subtle problem where the
    plugin runner (```uv run```) keeps Python processes alive across separate
    steps; the experimental 3.11 smoke check imports the module with the
    override enabled, setting ``_state.available`` to ``True``.  later the
    full-suite step runs with the override cleared, but the cached value stays
    ``True`` and ``enable_frame_eval`` subsequently reports success even though
    capabilities no longer permit the hook.  the result was the mysterious
    failing integration tests.

    to avoid this class of bug we always recompute the capability surface on
    each call, updating ``_state`` accordingly.  callers should therefore use
    this helper rather than trusting ``_state.available`` directly.
    """
    # recompute from the public helper so that the value is always in sync
    # with the current environment.  this mirrors what the Cython extension
    # would do at import-time, but we do it lazily so callers don't have to
    # worry about import-order or uv process reuse.
    caps = get_frame_eval_capabilities()
    _state.available = bool(caps.get("supports_eval_frame_hook", False))
    reason = caps.get("reason")
    _state.hook_reason = reason if isinstance(reason, str) and reason else None
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

    # make sure ``available`` is up-to-date in case the environment changed
    # since the module was imported (see ``is_frame_eval_available`` docstring)
    if not is_frame_eval_available():
        return False

    if (
        _state.setup_frame_eval({}) and _state.install_eval_frame_hook()
    ):  # Pass empty config by default
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
        _state.uninstall_eval_frame_hook()
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
        "hook": _state.get_eval_frame_hook_status(),
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


def install_eval_frame_hook() -> bool:
    """Install the low-level eval-frame hook controller."""
    return _state.install_eval_frame_hook()


def uninstall_eval_frame_hook() -> bool:
    """Uninstall the low-level eval-frame hook controller."""
    return _state.uninstall_eval_frame_hook()


def get_eval_frame_hook_status() -> dict[str, Any]:
    """Return low-level eval-frame hook status information."""
    return _state.get_eval_frame_hook_status()


def mark_thread_as_debugger_internal() -> None:
    """Mark the current thread as debugger-internal so frame eval skips it."""
    _state.mark_thread_as_debugger_internal()


def unmark_thread_as_debugger_internal() -> None:
    """Remove debugger-internal marking from the current thread."""
    _state.unmark_thread_as_debugger_internal()


def set_thread_skip_all(skip: bool) -> None:
    """Set whether current thread should skip all frames.

    Args:
        skip: True to skip all frames in this thread
    """
    _state.set_thread_skip_all(skip)
