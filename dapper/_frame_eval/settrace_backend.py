# ruff: noqa: PLC0415
"""Settrace-based tracing backend that wraps the existing frame-eval
integration (selective tracing + bytecode modifier).

This backend keeps current behaviour but exposes the `TracingBackend`
interface so a `SysMonitoringBackend` can be introduced alongside it.
"""

from __future__ import annotations

from typing import Any

from dapper._frame_eval.debugger_integration import IntegrationStatistics
from dapper._frame_eval.debugger_integration import configure_integration
from dapper._frame_eval.debugger_integration import integrate_debugger_bdb
from dapper._frame_eval.debugger_integration import integrate_py_debugger
from dapper._frame_eval.selective_tracer import update_breakpoints as _update_breakpoints
from dapper._frame_eval.tracing_backend import TracingBackend


class SettraceBackend(TracingBackend):
    def __init__(self) -> None:
        self._installed = False
        self._debugger = None

    def install(self, debugger_instance: object) -> None:
        """Integrate the existing frame-eval system with the debugger."""
        # Choose appropriate integration helper depending on debugger shape
        self._debugger = debugger_instance
        # Try DebuggerBDB integration first, then PyDebugger-style
        integrated = False
        try:
            integrated = integrate_debugger_bdb(debugger_instance)
        except Exception:
            integrated = False

        if not integrated:
            try:
                integrated = integrate_py_debugger(debugger_instance)
            except Exception:
                integrated = False

        if integrated:
            self._installed = True

    def shutdown(self) -> None:
        """Remove integration; mostly a no-op since integration removal is
        handled by `debugger_integration.remove_integration` when needed.
        """
        if self._installed and self._debugger is not None:
            try:
                # Use the public removal helper if available
                from dapper._frame_eval.debugger_integration import remove_integration

                remove_integration(self._debugger)
            except Exception:
                # Best-effort only
                pass
        self._installed = False
        self._debugger = None

    def update_breakpoints(self, filepath: str, lines: set[int]) -> None:
        """Forward breakpoint updates to the existing selective tracer."""
        try:
            _update_breakpoints(filepath, lines)
        except Exception:
            # Best-effort: do not raise to avoid breaking debugger control flow
            pass

    def set_stepping(self, mode: Any) -> None:  # noqa: ARG002
        """Set stepping mode via configuration hook where possible.

        The legacy settrace path uses the debugger's internal stepping logic;
        we expose a no-op / best-effort hook here so callers can use the
        TracingBackend API uniformly.
        """
        try:
            # Propagate stepping preference into integration configuration
            configure_integration(selective_tracing=True)
        except Exception:
            pass

    def set_exception_breakpoints(self, filters: list[str]) -> None:  # noqa: ARG002
        # No-op: the existing exception handling is managed by the debugger
        # core (BreakpointResolver / ExceptionHandler).
        return

    def get_statistics(self) -> IntegrationStatistics:
        # The imports below are intentionally inside the method to avoid a
        # heavy upfront dependency when this backend is instantiated but
        # statistics are never requested.  PLC0415 is suppressed accordingly.
        from dapper._frame_eval.cache_manager import BreakpointCacheStats
        from dapper._frame_eval.cache_manager import CacheStatistics
        from dapper._frame_eval.cache_manager import FuncCodeCacheStats
        from dapper._frame_eval.cache_manager import GlobalCacheStats
        from dapper._frame_eval.debugger_integration import get_integration_statistics
        from dapper._frame_eval.telemetry import FrameEvalReasonCounts
        from dapper._frame_eval.telemetry import FrameEvalTelemetrySnapshot

        def _empty() -> IntegrationStatistics:
            return IntegrationStatistics(
                config={
                    "enabled": False,
                    "selective_tracing": False,
                    "bytecode_optimization": False,
                    "cache_enabled": False,
                    "performance_monitoring": False,
                    "fallback_on_error": False,
                },
                integration_stats={},
                performance_data={},
                trace_manager_stats={},
                cache_stats=CacheStatistics(
                    func_code_cache=FuncCodeCacheStats(
                        hits=0,
                        misses=0,
                        evictions=0,
                        total_entries=0,
                        max_size=0,
                        ttl=0,
                        hit_rate=0.0,
                        memory_usage=0,
                    ),
                    breakpoint_cache=BreakpointCacheStats(
                        total_files=0,
                        max_entries=0,
                        cached_files=[],
                    ),
                    global_stats=GlobalCacheStats(
                        hits=0,
                        misses=0,
                        evictions=0,
                        total_entries=0,
                        memory_usage=0,
                    ),
                ),
                telemetry=FrameEvalTelemetrySnapshot(
                    reason_counts=FrameEvalReasonCounts(),
                    recent_events=[],
                ),
            )

        try:
            stats = get_integration_statistics()
            if isinstance(stats, dict):
                try:
                    return IntegrationStatistics(**stats)  # type: ignore[misc]
                except Exception:
                    return _empty()
            return _empty()
        except Exception:
            return _empty()
