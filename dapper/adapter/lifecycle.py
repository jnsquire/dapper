"""Backend lifecycle management system.

This module provides standardized lifecycle management for all debugger backends,
including state tracking, transitions, and resource cleanup.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from enum import Enum
import logging
from typing import TYPE_CHECKING
from typing import ClassVar

if TYPE_CHECKING:
    from typing import Callable

logger = logging.getLogger(__name__)


class BackendLifecycleState(Enum):
    """Lifecycle states for debugger backends."""

    UNINITIALIZED = "uninitialized"
    INITIALIZING = "initializing"
    READY = "ready"
    BUSY = "busy"
    ERROR = "error"
    TERMINATING = "terminating"
    TERMINATED = "terminated"


class LifecycleTransitionError(Exception):
    """Raised when an invalid lifecycle state transition is attempted."""

    def __init__(self, from_state: BackendLifecycleState, to_state: BackendLifecycleState) -> None:
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"Invalid lifecycle transition: {from_state.value} -> {to_state.value}")


class LifecycleManager:
    """Manages lifecycle state transitions and resource cleanup for backends."""

    # Valid state transitions
    _VALID_TRANSITIONS: ClassVar[dict[BackendLifecycleState, set[BackendLifecycleState]]] = {
        BackendLifecycleState.UNINITIALIZED: {
            BackendLifecycleState.INITIALIZING,
            BackendLifecycleState.TERMINATED,
        },
        BackendLifecycleState.INITIALIZING: {
            BackendLifecycleState.READY,
            BackendLifecycleState.ERROR,
            BackendLifecycleState.TERMINATING,
        },
        BackendLifecycleState.READY: {
            BackendLifecycleState.BUSY,
            BackendLifecycleState.ERROR,
            BackendLifecycleState.TERMINATING,
        },
        BackendLifecycleState.BUSY: {
            BackendLifecycleState.READY,
            BackendLifecycleState.ERROR,
            BackendLifecycleState.TERMINATING,
        },
        BackendLifecycleState.ERROR: {
            BackendLifecycleState.READY,  # Recovery
            BackendLifecycleState.TERMINATING,
        },
        BackendLifecycleState.TERMINATING: {
            BackendLifecycleState.TERMINATED,
            BackendLifecycleState.ERROR,  # Failed termination
        },
        BackendLifecycleState.TERMINATED: set(),  # Final state
    }

    def __init__(self, backend_name: str) -> None:
        """Initialize the lifecycle manager.

        Args:
            backend_name: Name of the backend for logging
        """
        self._backend_name = backend_name
        self._state = BackendLifecycleState.UNINITIALIZED
        self._lock = asyncio.Lock()
        self._cleanup_callbacks: list[Callable[[], None]] = []
        self._error_info: str | None = None

    @property
    def state(self) -> BackendLifecycleState:
        """Get the current lifecycle state."""
        return self._state

    @property
    def is_ready(self) -> bool:
        """Check if the backend is ready for operations."""
        return self._state in (BackendLifecycleState.READY, BackendLifecycleState.BUSY)

    @property
    def is_available(self) -> bool:
        """Check if the backend is available (not terminated or in error)."""
        return self._state not in (
            BackendLifecycleState.TERMINATED,
            BackendLifecycleState.ERROR,
            BackendLifecycleState.TERMINATING,
        )

    @property
    def error_info(self) -> str | None:
        """Get information about the last error."""
        return self._error_info

    async def transition_to(
        self, new_state: BackendLifecycleState, error_info: str | None = None
    ) -> None:
        """Transition to a new lifecycle state.

        Args:
            new_state: The target state
            error_info: Optional error information for ERROR state

        Raises:
            LifecycleTransitionError: If the transition is invalid
        """
        async with self._lock:
            if new_state not in self._VALID_TRANSITIONS[self._state]:
                raise LifecycleTransitionError(self._state, new_state)

            old_state = self._state
            self._state = new_state

            if new_state == BackendLifecycleState.ERROR:
                self._error_info = error_info or "Unknown error"
            elif new_state != BackendLifecycleState.ERROR:
                self._error_info = None

            logger.debug(f"{self._backend_name}: {old_state.value} -> {new_state.value}")

    def add_cleanup_callback(self, callback: Callable[[], None]) -> None:
        """Add a cleanup callback to be called during termination.

        Args:
            callback: Function to call during cleanup
        """
        self._cleanup_callbacks.append(callback)

    async def cleanup(self) -> None:
        """Execute all registered cleanup callbacks."""
        logger.debug(
            f"{self._backend_name}: Running {len(self._cleanup_callbacks)} cleanup callbacks"
        )

        for callback in self._cleanup_callbacks:
            try:
                callback()
            except Exception:  # noqa: PERF203
                logger.exception(f"{self._backend_name}: Cleanup callback failed")

        self._cleanup_callbacks.clear()

    @asynccontextmanager
    async def operation_context(self, operation_name: str):
        """Context manager for backend operations with automatic state management.

        If the backend is still UNINITIALIZED, it is automatically transitioned
        through INITIALIZING to READY before the operation proceeds.

        Args:
            operation_name: Name of the operation for logging
        """
        # Auto-transition from UNINITIALIZED -> INITIALIZING -> READY
        if self._state == BackendLifecycleState.UNINITIALIZED:
            await self.transition_to(BackendLifecycleState.INITIALIZING)
            await self.transition_to(BackendLifecycleState.READY)

        if not self.is_ready:
            error_msg = f"Backend not ready for operation: {operation_name}"
            raise RuntimeError(error_msg)

        await self.transition_to(BackendLifecycleState.BUSY)
        try:
            yield
        except Exception as e:
            await self.transition_to(BackendLifecycleState.ERROR, str(e))
            raise
        finally:
            if self._state == BackendLifecycleState.BUSY:
                await self.transition_to(BackendLifecycleState.READY)

    async def initialize(self) -> None:
        """Initialize the backend lifecycle."""
        await self.transition_to(BackendLifecycleState.INITIALIZING)

    async def mark_ready(self) -> None:
        """Mark the backend as ready for operations."""
        await self.transition_to(BackendLifecycleState.READY)

    async def mark_error(self, error_info: str) -> None:
        """Mark the backend as in error state.

        Args:
            error_info: Description of the error
        """
        await self.transition_to(BackendLifecycleState.ERROR, error_info)

    async def begin_termination(self) -> None:
        """Begin the termination process."""
        await self.transition_to(BackendLifecycleState.TERMINATING)

    async def complete_termination(self) -> None:
        """Complete the termination process."""
        await self.cleanup()
        await self.transition_to(BackendLifecycleState.TERMINATED)

    async def recover(self) -> None:
        """Attempt to recover from error state."""
        if self._state != BackendLifecycleState.ERROR:
            error_msg = f"Cannot recover from state: {self._state.value}"
            raise RuntimeError(error_msg)

        await self.transition_to(BackendLifecycleState.READY)
