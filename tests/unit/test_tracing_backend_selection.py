"""Phase 1.6 — unit tests for TracingBackend abstraction, SettraceBackend,
and FrameEvalManager backend-selection logic.

These tests verify the integration seams introduced in Phase 1 without
requiring SysMonitoringBackend (Phase 2) to exist yet.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from dapper._frame_eval.compatibility_policy import FrameEvalCompatibilityPolicy
from dapper._frame_eval.config import FrameEvalConfig
from dapper._frame_eval.settrace_backend import SettraceBackend
from dapper._frame_eval.tracing_backend import TracingBackend

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# ruff: noqa: PLC0415


def _fresh_manager():
    """Return a *new* FrameEvalManager instance (bypasses singleton)."""
    from dapper._frame_eval.frame_eval_main import FrameEvalManager

    mgr = object.__new__(FrameEvalManager)
    mgr.initialize()
    return mgr


# ---------------------------------------------------------------------------
# 1. TracingBackend protocol
# ---------------------------------------------------------------------------


class TestTracingBackendProtocol:
    """Verify the abstract interface is enforced."""

    def test_cannot_instantiate_abstract_backend(self):
        with pytest.raises(TypeError):
            TracingBackend()  # type: ignore[abstract]

    def test_concrete_subclass_must_implement_all_methods(self):
        """A partial implementation should raise TypeError at instantiation."""

        class Incomplete(TracingBackend):
            def install(self, debugger_instance): ...

        with pytest.raises(TypeError):
            Incomplete()  # missing shutdown, update_breakpoints, set_stepping, …

    def test_full_concrete_subclass_instantiates(self):
        class Full(TracingBackend):
            def install(self, debugger_instance): ...
            def shutdown(self): ...
            def update_breakpoints(self, filepath, lines): ...
            def set_stepping(self, mode): ...
            def set_exception_breakpoints(self, filters): ...
            def get_statistics(self):
                return {}

        backend = Full()
        assert isinstance(backend, TracingBackend)


# ---------------------------------------------------------------------------
# 2. SettraceBackend
# ---------------------------------------------------------------------------


class TestSettraceBackend:
    def test_implements_protocol(self):
        backend = SettraceBackend()
        assert isinstance(backend, TracingBackend)

    def test_install_on_unknown_object_does_not_raise(self):
        """install() should not raise even when the debugger has no methods."""
        backend = SettraceBackend()
        backend.install(object())

    def test_shutdown_before_install_does_not_raise(self):
        backend = SettraceBackend()
        backend.shutdown()

    def test_update_breakpoints_does_not_raise(self):
        backend = SettraceBackend()
        # Should be a no-op / best-effort even with arbitrary paths
        backend.update_breakpoints("/nonexistent/file.py", {10, 20})

    def test_set_stepping_does_not_raise(self):
        backend = SettraceBackend()
        backend.set_stepping("STEP_IN")

    def test_set_exception_breakpoints_does_not_raise(self):
        backend = SettraceBackend()
        backend.set_exception_breakpoints(["raised", "uncaught"])

    def test_get_statistics_returns_integration_statistics_shape(self):

        backend = SettraceBackend()
        stats = backend.get_statistics()
        # Should have the six required top-level keys of IntegrationStatistics
        for key in (
            "config",
            "integration_stats",
            "performance_data",
            "trace_manager_stats",
            "cache_stats",
            "telemetry",
        ):
            assert key in stats, f"Missing key '{key}' in statistics"

    def test_install_sets_installed_flag_when_integration_succeeds(self):
        """Verify internal _installed flag is set when integration succeeds."""
        backend = SettraceBackend()
        mock_debugger = MagicMock()
        mock_debugger.breakpoints = {}  # looks like DebuggerBDB

        with patch(
            "dapper._frame_eval.settrace_backend.integrate_debugger_bdb",
            return_value=True,
        ):
            backend.install(mock_debugger)

        assert backend._installed is True  # type: ignore[attr-defined]

    def test_shutdown_clears_installed_flag(self):
        backend = SettraceBackend()
        backend._installed = True  # type: ignore[attr-defined]
        backend._debugger = MagicMock()  # type: ignore[attr-defined]

        with patch("dapper._frame_eval.debugger_integration.remove_integration"):
            backend.shutdown()

        assert backend._installed is False  # type: ignore[attr-defined]
        assert backend._debugger is None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 3. TracingBackendKind enum and FrameEvalConfig round-trip
# ---------------------------------------------------------------------------


class TestTracingBackendKindConfig:
    def test_default_is_auto(self):
        cfg = FrameEvalConfig()
        assert cfg.tracing_backend is FrameEvalConfig.TracingBackendKind.AUTO

    @pytest.mark.parametrize("kind", list(FrameEvalConfig.TracingBackendKind))
    def test_round_trip_to_dict_from_dict(self, kind):
        cfg = FrameEvalConfig(tracing_backend=kind)
        d = cfg.to_dict()
        assert "tracing_backend" in d
        restored = FrameEvalConfig.from_dict(d)
        assert restored.tracing_backend is kind

    def test_from_dict_accepts_name_string(self):
        cfg = FrameEvalConfig.from_dict({"tracing_backend": "SETTRACE"})
        assert cfg.tracing_backend is FrameEvalConfig.TracingBackendKind.SETTRACE

    def test_from_dict_accepts_value_string(self):
        cfg = FrameEvalConfig.from_dict({"tracing_backend": "sys_monitoring"})
        assert cfg.tracing_backend is FrameEvalConfig.TracingBackendKind.SYS_MONITORING

    def test_from_dict_ignores_invalid_value(self):
        """An unrecognised tracing_backend value should fall back to the default."""
        cfg = FrameEvalConfig.from_dict({"tracing_backend": "nonexistent_backend"})
        assert cfg.tracing_backend is FrameEvalConfig.TracingBackendKind.AUTO


# ---------------------------------------------------------------------------
# 4. CompatibilityPolicy.supports_sys_monitoring
# ---------------------------------------------------------------------------


class TestSupportsSysMonitoring:
    def test_returns_false_on_old_python(self):
        policy = FrameEvalCompatibilityPolicy()
        with patch("sys.version_info"), patch.object(sys, "version_info", (3, 11, 0)):  # type: ignore[attr-defined]
            # The property reads the live sys.version_info
            result = policy.supports_sys_monitoring()
        assert result is False

    def test_returns_true_on_3_12_with_monitoring_attr(self):
        policy = FrameEvalCompatibilityPolicy()
        mock_monitoring = MagicMock()
        with (
            patch.object(sys, "version_info", (3, 12, 0)),
            patch.object(sys, "monitoring", mock_monitoring, create=True),
        ):
            result = policy.supports_sys_monitoring()
        assert result is True

    def test_returns_false_when_monitoring_attr_absent(self):
        """Even on 3.12+, if sys.monitoring is absent the result is False."""
        policy = FrameEvalCompatibilityPolicy()
        with patch.object(sys, "version_info", (3, 12, 0)):  # type: ignore[attr-defined]
            # Remove sys.monitoring for the duration of the test
            monitoring_backup = getattr(sys, "monitoring", None)
            if hasattr(sys, "monitoring"):
                delattr(sys, "monitoring")
            try:
                result = policy.supports_sys_monitoring()
            finally:
                if monitoring_backup is not None:
                    sys.monitoring = monitoring_backup  # type: ignore[attr-defined]
        assert result is False


# ---------------------------------------------------------------------------
# 5. FrameEvalManager._create_backend selection logic
# ---------------------------------------------------------------------------


class TestCreateBackend:
    def test_explicit_settrace_returns_settrace_backend(self):
        mgr = _fresh_manager()
        cfg = FrameEvalConfig(tracing_backend=FrameEvalConfig.TracingBackendKind.SETTRACE)
        backend = mgr._create_backend(cfg)
        assert isinstance(backend, SettraceBackend)

    def test_auto_on_old_python_returns_settrace_backend(self):
        mgr = _fresh_manager()
        mgr._compatibility_policy = FrameEvalCompatibilityPolicy()
        cfg = FrameEvalConfig(tracing_backend=FrameEvalConfig.TracingBackendKind.AUTO)
        with patch.object(
            mgr._compatibility_policy,
            "supports_sys_monitoring",
            return_value=False,
        ):
            backend = mgr._create_backend(cfg)
        assert isinstance(backend, SettraceBackend)

    def test_sys_monitoring_kind_falls_back_when_module_missing(self):
        """When monitoring_backend module hasn't been written yet, fall back gracefully."""
        mgr = _fresh_manager()
        cfg = FrameEvalConfig(tracing_backend=FrameEvalConfig.TracingBackendKind.SYS_MONITORING)
        # Simulate the module not existing
        with patch.dict("sys.modules", {"dapper._frame_eval.monitoring_backend": None}):
            backend = mgr._create_backend(cfg)
        assert isinstance(backend, SettraceBackend)

    def test_auto_on_new_python_falls_back_when_module_missing(self):
        mgr = _fresh_manager()
        cfg = FrameEvalConfig(tracing_backend=FrameEvalConfig.TracingBackendKind.AUTO)
        with (
            patch.object(mgr._compatibility_policy, "supports_sys_monitoring", return_value=True),
            patch.dict("sys.modules", {"dapper._frame_eval.monitoring_backend": None}),
        ):
            backend = mgr._create_backend(cfg)
        assert isinstance(backend, SettraceBackend)

    def test_active_backend_is_none_before_setup(self):
        mgr = _fresh_manager()
        assert mgr.active_backend is None

    def test_active_backend_set_to_settrace_after_setup(self):
        mgr = _fresh_manager()
        mgr._frame_eval_config.tracing_backend = FrameEvalConfig.TracingBackendKind.SETTRACE
        # Patch away real runtime/integration side-effects
        with patch.object(mgr._runtime, "initialize", return_value=True):
            result = mgr._initialize_components()

        assert result is True
        assert isinstance(mgr.active_backend, SettraceBackend)

    def test_active_backend_cleared_after_shutdown(self):
        mgr = _fresh_manager()
        mgr._frame_eval_config.tracing_backend = FrameEvalConfig.TracingBackendKind.SETTRACE
        with patch.object(mgr._runtime, "initialize", return_value=True):
            mgr._initialize_components()

        with patch.object(mgr._runtime, "shutdown"):
            mgr._cleanup_components()

        assert mgr.active_backend is None
