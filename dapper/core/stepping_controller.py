"""
SteppingController: Centralized stepping state management.

This module provides logic for:
1. Managing stepping flags (stepping, stop_on_entry)
2. Determining stop reasons based on current state
3. Consuming stepping state after stops
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import types


class StopReason(str, Enum):
    """DAP stop reasons."""

    BREAKPOINT = "breakpoint"
    STEP = "step"
    ENTRY = "entry"
    EXCEPTION = "exception"
    PAUSE = "pause"
    DATA_BREAKPOINT = "data breakpoint"
    FUNCTION_BREAKPOINT = "function breakpoint"


@dataclass
class SteppingController:
    """Manages stepping state for the debugger.

    This class consolidates stepping-related state that was previously
    scattered in DebuggerBDB:
    - stepping: whether we're in step mode
    - stop_on_entry: whether to stop at program entry
    - current_frame: the frame we're currently stopped at

    The controller provides a clean API for:
    - Setting stepping modes
    - Getting stop reasons
    - Consuming stepping state after a stop

    Attributes:
        stepping: Whether the debugger is in stepping mode.
        stop_on_entry: Whether to stop at program entry.
        current_frame: The frame we're currently stopped at (if any).
    """

    stepping: bool = False
    stop_on_entry: bool = False
    current_frame: types.FrameType | None = None

    def is_stepping(self) -> bool:
        """Check if currently in stepping mode."""
        return self.stepping

    def set_stepping(self, value: bool = True) -> None:
        """Set stepping mode."""
        self.stepping = value

    def set_stop_on_entry(self, value: bool = True) -> None:
        """Set stop on entry mode."""
        self.stop_on_entry = value

    def set_current_frame(self, frame: types.FrameType) -> None:
        """Set the current frame."""
        self.current_frame = frame

    def get_stop_reason(self) -> StopReason:
        """Get the stop reason based on current state.

        Returns the appropriate stop reason, prioritizing:
        1. stop_on_entry -> "entry"
        2. stepping -> "step"
        3. default -> "breakpoint"

        Note: This does NOT consume the state. Call consume_stop_state()
        after emitting the stopped event.
        """
        if self.stop_on_entry:
            return StopReason.ENTRY
        if self.stepping:
            return StopReason.STEP
        return StopReason.BREAKPOINT

    def consume_stop_state(self) -> StopReason:
        """Get the stop reason and consume the stepping state.

        This is a convenience method that combines get_stop_reason()
        with clearing the appropriate flags.

        Returns:
            The stop reason that was active.
        """
        reason = self.get_stop_reason()

        # Consume the state
        if self.stop_on_entry:
            self.stop_on_entry = False
        elif self.stepping:
            self.stepping = False

        return reason

    def clear(self) -> None:
        """Clear all stepping state."""
        self.stepping = False
        self.stop_on_entry = False
        self.current_frame = None

    def request_step(self) -> None:
        """Request a step operation (step into).

        Sets the stepping flag so the next line stop will report
        reason="step" instead of reason="breakpoint".
        """
        self.stepping = True


__all__ = ["SteppingController", "StopReason"]
