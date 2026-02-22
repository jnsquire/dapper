"""
Frame tracing utilities for Dapper frame evaluation.

This module provides Python-level utilities for frame tracing, debugging,
and integration with Dapper's existing debugging infrastructure.
"""

from __future__ import annotations

# Standard library imports
import importlib.resources
import logging
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import Callable
from typing import TypedDict

# Local application imports
from dapper._frame_eval.cache_manager import get_breakpoints

# Set up logging
logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import os
    from types import CodeType
    from types import FrameType


class FrameInfo(TypedDict):
    """Type definition for frame information dictionary.

    Attributes:
        filename: The source file path
        lineno: The line number in the source file
        function: The name of the function where the frame is executing
        code_object: The code object being executed in this frame
        is_debugger_frame: Whether this frame is part of the debugger itself
        should_skip: Whether this frame should be skipped during debugging
    """

    filename: str
    lineno: int
    function: str
    code_object: CodeType
    is_debugger_frame: bool
    should_skip: bool


# Constants for better testability
DEBUGGER_PATHS = [
    "dapper/debugger_bdb.py",
    "dapper/server.py",
    "dapper/debug_launcher.py",
    "dapper/_frame_eval/",
    "site-packages/",
    "python3.",
]

STANDARD_LIBRARY_PATHS = [
    "lib/python",
    "Python/Lib",
    "importlib",
    "threading.py",
    "asyncio/",
]

DEBUGGER_FUNCTIONS = [
    "user_line",
    "user_exception",
    "user_call",
    "trace_dispatch",
    "_dispatch_line",
    "_dispatch_exception",
    "_dispatch_call",
]

# Global state for frame tracing
_tracing_enabled = False
_breakpoint_wrapper_template = None
_trace_function_cache: dict[tuple[int, str, int], Callable] = {}


class FrameTracingConfig:
    """Configuration for frame tracing."""

    def __init__(self, enabled: bool = False):
        self.enabled = enabled
        self.debugger_paths = DEBUGGER_PATHS
        self.standard_library_paths = STANDARD_LIBRARY_PATHS
        self.debugger_functions = DEBUGGER_FUNCTIONS

    @classmethod
    def from_dict(cls, config_dict: dict[str, Any]) -> FrameTracingConfig:
        """Create config from dictionary."""
        return cls(enabled=config_dict.get("enabled", False))


class PathHandler:
    """Handles path operations for frame tracing."""

    @staticmethod
    def normalize_path(filename: str | os.PathLike) -> str:
        """Normalize a file path.

        Args:
            filename: Path to normalize, can be string or path-like object

        Returns:
            Normalized absolute path as a string
        """
        try:
            path = Path(filename).absolute().resolve()
            return str(path)
        except Exception:
            # Return original path if normalization fails
            return str(filename)

    @staticmethod
    def is_debugger_path(filename: str | os.PathLike, debugger_paths: list[str]) -> bool:
        """Check if a filename contains debugger paths.

        Args:
            filename: Path to check
            debugger_paths: List of debugger path patterns to check against

        Returns:
            bool: True if any debugger path is found in the filename
        """
        path = Path(filename)
        return any(debug_path in str(path) for debug_path in debugger_paths)

    @staticmethod
    def is_standard_library_path(filename: str | os.PathLike, std_paths: list[str]) -> bool:
        """Check if a filename contains standard library paths.

        Args:
            filename: Path to check
            std_paths: List of standard library path patterns to check against

        Returns:
            bool: True if any standard library path is found in the filename
        """
        path = Path(filename)
        return any(std_path in str(path) for std_path in std_paths)

    @staticmethod
    def is_generated_code(filename: str) -> bool:
        """Check if filename represents generated code."""
        return bool(filename.startswith("<") and filename.endswith(">"))


class FrameEvaluator:
    """Evaluates frames to determine if they should be traced."""

    def __init__(self, config: FrameTracingConfig, path_handler: PathHandler):
        self._config = config
        self.path_handler = path_handler

    @property
    def config(self) -> FrameTracingConfig:
        """Get the current configuration."""
        return self._config

    def update_config(self, new_config: FrameTracingConfig) -> None:
        """Update the configuration.

        Args:
            new_config: New configuration to use
        """
        self._config = new_config

    def should_skip_frame(self, frame: FrameType) -> bool:
        """Determine if a frame should be skipped during frame evaluation.

        Args:
            frame: The frame to check

        Returns:
            bool: True if the frame should be skipped
        """
        filename = frame.f_code.co_filename

        # Skip frames from the debugger itself
        if self.path_handler.is_debugger_path(filename, self.config.debugger_paths):
            return True

        # Skip frames from standard library
        if self.path_handler.is_standard_library_path(
            filename,
            self.config.standard_library_paths,
        ):
            return True

        # Skip frames with no filename (like exec() or eval())
        if not filename or filename == "<string>":
            return True

        # Skip frames from generated code
        return self.path_handler.is_generated_code(filename)

    def is_debugger_frame(self, frame: FrameType) -> bool:
        """Check if a frame belongs to the debugger itself.

        Args:
            frame: The frame to check

        Returns:
            bool: True if the frame is from the debugger
        """
        filename = frame.f_code.co_filename
        function_name = frame.f_code.co_name

        # Check debugger module paths
        if self.path_handler.is_debugger_path(
            filename,
            self.config.debugger_paths[:4],
        ):  # Only core debugger paths
            return True

        # Check debugger function names
        return function_name in self.config.debugger_functions


