"""
Integration layer for frame evaluation with Dapper debugger classes.

This module provides seamless integration between the high-performance frame
evaluation system and the existing PyDebugger and DebuggerBDB classes,
enabling automatic optimization while maintaining full compatibility.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import threading
import time
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from typing_extensions import TypedDict
else:
    try:
        from typing_extensions import TypedDict
    except ImportError:
        from typing import TypedDict

# Import our frame evaluation components
from dapper._frame_eval.cache_manager import CacheStatistics
from dapper._frame_eval.cache_manager import clear_all_caches
from dapper._frame_eval.cache_manager import get_cache_statistics
from dapper._frame_eval.cache_manager import set_func_code_info
from dapper._frame_eval.modify_bytecode import BytecodeModifier
from dapper._frame_eval.modify_bytecode import inject_breakpoint_bytecode
from dapper._frame_eval.selective_tracer import disable_selective_tracing
from dapper._frame_eval.selective_tracer import enable_selective_tracing
from dapper._frame_eval.selective_tracer import get_selective_trace_function
from dapper._frame_eval.selective_tracer import get_trace_manager
from dapper._frame_eval.selective_tracer import update_breakpoints
from dapper._frame_eval.telemetry import FrameEvalTelemetrySnapshot
from dapper._frame_eval.telemetry import get_frame_eval_telemetry
from dapper._frame_eval.telemetry import telemetry

# Check module availability
debugger_bdb_available = importlib.util.find_spec("dapper.core.debugger_bdb") is not None
server_available = importlib.util.find_spec("dapper.adapter.server") is not None


class FrameEvalConfigDict(TypedDict):
    """Configuration for frame evaluation integration."""

    enabled: bool
    selective_tracing: bool
    bytecode_optimization: bool
    cache_enabled: bool
    performance_monitoring: bool
    fallback_on_error: bool


# Backward-compatibility alias for external imports/tests.
FrameEvalConfig = FrameEvalConfigDict


class IntegrationStatistics(TypedDict):
    """Statistics for frame evaluation integration."""

    config: FrameEvalConfigDict
    integration_stats: dict[str, int]
    performance_data: dict[str, Any]
    trace_manager_stats: dict[str, Any]
    cache_stats: CacheStatistics
    telemetry: FrameEvalTelemetrySnapshot


class DebuggerFrameEvalBridge:
    """
    Bridge between frame evaluation system and debugger classes.

    Provides automatic integration hooks that enhance debugger performance
    without requiring changes to existing debugger logic.
    """

    def __init__(self):
        self.config: FrameEvalConfigDict = {
            "enabled": True,
            "selective_tracing": True,
            "bytecode_optimization": True,
            "cache_enabled": True,
            "performance_monitoring": True,
            "fallback_on_error": True,
        }

        self.bytecode_modifier = BytecodeModifier()
        self.original_trace_functions = {}
        self.integration_stats = {
            "integrations_enabled": 0,
            "breakpoints_optimized": 0,
            "trace_calls_saved": 0,
            "bytecode_injections": 0,
            "errors_handled": 0,
        }
        self._lock = threading.RLock()

        # Performance monitoring
        self._performance_data = {
            "start_time": time.time(),
            "trace_function_calls": 0,
            "frame_eval_calls": 0,
            "cache_hits": 0,
            "cache_misses": 0,
        }

    def _ensure_user_line_exists(self, debugger_instance) -> None:
        """Ensure debugger has a user_line method."""
        if not hasattr(debugger_instance, "user_line") or not callable(
            debugger_instance.user_line
        ):

            def no_op_user_line(_frame):
                return None

            debugger_instance.user_line = no_op_user_line

    def _should_skip_trace_frame(self, frame) -> bool:
        """Check if frame should be skipped based on selective tracing."""
        if not self.config["selective_tracing"]:
            return False

        try:
            trace_manager = get_trace_manager()
            if trace_manager.is_enabled():
                decision = trace_manager.dispatcher.analyzer.should_trace_frame(frame)
                if not decision["should_trace"]:
                    self.integration_stats["trace_calls_saved"] += 1
                    return True
        except Exception:
            self.integration_stats["errors_handled"] += 1
            telemetry.record_selective_tracing_analysis_failed()
            if not self.config["fallback_on_error"]:
                raise
        return False

    def _call_original_fallback(self, debugger_instance, frame, original_user_line_func):
        """Call original user_line or mock_user_line as fallback."""
        if hasattr(debugger_instance, "_mock_user_line"):
            return debugger_instance._mock_user_line(frame)
        if original_user_line_func:
            return original_user_line_func(frame)
        return None

    def _create_enhanced_user_line(self, debugger_instance, original_user_line_func):
        """Create the enhanced user_line function."""

        def enhanced_user_line(frame):
            try:
                if self._should_skip_trace_frame(frame):
                    return None

                # Call original debugger logic
                if original_user_line_func:
                    return original_user_line_func(frame)
                return None

            except Exception:
                self.integration_stats["errors_handled"] += 1
                telemetry.record_py_debugger_trace_hook_failed()
                if self.config["fallback_on_error"]:
                    return self._call_original_fallback(
                        debugger_instance, frame, original_user_line_func
                    )
                raise

        return enhanced_user_line

    def _create_trace_function(self, enhanced_user_line):
        """Create trace function for selective tracing."""

        def trace_func(frame, event, _arg):
            if event == "line":
                return enhanced_user_line(frame)
            return None

        return trace_func

    def integrate_with_debugger_bdb(self, debugger_instance) -> bool:
        """
        Integrate frame evaluation with a DebuggerBDB instance.

        Args:
            debugger_instance: The DebuggerBDB instance to enhance

        Returns:
            True if integration was successful, False otherwise
        """
        if debugger_instance is None:
            return False

        debugger_id = id(debugger_instance)

        # If we already have this debugger integrated, return True
        if debugger_id in self.original_trace_functions:
            return True

        self._ensure_user_line_exists(debugger_instance)
        original_user_line = debugger_instance.user_line

        try:
            with self._lock:
                if not self.config["enabled"]:
                    return False

                # Store the original function in our tracking
                self.original_trace_functions[debugger_id] = original_user_line

                # Create and set enhanced user_line
                enhanced_user_line = self._create_enhanced_user_line(
                    debugger_instance, original_user_line
                )
                debugger_instance.user_line = enhanced_user_line

                # Enable selective tracing
                if self.config["selective_tracing"]:
                    trace_func = self._create_trace_function(enhanced_user_line)
                    enable_selective_tracing(trace_func)

                self.integration_stats["integrations_enabled"] += 1
                return True

        except Exception:
            # Clean up if an error occurs during integration
            self.original_trace_functions.pop(debugger_id, None)
            telemetry.record_integration_bdb_failed()

            if self.config["fallback_on_error"]:
                self.integration_stats["errors_handled"] += 1
                # Restore original user_line if we can
                if hasattr(debugger_instance, "user_line"):
                    debugger_instance.user_line = original_user_line
                return False

            raise

    def integrate_with_py_debugger(self, debugger_instance) -> bool:
        """
        Integrate frame evaluation with a PyDebugger instance.

        Args:
            debugger_instance: The PyDebugger instance to enhance

        Returns:
            True if integration was successful
        """
        try:
            with self._lock:
                if not self.config["enabled"]:
                    return False

                # Hook into breakpoint setting
                original_set_breakpoints = getattr(debugger_instance, "set_breakpoints", None)

                def enhanced_set_breakpoints(source, breakpoints, **kwargs):
                    """Enhanced breakpoint setting with frame evaluation optimizations."""
                    try:
                        # Call original breakpoint setting
                        result = (
                            original_set_breakpoints(source, breakpoints, **kwargs)
                            if original_set_breakpoints
                            else None
                        )

                        # Update frame evaluation system with new breakpoints
                        if self.config["selective_tracing"]:
                            filepath = source.get("path", "")
                            if filepath:
                                breakpoint_lines = {
                                    bp.get("line", 0) for bp in breakpoints if bp.get("line")
                                }
                                update_breakpoints(filepath, breakpoint_lines)
                                self.integration_stats["breakpoints_optimized"] += len(
                                    breakpoint_lines
                                )

                        # Apply bytecode optimizations if enabled
                        if self.config["bytecode_optimization"] and breakpoints:
                            self._apply_bytecode_optimizations(source, breakpoints)

                        return result
                        # ruff: noqa: TRY300 - Valid try-except structure, return is part of try block

                    except Exception:
                        if self.config["fallback_on_error"]:
                            self.integration_stats["errors_handled"] += 1
                            telemetry.record_py_debugger_breakpoint_hook_failed()
                            return (
                                original_set_breakpoints(source, breakpoints, **kwargs)
                                if original_set_breakpoints
                                else None
                            )
                        raise

                # Replace the set_breakpoints method
                debugger_instance.set_breakpoints = enhanced_set_breakpoints

                # Hook into trace function setting
                original_set_trace = getattr(debugger_instance, "_set_trace_function", None)

                def enhanced_set_trace():
                    """Enhanced trace function setting with selective tracing."""
                    try:
                        if self.config["selective_tracing"]:
                            # Use selective tracing instead of direct sys.settrace
                            selective_trace = get_selective_trace_function()
                            if selective_trace:
                                sys.settrace(selective_trace)
                                return

                        # Fallback to original behavior
                        if original_set_trace:
                            original_set_trace()

                    except Exception:
                        if self.config["fallback_on_error"]:
                            self.integration_stats["errors_handled"] += 1
                            telemetry.record_py_debugger_trace_hook_failed()
                            if original_set_trace:
                                original_set_trace()
                        else:
                            raise

                # Call the original function first to indicate integration
                if original_set_trace:
                    original_set_trace()

                # Replace the trace function setter
                # ruff: noqa: SLF001 - Intentional access to private method for debugger integration
                debugger_instance._set_trace_function = enhanced_set_trace

                self.integration_stats["integrations_enabled"] += 1
                return True

        except Exception:
            if self.config["fallback_on_error"]:
                self.integration_stats["errors_handled"] += 1
                telemetry.record_py_debugger_integration_failed()
                return False
            raise

    def _apply_bytecode_optimizations(
        self, source: dict[str, Any], breakpoints: list[dict[str, Any]]
    ) -> None:
        """Apply bytecode optimizations for breakpoints."""
        if not self.config["bytecode_optimization"]:
            return

        try:
            filepath = source.get("path", "")
            if not filepath or not filepath.endswith(".py"):
                return

            breakpoint_lines = {
                line
                for bp in breakpoints
                if (line := bp.get("line")) is not None
            }
            if not breakpoint_lines:
                return

            # Read the source file and compile it
            try:
                with pathlib.Path(filepath).open(encoding="utf-8") as f:
                    source_code = f.read()

                # Compile the source code
                code_obj = compile(source_code, filepath, "exec")

                # Apply bytecode modifications
                modified_code = inject_breakpoint_bytecode(code_obj, breakpoint_lines)
                if modified_code:
                    self.integration_stats["bytecode_injections"] += 1
                    # Store the modified code object for future use
                    set_func_code_info(
                        code_obj, {"modified_code": modified_code, "breakpoints": breakpoint_lines}
                    )

            except Exception:
                # If we can't read/compile the file, skip bytecode optimization
                self.integration_stats["errors_handled"] += 1
                telemetry.record_bytecode_optimization_file_read_failed(
                    filepath=filepath,
                )

        except Exception:
            # Silently fail if bytecode optimization fails
            self.integration_stats["errors_handled"] += 1
            telemetry.record_bytecode_optimization_failed()

    def remove_integration(self, debugger_instance) -> bool:
        """
        Remove frame evaluation integration from a debugger instance.

        Args:
            debugger_instance: The debugger instance to restore

        Returns:
            bool: True if removal was successful, False if debugger was not found
        """
        if debugger_instance is None:
            return False

        try:
            with self._lock:
                debugger_id = id(debugger_instance)

                # Check if debugger is in our tracking
                if debugger_id not in self.original_trace_functions:
                    return False

                # Restore original user_line function for DebuggerBDB
                original_func = self.original_trace_functions[debugger_id]
                if hasattr(debugger_instance, "user_line"):
                    debugger_instance.user_line = original_func
                del self.original_trace_functions[debugger_id]

                # Disable selective tracing if no more integrations
                if not self.original_trace_functions:
                    disable_selective_tracing()

                return True

        except Exception:
            # If anything goes wrong during removal, consider it a failure
            telemetry.record_integration_remove_failed()
            return False

    def update_config(self, **kwargs) -> None:
        """Update integration configuration."""
        with self._lock:
            for key, value in kwargs.items():
                if key in self.config:
                    self.config[key] = value

            # Apply configuration changes
            if not self.config["cache_enabled"]:
                clear_all_caches()

            if not self.config["enabled"]:
                # Disable all integrations
                disable_selective_tracing()

    def get_integration_statistics(self) -> IntegrationStatistics:
        """Get comprehensive integration statistics."""
        with self._lock:
            # Get frame evaluation statistics
            trace_stats = get_trace_manager().get_statistics()
            cache_stats = get_cache_statistics()

            # Calculate performance metrics
            uptime = time.time() - self._performance_data["start_time"]

            return {
                "config": self.config.copy(),
                "integration_stats": self.integration_stats.copy(),
                "performance_data": {
                    **self._performance_data,
                    "uptime_seconds": uptime,
                    "avg_trace_calls_per_second": self._performance_data["trace_function_calls"]
                    / max(uptime, 1),
                },
                "trace_manager_stats": trace_stats,
                "cache_stats": cache_stats,
                "telemetry": get_frame_eval_telemetry(),
            }

    def reset_statistics(self) -> None:
        """Reset all integration statistics."""
        with self._lock:
            self.config = {
                "enabled": True,
                "selective_tracing": True,
                "bytecode_optimization": True,
                "cache_enabled": True,
                "performance_monitoring": True,
                "fallback_on_error": True,
            }
            self.integration_stats = {
                "integrations_enabled": 0,
                "breakpoints_optimized": 0,
                "trace_calls_saved": 0,
                "bytecode_injections": 0,
                "errors_handled": 0,
            }
            self._performance_data = {
                "start_time": time.time(),
                "trace_function_calls": 0,
                "frame_eval_calls": 0,
                "cache_hits": 0,
                "cache_misses": 0,
            }

    def enable_performance_monitoring(self, enabled: bool = True) -> None:
        """Enable or disable performance monitoring."""
        with self._lock:
            self.config["performance_monitoring"] = enabled

    def _monitor_trace_call(self) -> None:
        """Monitor a trace function call (for performance tracking)."""
        if self.config["performance_monitoring"]:
            self._performance_data["trace_function_calls"] += 1

    def _monitor_frame_eval_call(self) -> None:
        """Monitor a frame evaluation call (for performance tracking)."""
        if self.config["performance_monitoring"]:
            self._performance_data["frame_eval_calls"] += 1


# Global bridge instance
_integration_bridge = DebuggerFrameEvalBridge()


def get_integration_bridge() -> DebuggerFrameEvalBridge:
    """Get the global integration bridge instance."""
    return _integration_bridge


def integrate_debugger_bdb(debugger_instance) -> bool:
    """Integrate frame evaluation with a DebuggerBDB instance."""
    return _integration_bridge.integrate_with_debugger_bdb(debugger_instance)


def integrate_py_debugger(debugger_instance) -> bool:
    """Integrate frame evaluation with a PyDebugger instance."""
    return _integration_bridge.integrate_with_py_debugger(debugger_instance)


def remove_integration(debugger_instance) -> bool:
    """Remove frame evaluation integration from a debugger instance."""
    return _integration_bridge.remove_integration(debugger_instance)


def configure_integration(**kwargs) -> None:
    """Configure frame evaluation integration."""
    _integration_bridge.update_config(**kwargs)


def get_integration_statistics() -> IntegrationStatistics:
    """Get integration statistics."""
    return _integration_bridge.get_integration_statistics()


def integrate_with_backend(backend: Any, debugger_instance: object) -> bool:
    """Wire *debugger_instance* to *backend* using the appropriate path.

    For :class:`~dapper._frame_eval.monitoring_backend.SysMonitoringBackend`:
    calls ``backend.install(debugger_instance)`` directly and returns
    ``True``.  The ``sys.monitoring`` path does **not** wrap ``user_line``
    or install ``sys.settrace``; the backend's callbacks handle everything.

    For :class:`~dapper._frame_eval.settrace_backend.SettraceBackend` (or
    any other :class:`~dapper._frame_eval.tracing_backend.TracingBackend`):
    falls back to :func:`integrate_debugger_bdb`.

    Args:
        backend: The active :class:`~dapper._frame_eval.tracing_backend.TracingBackend`.
        debugger_instance: The debugger to wire up.

    Returns:
        ``True`` if integration succeeded.

    """
    try:
        # Importing here keeps the dependency optional; ruff PLC0415 is
        # suppressed because this is intentional.
        from dapper._frame_eval.monitoring_backend import SysMonitoringBackend  # noqa: PLC0415

        if isinstance(backend, SysMonitoringBackend):
            try:
                backend.install(debugger_instance)
                return True
            except Exception:
                telemetry.record_integration_bdb_failed()
                return False
    except ImportError:
        pass

    return integrate_debugger_bdb(debugger_instance)


def auto_integrate_debugger(debugger_instance) -> bool:
    """
    Automatically detect debugger type and integrate frame evaluation.

    Args:
        debugger_instance: The debugger instance to enhance

    Returns:
        True if integration was successful, False otherwise
    """
    try:
        # Check if it's a DebuggerBDB instance
        if hasattr(debugger_instance, "breakpoints"):
            return _integration_bridge.integrate_with_debugger_bdb(debugger_instance)

        # Check if it's a PyDebugger instance
        if hasattr(debugger_instance, "set_breakpoints") and hasattr(debugger_instance, "threads"):
            return _integration_bridge.integrate_with_py_debugger(debugger_instance)

        # Unknown debugger type
        return False
        # ruff: noqa: TRY300 - Valid try-except structure, return is part of try block

    except Exception:
        telemetry.record_auto_integration_failed()
        return False
