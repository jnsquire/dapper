"""
ExceptionHandler: Centralized exception breakpoint handling.

This module provides logic for:
1. Determining whether to break on an exception
2. Building DAP-compliant exception info structures
3. Managing per-thread exception state
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
import traceback
from typing import TYPE_CHECKING
from typing import Any

from dapper.core.debug_helpers import frame_may_handle_exception

if TYPE_CHECKING:
    import types

    from dapper.protocol.debugger_protocol import ExceptionInfo


@dataclass
class ExceptionBreakpointConfig:
    """Configuration for exception breakpoints.

    Attributes:
        break_on_raised: Break when any exception is raised.
        break_on_uncaught: Break only on uncaught exceptions.
    """

    break_on_raised: bool = False
    break_on_uncaught: bool = False

    def is_enabled(self) -> bool:
        """Check if any exception breakpoint is enabled."""
        return self.break_on_raised or self.break_on_uncaught

    def set_from_filters(self, filters: list[str] | set[str]) -> None:
        """Configure from DAP exception filter IDs.

        Args:
            filters: List of filter IDs like ["raised", "uncaught"].
        """
        self.break_on_raised = "raised" in filters
        self.break_on_uncaught = "uncaught" in filters


@dataclass
class ExceptionHandler:
    """Handles exception breakpoint logic and state.

    This class consolidates exception handling that was previously
    scattered in DebuggerBDB:
    - exception_breakpoints_raised/uncaught flags
    - current_exception_info storage
    - Decision logic for when to break
    - Building ExceptionInfo structures

    Attributes:
        config: Exception breakpoint configuration.
        exception_info_by_thread: Per-thread exception info storage.
    """

    config: ExceptionBreakpointConfig = field(default_factory=ExceptionBreakpointConfig)
    exception_info_by_thread: dict[int, ExceptionInfo] = field(default_factory=dict)

    def should_break(
        self,
        frame: types.FrameType | Any,
    ) -> bool:
        """Determine if execution should break for this exception.

        Args:
            frame: The frame where the exception occurred.

        Returns:
            True if we should break on this exception.
        """
        if not self.config.is_enabled():
            return False

        # "raised" mode breaks on all exceptions
        if self.config.break_on_raised:
            return True

        # "uncaught" mode only breaks if exception won't be handled
        if self.config.break_on_uncaught:
            # Ask the helper whether the current frame will handle this exception
            # True or None means it's handled, so we don't break
            res = frame_may_handle_exception(frame)
            return res is False

        return False

    def get_break_mode(self) -> str:
        """Get the DAP break mode string.

        Returns:
            "always" if break_on_raised, "unhandled" otherwise.
        """
        return "always" if self.config.break_on_raised else "unhandled"

    def build_exception_info(
        self,
        exc_info: tuple[type[BaseException], BaseException, Any],
        frame: types.FrameType | Any,
    ) -> ExceptionInfo:
        """Build a DAP ExceptionInfo structure.

        Args:
            exc_info: Tuple of (exc_type, exc_value, exc_traceback).
            frame: The frame where the exception occurred.

        Returns:
            ExceptionInfo dict suitable for DAP protocol.
        """
        exc_type, exc_value, exc_traceback = exc_info
        stack_trace = traceback.format_exception(exc_type, exc_value, exc_traceback)

        return {
            "exceptionId": exc_type.__name__,
            "description": str(exc_value),
            "breakMode": self.get_break_mode(),
            "details": {
                "message": str(exc_value),
                "typeName": exc_type.__name__,
                "fullTypeName": f"{exc_type.__module__}.{exc_type.__name__}",
                "source": frame.f_code.co_filename if hasattr(frame, "f_code") else "<unknown>",
                "stackTrace": stack_trace,
            },
        }

    def get_exception_text(
        self,
        exc_info: tuple[type[BaseException], BaseException, Any],
    ) -> str:
        """Get a short text description for the stopped event.

        Args:
            exc_info: Tuple of (exc_type, exc_value, exc_traceback).

        Returns:
            String like "ValueError: invalid value".
        """
        exc_type, exc_value, _ = exc_info
        return f"{exc_type.__name__}: {exc_value!s}"

    def store_exception_info(self, thread_id: int, info: ExceptionInfo) -> None:
        """Store exception info for a thread.

        Args:
            thread_id: The thread ID.
            info: The ExceptionInfo to store.
        """
        self.exception_info_by_thread[thread_id] = info

    def get_exception_info(self, thread_id: int) -> ExceptionInfo | None:
        """Get stored exception info for a thread.

        Args:
            thread_id: The thread ID.

        Returns:
            The stored ExceptionInfo, or None if not found.
        """
        return self.exception_info_by_thread.get(thread_id)

    def clear_exception_info(self, thread_id: int) -> None:
        """Clear stored exception info for a thread.

        Args:
            thread_id: The thread ID.
        """
        self.exception_info_by_thread.pop(thread_id, None)

    def clear_all(self) -> None:
        """Clear all stored exception info."""
        self.exception_info_by_thread.clear()


__all__ = ["ExceptionBreakpointConfig", "ExceptionHandler"]