class CodeWrapper:
    """Handles creation of code wrappers for debugging."""

    def __init__(self):
        self._template: str | None = None

    def _get_template(self) -> str:
        """Load and return the wrapper template from package resources.

        Returns:
            str: The template content as a string.

        Raises:
            RuntimeError: If the template cannot be loaded from package resources.
        """
        if self._template is None:
            try:
                # Load from package resources
                template_bytes = (
                    importlib.resources.files("dapper._frame_eval.resources.templates")
                    .joinpath("frame_wrapper.py.template")
                    .read_bytes()
                )
                self._template = template_bytes.decode("utf-8")
            except Exception as exc:
                msg = f"Failed to load frame evaluation template: {exc}"
                raise RuntimeError(msg) from exc
        return self._template

    def create_wrapper(self, line: int) -> str:
        """Create a code wrapper for debugging at a specific line.

        Args:
            line: The line number to create a wrapper for

        Returns:
            str: Python code string for the wrapper
        """
        template = self._get_template()
        return template.format(line=line)


class CacheManager:
    """Manages caching for trace functions and code objects."""

    def __init__(self):
        self._trace_function_cache: dict[tuple[int, str, int], Callable] = {}

    def get_cache_key(self, code_obj: CodeType) -> tuple[int, str, int]:
        """Generate a cache key for a code object."""
        return (id(code_obj), code_obj.co_filename, code_obj.co_firstlineno)

    def invalidate_code_cache(self, code_obj: CodeType) -> None:
        """Invalidate cached information for a code object.

        Args:
            code_obj: The code object to invalidate cache for
        """
        # Clear any cached breakpoint information
        if hasattr(code_obj, "_frame_eval_cache"):
            delattr(code_obj, "_frame_eval_cache")

        # Clear from global cache
        cache_key = self.get_cache_key(code_obj)
        self._trace_function_cache.pop(cache_key, None)

    def clear_all(self) -> None:
        """Clear all cached data."""
        self._trace_function_cache.clear()


# Global instances for backward compatibility
_path_handler = PathHandler()
_evaluator = FrameEvaluator(FrameTracingConfig(), _path_handler)  # Initialize with default config
_code_wrapper = CodeWrapper()
_cache_manager = CacheManager()


def create_pydev_trace_code_wrapper(line: int) -> str:
    """Create a code wrapper for debugging at a specific line.

    Args:
        line: The line number to create a wrapper for

    Returns:
        str: Python code string for the wrapper
    """
    return _code_wrapper.create_wrapper(line)


def update_globals_dict(globals_dict: dict[str, Any]) -> None:
    """Update the globals dictionary with debugging utilities.

    Args:
        globals_dict: The globals dictionary to update
    """
    # These globals are kept for backward compatibility
    # but we manage the frame evaluation state internally through _tracing_enabled
    globals_dict.update(
        {
            "_pydevd_frame_eval_active": True,  # For backward compatibility
            "_pydevd_frame_eval_line": None,
            "_pydevd_frame_eval_filename": None,
        },
    )


def should_skip_frame(frame: FrameType) -> bool:
    """Determine if a frame should be skipped during frame evaluation.

    Args:
        frame: The frame to check

    Returns:
        bool: True if the frame should be skipped
    """
    return _evaluator.should_skip_frame(frame)


def get_frame_filename(frame: FrameType) -> str:
    """Get the normalized filename for a frame.

    Args:
        frame: The frame to get the filename for

    Returns:
        str: Normalized filename
    """
    return _path_handler.normalize_path(frame.f_code.co_filename)


def is_debugger_frame(frame: FrameType) -> bool:
    """Check if a frame belongs to the debugger itself.

    Args:
        frame: The frame to check

    Returns:
        bool: True if the frame is from the debugger
    """
    return _evaluator.is_debugger_frame(frame)


