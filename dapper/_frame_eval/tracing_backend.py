"""Tracing backend abstraction for frame evaluation.

Defines the interface for pluggable tracing backends (settrace-based and
sys.monitoring-based). Implementations should be thread-safe where noted.
"""

from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from dapper._frame_eval.debugger_integration import IntegrationStatistics


class TracingBackend(ABC):
    """Abstract tracing backend.

    Concrete backends must implement lifecycle and control operations used by
    the frame-eval integration.
    """

    @abstractmethod
    def install(self, debugger_instance: object) -> None:
        """Install the backend for the given debugger instance.

        Called when frame-eval integration is being enabled. Must be safe to
        call multiple times (idempotent) for the same debugger instance.
        """

    @abstractmethod
    def shutdown(self) -> None:
        """Shutdown the backend and unregister any callbacks.

        Should restore process-global state so that a fresh `install()` can
        be performed later if desired.
        """

    @abstractmethod
    def update_breakpoints(self, filepath: str, lines: set[int]) -> None:
        """Update the set of breakpoints for a source file.

        Implementations should apply per-code-object or global event changes
        required to monitor the given `lines` in `filepath`.
        """

    @abstractmethod
    def set_stepping(self, mode: Any) -> None:
        """Set the stepping mode (STEP_IN / STEP_OVER / CONTINUE / ...)."""

    @abstractmethod
    def set_exception_breakpoints(self, filters: list[str]) -> None:
        """Configure exception breakpoint filters used by the backend."""

    @abstractmethod
    def get_statistics(self) -> IntegrationStatistics | dict[str, Any]:
        """Return diagnostic statistics for this backend.

        Prefer returning an `IntegrationStatistics` mapping when available.
        """
