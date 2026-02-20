"""Tests for the frame evaluation runtime composition root."""

from __future__ import annotations

from unittest.mock import patch

from dapper._frame_eval.config import FrameEvalConfig
from dapper._frame_eval.runtime import FrameEvalRuntime
from dapper._frame_eval.telemetry import reset_frame_eval_telemetry
from dapper._frame_eval.telemetry import telemetry


def test_runtime_initialize_with_dict_config() -> None:
    """Runtime should initialize and accept dict configuration."""
    runtime = FrameEvalRuntime()

    assert runtime.initialized is False

    ok = runtime.initialize({"enabled": True, "debug": True, "cache_size": 42})

    assert ok is True
    assert runtime.initialized is True
    assert runtime.config.enabled is True
    assert runtime.config.debug is True
    assert runtime.config.cache_size == 42


def test_runtime_initialize_with_invalid_config_type() -> None:
    """Runtime rejects unsupported config payload types."""
    runtime = FrameEvalRuntime()

    ok = runtime.initialize(config="not-a-config")  # type: ignore[arg-type]

    assert ok is False
    assert runtime.initialized is False


def test_runtime_initialize_from_config_object() -> None:
    """Runtime accepts FrameEvalConfig instances."""
    runtime = FrameEvalRuntime()
    config = FrameEvalConfig(enabled=True, debug=True, optimize=False, cache_size=99)

    ok = runtime.initialize(config)

    assert ok is True
    assert runtime.config.enabled is True
    assert runtime.config.debug is True
    assert runtime.config.optimize is False
    assert runtime.config.cache_size == 99


def test_runtime_shutdown_disables_tracing_and_clears_cache() -> None:
    """Runtime shutdown should invoke subsystem cleanup hooks."""
    runtime = FrameEvalRuntime()
    runtime.initialize()

    with (
        patch("dapper._frame_eval.runtime.disable_selective_tracing") as mock_disable,
        patch("dapper._frame_eval.runtime.clear_all_caches") as mock_clear,
    ):
        runtime.shutdown()

    mock_disable.assert_called_once()
    mock_clear.assert_called_once()
    assert runtime.initialized is False


def test_runtime_update_breakpoints_delegates_to_trace_manager() -> None:
    """Breakpoint updates should be forwarded to trace manager."""
    runtime = FrameEvalRuntime()

    with patch("dapper._frame_eval.runtime.get_trace_manager") as mock_get_trace_manager:
        trace_manager = mock_get_trace_manager.return_value
        runtime.update_breakpoints("/tmp/sample.py", {10, 20})

    trace_manager.update_file_breakpoints.assert_called_once_with("/tmp/sample.py", {10, 20})


def test_runtime_status_shape() -> None:
    """Runtime status should include initialization, config, and tracing fields."""
    runtime = FrameEvalRuntime()

    with patch("dapper._frame_eval.runtime.get_trace_manager") as mock_get_trace_manager:
        mock_get_trace_manager.return_value.is_enabled.return_value = False
        status = runtime.status()

    assert status.initialized is False
    assert hasattr(status.config, "enabled")
    assert status.tracing_enabled is False

    # Verify new serialization helper
    d = status.as_dict()
    assert isinstance(d, dict)
    assert d["config"]["enabled"] == status.config.enabled


def test_runtime_stats_include_telemetry() -> None:
    """Runtime stats should include telemetry snapshot."""
    reset_frame_eval_telemetry()
    telemetry.record_auto_integration_failed()

    runtime = FrameEvalRuntime()
    stats = runtime.get_stats()

    assert hasattr(stats, "telemetry")
    assert hasattr(stats.telemetry, "reason_counts")
    assert stats.telemetry.reason_counts.auto_integration_failed >= 1
