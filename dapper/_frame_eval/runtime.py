"""Runtime composition root for frame evaluation subsystems."""

from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
import threading
from typing import Any

from dapper._frame_eval.cache_manager import CacheStatistics
from dapper._frame_eval.cache_manager import clear_all_caches
from dapper._frame_eval.cache_manager import get_cache_statistics
from dapper._frame_eval.condition_evaluator import get_condition_evaluator
from dapper._frame_eval.config import FrameEvalConfig
from dapper._frame_eval.debugger_integration import IntegrationStatistics
from dapper._frame_eval.debugger_integration import get_integration_bridge
from dapper._frame_eval.selective_tracer import disable_selective_tracing
from dapper._frame_eval.selective_tracer import get_trace_manager
from dapper._frame_eval.telemetry import FrameEvalTelemetrySnapshot
from dapper._frame_eval.telemetry import get_frame_eval_telemetry


@dataclass
class FrameEvalRuntimeConfig:
    """Structured runtime configuration view returned by `FrameEvalRuntime.status()`.

    Note: this is a thin representation intended for diagnostics and tooling.
    """

    enabled: bool = True
    fallback_to_tracing: bool = True
    debug: bool = False
    cache_size: int = 0
    optimize: bool = False
    timeout: float = 0.0
    conditional_breakpoints_enabled: bool = False
    condition_budget_s: float = 0.0

    @classmethod
    def from_frame_eval_config(cls, cfg: FrameEvalConfig) -> FrameEvalRuntimeConfig:
        """Create a runtime-view config directly from a FrameEvalConfig instance.

        Avoids the intermediate dict conversion and is slightly more efficient
        and type-safe.
        """
        return cls(
            enabled=cfg.enabled,
            fallback_to_tracing=cfg.fallback_to_tracing,
            debug=cfg.debug,
            cache_size=cfg.cache_size,
            optimize=cfg.optimize,
            timeout=cfg.timeout,
            conditional_breakpoints_enabled=cfg.conditional_breakpoints_enabled,
            condition_budget_s=cfg.condition_budget_s,
        )


@dataclass
class FrameEvalRuntimeStatus:
    """High-level runtime status payload."""

    initialized: bool
    config: FrameEvalRuntimeConfig
    tracing_enabled: bool

    def as_dict(self) -> dict[str, Any]:
        """Return a primitive dict representation (suitable for JSON/UI)."""
        return {
            "initialized": self.initialized,
            "config": asdict(self.config),
            "tracing_enabled": self.tracing_enabled,
        }


@dataclass
class FrameEvalRuntimeStats:
    """Runtime subsystem statistics payload."""

    initialized: bool
    cache_stats: CacheStatistics
    trace_stats: dict[str, Any]
    integration_stats: IntegrationStatistics
    telemetry: FrameEvalTelemetrySnapshot

    def as_dict(self) -> dict[str, Any]:
        """Return a primitive dict representation (suitable for JSON/UI)."""
        return {
            "initialized": self.initialized,
            "cache_stats": self.cache_stats,
            "trace_stats": self.trace_stats,
            "integration_stats": self.integration_stats,
            "telemetry": self.telemetry.as_dict(),
        }


class FrameEvalRuntime:
    """Composes and manages runtime frame-eval subsystems."""

    def __init__(self, config: FrameEvalConfig | None = None) -> None:
        self._lock = threading.RLock()
        self._initialized = False
        self._config = FrameEvalConfig.from_dict((config or FrameEvalConfig()).to_dict())

    @property
    def initialized(self) -> bool:
        """Whether runtime has been initialized."""
        return self._initialized

    @property
    def config(self) -> FrameEvalConfig:
        """Current runtime configuration."""
        return self._config

    def initialize(self, config: dict[str, Any] | FrameEvalConfig | None = None) -> bool:
        """Initialize runtime with provided configuration."""
        with self._lock:
            if config is not None:
                if isinstance(config, FrameEvalConfig):
                    self._config = FrameEvalConfig.from_dict(config.to_dict())
                elif isinstance(config, dict):
                    self._config = FrameEvalConfig.from_dict(config)
                else:
                    return False

            self._initialized = True

            # Propagate condition-evaluator settings to the global singleton.
            evaluator = get_condition_evaluator()
            evaluator.enabled = self._config.conditional_breakpoints_enabled
            evaluator._budget_s = self._config.condition_budget_s  # noqa: SLF001

            return True

    def shutdown(self) -> None:
        """Shutdown runtime-managed components."""
        with self._lock:
            disable_selective_tracing()
            clear_all_caches()
            self._initialized = False

    def update_breakpoints(self, filename: str, lines: set[int]) -> None:
        """Update breakpoints through the trace manager."""
        with self._lock:
            get_trace_manager().update_file_breakpoints(filename, lines)

    def get_stats(self) -> FrameEvalRuntimeStats:
        """Return runtime subsystem statistics."""
        trace_manager = get_trace_manager()
        integration_bridge = get_integration_bridge()

        return FrameEvalRuntimeStats(
            initialized=self._initialized,
            cache_stats=get_cache_statistics(),
            trace_stats=trace_manager.get_statistics(),
            integration_stats=integration_bridge.get_integration_statistics(),
            telemetry=get_frame_eval_telemetry(),
        )

    def status(self) -> FrameEvalRuntimeStatus:
        """Return high-level runtime status."""
        trace_manager = get_trace_manager()
        cfg = FrameEvalRuntimeConfig.from_frame_eval_config(self._config)
        return FrameEvalRuntimeStatus(
            initialized=self._initialized,
            config=cfg,
            tracing_enabled=trace_manager.is_enabled(),
        )