def get_frame_info(frame: FrameType) -> FrameInfo:
    """Extract relevant information from a frame for debugging.

    Args:
        frame: The frame to extract info from

    Returns:
        FrameInfo: Frame information dictionary with frame details

    Raises:
        ValueError: If there's an error getting the frame filename

    Note:
        This function will raise a ValueError if there's an error getting the frame filename,
        as this is considered a critical error. Other errors will be caught and a basic
        frame info dictionary will be returned.
    """
    # Get filename - handle exceptions appropriately
    try:
        filename = get_frame_filename(frame)
        skip_frame = False
    except ValueError:
        # Re-raise ValueError as it's considered a critical error
        raise
    except Exception:
        # For other errors, use the original filename and mark for skipping
        filename = frame.f_code.co_filename
        skip_frame = True

    # Prepare frame info with common values
    try:
        is_debug = is_debugger_frame(frame)
        should_skip_flag = skip_frame or should_skip_frame(frame)
    except Exception:
        # Fall back to safe defaults if there's an error
        is_debug = False
        should_skip_flag = True

    # Construct and return the frame info
    return FrameInfo(
        filename=filename,
        lineno=frame.f_lineno,
        function=frame.f_code.co_name,
        code_object=frame.f_code,
        is_debugger_frame=is_debug,
        should_skip=should_skip_flag,
    )


def create_trace_function_wrapper(original_trace: Callable) -> Callable:
    """Create a wrapper for trace functions that integrates with frame evaluation.

    Args:
        original_trace: The original trace function to wrap

    Returns:
        Callable: Wrapped trace function
    """

    def frame_eval_trace_wrapper(frame: FrameType, event: str, arg: Any) -> Any:
        try:
            # Skip frames that should be ignored
            if should_skip_frame(frame):
                return original_trace(frame, event, arg)

            # Handle frame evaluation specific logic
            if event == "line" and _tracing_enabled:
                frame_info = get_frame_info(frame)
                if not frame_info["should_skip"]:
                    # Let frame evaluation handle this
                    return None

            # Call original trace function
            return original_trace(frame, event, arg)
        except Exception:
            # If anything fails, fall back to original trace
            return original_trace(frame, event, arg)

    return frame_eval_trace_wrapper


def invalidate_code_cache(code_obj: CodeType) -> None:
    """Invalidate cached information for a code object.

    Args:
        code_obj: The code object to invalidate cache for
    """
    _cache_manager.invalidate_code_cache(code_obj)


def get_breakpoint_lines_for_file(filename: str) -> set[int]:
    """Get all breakpoint lines for a given file.

    Args:
        filename: The filename to get breakpoints for

    Returns:
        Set of line numbers with breakpoints. Returns an empty set if no breakpoints are set.
    """
    # Try to get breakpoints from the cache
    breakpoints = get_breakpoints(filename)

    # Return breakpoints if found, otherwise return an empty set
    return set(breakpoints) if breakpoints is not None else set()


def optimize_code_for_debugging(code_obj: type) -> type:
    """Optimize a code object for debugging with frame evaluation.

    Args:
        code_obj: The code object to optimize

    Returns:
        CodeType: Optimized code object
    """
    # For now, return the original code object
    # Optimization will be implemented in bytecode modification step
    return code_obj


def setup_frame_tracing(config: dict[str, Any]) -> bool:
    """Set up frame tracing with the given configuration.

    Args:
        config: Configuration dictionary

    Returns:
        bool: True if setup was successful
    """
    global _tracing_enabled, _evaluator  # noqa: PLW0602, PLW0603

    try:
        # Update evaluator with new config
        _evaluator.update_config(FrameTracingConfig.from_dict(config))
        _tracing_enabled = _evaluator.config.enabled

        # Set up any additional configuration
        if _tracing_enabled:
            # Initialize any required state
            pass

        return True  # noqa: TRY300
    except Exception:
        return False


def cleanup_frame_tracing() -> None:
    """Clean up frame tracing state."""
    global _tracing_enabled  # noqa: PLW0603

    # Reset tracing state
    _tracing_enabled = False

    # Clear all caches
    _trace_function_cache.clear()
    _cache_manager.clear_all()


# Expose classes for testing
__all__ = [
    "CacheManager",
    "CodeWrapper",
    "FrameEvaluator",
    "FrameTracingConfig",
    "PathHandler",
    "cleanup_frame_tracing",
    "create_pydev_trace_code_wrapper",
    "create_trace_function_wrapper",
    "get_breakpoint_lines_for_file",
    "get_frame_filename",
    "get_frame_info",
    "invalidate_code_cache",
    "is_debugger_frame",
    "optimize_code_for_debugging",
    "setup_frame_tracing",
    "should_skip_frame",
    "update_globals_dict",
]
