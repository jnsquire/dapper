"""Generic backend abstraction for frame evaluation.

This module defines the superset interface used by the frame-eval manager to
interact with any backend implementation, whether tracing-based or
"eval-frame"-based.  The existing ``TracingBackend`` interface lives in a
separate module and subclasses from ``FrameEvalBackend`` so that legacy code
continues to work without change.

Conceptually, a backend is responsible for integrating with a debugger
instance, responding to breakpoint updates and stepping commands, and
reporting statistics.  Future eval-frame backends may implement a more direct
interpreter integration while still conforming to this API.
"""

from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from dapper._frame_eval.debugger_integration import IntegrationStatistics


class FrameEvalBackend(ABC):
    """Abstract base class for all frame-evaluation backends.

    The methods here mirror the ones previously defined in
    :class:`TracingBackend`; that class now simply subclasses
    ``FrameEvalBackend``.  Backends should be safe to ``install`` multiple
    times and should leave process-global state clean when ``shutdown`` is
    called.
    """

    @abstractmethod
    def install(self, debugger_instance: object) -> None:  # pragma: no cover - interface
        """Attach the backend to a concrete debugger instance."""

    @abstractmethod
    def shutdown(self) -> None:  # pragma: no cover - interface
        """Tear down any process-global state and detach from debugger."""

    @abstractmethod
    def update_breakpoints(
        self, filepath: str, lines: set[int]
    ) -> None:  # pragma: no cover - interface
        """Notify backend of breakpoint set changes for a file."""

    @abstractmethod
    def set_stepping(self, mode: Any) -> None:  # pragma: no cover - interface
        """Set the current stepping mode (STEP_IN, STEP_OVER, etc.)."""

    @abstractmethod
    def set_exception_breakpoints(
        self, filters: list[str]
    ) -> None:  # pragma: no cover - interface
        """Configure exception-breakpoint filtering."""

    @abstractmethod
    def get_statistics(
        self,
    ) -> IntegrationStatistics | dict[str, Any]:  # pragma: no cover - interface
        """Return diagnostic statistics for the backend."""
