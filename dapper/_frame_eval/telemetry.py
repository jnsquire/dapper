"""Telemetry and reason codes for frame-eval fallback and error paths."""

from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
import json
import threading
import time
from typing import Any


@dataclass
class FrameEvalTelemetryEvent:
    """Single telemetry event entry."""

    timestamp: float
    reason_code: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class FrameEvalReasonCounts:
    """Explicit counters for each known FrameEval reason code.

    The class implements a small mapping-like surface so existing call sites
    can index/get by string reason-code, and also provides an `as_dict()` helper for
    serialization and tests.
    """

    auto_integration_failed: int = 0
    bytecode_injection_failed: int = 0
    bytecode_optimization_failed: int = 0
    bytecode_optimization_file_read_failed: int = 0
    integration_bdb_failed: int = 0
    integration_remove_failed: int = 0
    hot_reload_failed: int = 0
    hot_reload_succeeded: int = 0
    py_debugger_breakpoint_hook_failed: int = 0
    py_debugger_integration_failed: int = 0
    py_debugger_trace_hook_failed: int = 0
    selective_tracing_analysis_failed: int = 0

    def as_dict(self) -> dict[str, int]:
        # Explicit, literal mapping from enum value -> dataclass field.
        out = {
            "AUTO_INTEGRATION_FAILED": self.auto_integration_failed,
            "BYTECODE_INJECTION_FAILED": self.bytecode_injection_failed,
            "BYTECODE_OPTIMIZATION_FAILED": self.bytecode_optimization_failed,
            "BYTECODE_OPTIMIZATION_FILE_READ_FAILED": self.bytecode_optimization_file_read_failed,
            "HOT_RELOAD_FAILED": self.hot_reload_failed,
            "HOT_RELOAD_SUCCEEDED": self.hot_reload_succeeded,
            "INTEGRATION_BDB_FAILED": self.integration_bdb_failed,
            "INTEGRATION_REMOVE_FAILED": self.integration_remove_failed,
            "PY_DEBUGGER_BREAKPOINT_HOOK_FAILED": self.py_debugger_breakpoint_hook_failed,
            "PY_DEBUGGER_INTEGRATION_FAILED": self.py_debugger_integration_failed,
            "PY_DEBUGGER_TRACE_HOOK_FAILED": self.py_debugger_trace_hook_failed,
            "SELECTIVE_TRACING_ANALYSIS_FAILED": self.selective_tracing_analysis_failed,
        }

        # Preserve original behaviour for empty state: return empty dict
        # when no counters are set (keeps some existing tests/simple prints tidy).
        if all(v == 0 for v in out.values()):
            return {}
        return out


@dataclass
class FrameEvalTelemetrySnapshot:
    """Telemetry snapshot payload returned to callers."""

    reason_counts: FrameEvalReasonCounts = field(default_factory=FrameEvalReasonCounts)
    recent_events: list[FrameEvalTelemetryEvent] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "reason_counts": self.reason_counts.as_dict(),
            "recent_events": [asdict(e) for e in self.recent_events],
        }

    def as_json(self) -> str:
        """Return a JSON string for diagnostic UIs/logs/tests."""
        return json.dumps(self.as_dict(), default=str)


class FrameEvalTelemetry:
    """Thread-safe telemetry collector for frame evaluation subsystem."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # Use structured counters to avoid repeated dict<->dataclass conversions.
        self._reason_counts: FrameEvalReasonCounts = FrameEvalReasonCounts()
        self._recent_events: list[FrameEvalTelemetryEvent] = []
        self._max_recent_events = 50

    def _record(self, reason_code: str, attr_name: str, **kwargs: Any) -> None:
        """Record a reason-code event with optional context."""
        event = FrameEvalTelemetryEvent(
            timestamp=time.time(),
            reason_code=reason_code,
            context=kwargs,
        )

        with self._lock:
            if hasattr(self._reason_counts, attr_name):
                setattr(
                    self._reason_counts,
                    attr_name,
                    getattr(self._reason_counts, attr_name) + 1,
                )

            self._recent_events.append(event)
            if len(self._recent_events) > self._max_recent_events:
                self._recent_events = self._recent_events[-self._max_recent_events :]

    def record_auto_integration_failed(self, **kwargs: Any) -> None:
        self._record("AUTO_INTEGRATION_FAILED", "auto_integration_failed", **kwargs)

    def record_bytecode_injection_failed(self, **kwargs: Any) -> None:
        self._record("BYTECODE_INJECTION_FAILED", "bytecode_injection_failed", **kwargs)

    def record_bytecode_optimization_failed(self, **kwargs: Any) -> None:
        self._record("BYTECODE_OPTIMIZATION_FAILED", "bytecode_optimization_failed", **kwargs)

    def record_bytecode_optimization_file_read_failed(self, **kwargs: Any) -> None:
        self._record(
            "BYTECODE_OPTIMIZATION_FILE_READ_FAILED",
            "bytecode_optimization_file_read_failed",
            **kwargs,
        )

    def record_integration_bdb_failed(self, **kwargs: Any) -> None:
        self._record("INTEGRATION_BDB_FAILED", "integration_bdb_failed", **kwargs)

    def record_integration_remove_failed(self, **kwargs: Any) -> None:
        self._record("INTEGRATION_REMOVE_FAILED", "integration_remove_failed", **kwargs)

    def record_hot_reload_failed(self, **kwargs: Any) -> None:
        self._record("HOT_RELOAD_FAILED", "hot_reload_failed", **kwargs)

    def record_hot_reload_succeeded(self, **kwargs: Any) -> None:
        self._record("HOT_RELOAD_SUCCEEDED", "hot_reload_succeeded", **kwargs)

    def record_py_debugger_breakpoint_hook_failed(self, **kwargs: Any) -> None:
        self._record(
            "PY_DEBUGGER_BREAKPOINT_HOOK_FAILED",
            "py_debugger_breakpoint_hook_failed",
            **kwargs,
        )

    def record_py_debugger_integration_failed(self, **kwargs: Any) -> None:
        self._record("PY_DEBUGGER_INTEGRATION_FAILED", "py_debugger_integration_failed", **kwargs)

    def record_py_debugger_trace_hook_failed(self, **kwargs: Any) -> None:
        self._record("PY_DEBUGGER_TRACE_HOOK_FAILED", "py_debugger_trace_hook_failed", **kwargs)

    def record_selective_tracing_analysis_failed(self, **kwargs: Any) -> None:
        self._record(
            "SELECTIVE_TRACING_ANALYSIS_FAILED",
            "selective_tracing_analysis_failed",
            **kwargs,
        )

    def snapshot(self) -> FrameEvalTelemetrySnapshot:
        """Return a stable snapshot of telemetry data."""
        with self._lock:
            return FrameEvalTelemetrySnapshot(
                reason_counts=FrameEvalReasonCounts(**asdict(self._reason_counts)),
                recent_events=list(self._recent_events),
            )

    def clear(self) -> None:
        """Reset all telemetry state."""
        with self._lock:
            self._reason_counts = FrameEvalReasonCounts()
            self._recent_events.clear()


telemetry = FrameEvalTelemetry()


def get_frame_eval_telemetry() -> FrameEvalTelemetrySnapshot:
    """Return global telemetry snapshot."""
    return telemetry.snapshot()


def reset_frame_eval_telemetry() -> None:
    """Reset global telemetry."""
    telemetry.clear()
