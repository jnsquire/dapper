"""Tests for the FrameEvalManager class.

This module contains unit tests for the FrameEvalManager class in Dapper.
"""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from dapper._frame_eval._frame_evaluator import _clear_thread_trace_func
from dapper._frame_eval._frame_evaluator import _dispatch_trace_callback
from dapper._frame_eval.config import FrameEvalConfig
from dapper._frame_eval.debugger_integration import integrate_with_backend
from dapper._frame_eval.eval_frame_backend import EvalFrameBackend
from dapper._frame_eval.frame_eval_main import FrameEvalManager
from dapper._frame_eval.types import get_thread_info
from dapper.core.debugger_bdb import DebuggerBDB
from tests.mocks import make_real_frame


class TestFrameEvalManager:
    """Test suite for the FrameEvalManager class."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test fixtures."""
        # Clear the singleton instance before each test
        FrameEvalManager._instance = None
        self.manager = FrameEvalManager()
        yield
        # Clean up after each test
        FrameEvalManager._instance = None

    def test_singleton_pattern(self):
        """Test that only one instance of FrameEvalManager exists."""
        manager1 = FrameEvalManager()
        manager2 = FrameEvalManager()
        assert manager1 is manager2

    def test_initial_state(self):
        """Test the initial state of the FrameEvalManager."""
        assert not self.manager.is_initialized
        expected_config = FrameEvalConfig(
            enabled=True,
            fallback_to_tracing=True,
            debug=False,
            cache_size=1000,
            optimize=True,
            timeout=30.0,
        )
        assert self.manager.config == expected_config

    def test_is_incompatible_environment(self):
        """Test the _is_incompatible_environment method."""
        # Save original values
        original_modules = sys.modules.copy()
        original_environ = os.environ.copy()

        try:
            # Test with no incompatible environments
            sys.modules.clear()
            os.environ.clear()
            assert not self.manager._is_incompatible_environment()

            # Test with an incompatible debugger
            sys.modules["pdb"] = MagicMock()
            assert self.manager._is_incompatible_environment()

            # Clean up
            sys.modules.clear()
            os.environ.clear()

            # Test with an incompatible environment variable
            os.environ["PYCHARM_HOSTED"] = "1"
            assert self.manager._is_incompatible_environment()

            # Clean up
            sys.modules.clear()
            os.environ.clear()

            # Test with coverage tool
            sys.modules["coverage"] = MagicMock()
            assert self.manager._is_incompatible_environment()

        finally:
            # Restore original values
            sys.modules.clear()
            sys.modules.update(original_modules)
            os.environ.clear()
            os.environ.update(original_environ)

    def test_check_platform_compatibility(self):
        """Test the _check_platform_compatibility method."""
        # Test with supported platform and architecture
        with (
            patch("platform.system", return_value="Windows"),
            patch("platform.architecture", return_value=("64bit", "WindowsPE")),
        ):
            assert self.manager._check_platform_compatibility()

        # Test with unsupported platform
        with patch("platform.system", return_value="UnsupportedOS"):
            assert not self.manager._check_platform_compatibility()

        # Test with unsupported architecture
        with (
            patch("platform.system", return_value="Linux"),
            patch("platform.architecture", return_value=("128bit", "ELF")),
        ):
            assert not self.manager._check_platform_compatibility()

    def test_check_environment_compatibility(self):
        """Test the check_environment_compatibility method."""

        # Create a mock for version info with attributes
        class VersionInfo:
            def __init__(self, major, minor, micro, releaselevel, serial):
                self.major = major
                self.minor = minor
                self.micro = micro
                self.releaselevel = releaselevel
                self.serial = serial

        with (
            patch.object(
                self.manager._compatibility_policy,
                "is_incompatible_environment",
                return_value=False,
            ),
            patch("platform.platform", return_value="Windows-10"),
            patch("sys.platform", "win32"),
            patch("platform.system", return_value="Windows"),
            patch("platform.architecture", return_value=("64bit", "WindowsPE")),
            patch("platform.python_implementation", return_value="CPython"),
        ):
            # Test with compatible Python version
            with patch("sys.version_info", VersionInfo(3, 11, 0, "final", 0)):
                result = self.manager.check_environment_compatibility()
                assert result["compatible"] is True
                assert result["python_version"] == "3.11.0"

            # Test with incompatible Python version (too old)
            with patch("sys.version_info", VersionInfo(3, 8, 0, "final", 0)):
                result = self.manager.check_environment_compatibility()
                assert result["compatible"] is False
                assert "Python version too old" in result["reason"]

            # Test with boundary Python version (maximum supported)
            with patch("sys.version_info", VersionInfo(3, 14, 0, "final", 0)):
                result = self.manager.check_environment_compatibility()
                assert result["compatible"] is True
                assert result["python_version"] == "3.14.0"
            # Test with incompatible Python version (too new)
            # max_python ceiling is now (3, 14), so 3.15 is the first out-of-range version
            with patch("sys.version_info", VersionInfo(3, 15, 0, "final", 0)):
                result = self.manager.check_environment_compatibility()
                assert result["compatible"] is False
                assert "Python version too new" in result["reason"]

    def test_config_management(self):
        """Test the config property and update_config method."""
        # Test initial config
        expected_config = FrameEvalConfig(
            enabled=True,
            fallback_to_tracing=True,
            debug=False,
            cache_size=1000,
            optimize=True,
            timeout=30.0,
        )
        assert self.manager.config == expected_config

        # Test updating config with validation
        update = {"debug": True, "cache_size": 2000}
        expected_updated = replace(expected_config, **update)

        with patch.object(self.manager, "_validate_config", return_value=True):
            result = self.manager.update_config(update)
            assert result is True
            assert self.manager.config == expected_updated

        # Test with invalid update (should not change config)
        invalid_updates = {"debug": "not a boolean"}
        with patch.object(self.manager, "_validate_config", return_value=False):
            # Save the current config before the invalid update
            config_before = FrameEvalConfig.from_dict(self.manager.config.to_dict())

            result = self.manager.update_config(invalid_updates)
            assert result is False

            # Config should remain unchanged from before the invalid update
            assert self.manager.config == config_before

            # Verify specific values are as expected
            assert self.manager.config.debug is True  # From the previous successful update
            assert self.manager.config.cache_size == 2000  # From the previous successful update
            assert self.manager.config.optimize is True
            assert self.manager.config.timeout == 30.0

    def test_update_config_applies_cache_and_condition_side_effects(self):
        """Config changes should fan out to cache, optimization, and condition state."""
        evaluator = MagicMock()
        evaluator.enabled = True
        evaluator._budget_s = 0.1

        updates = {
            "cache_size": 256,
            "optimize": False,
            "conditional_breakpoints_enabled": False,
            "condition_budget_s": 0.25,
        }

        with (
            patch.object(self.manager, "_validate_config", return_value=True),
            patch("dapper._frame_eval.frame_eval_main.configure_caches") as configure_caches,
            patch(
                "dapper._frame_eval.frame_eval_main.set_optimization_enabled"
            ) as set_optimization_enabled,
            patch("dapper._frame_eval.frame_eval_main.clear_all_caches") as clear_all_caches,
            patch(
                "dapper._frame_eval.frame_eval_main.get_condition_evaluator",
                return_value=evaluator,
            ),
            patch.object(
                self.manager._runtime, "initialize", return_value=True
            ) as initialize_runtime,
        ):
            result = self.manager.update_config(updates)

        assert result is True
        configure_caches.assert_called_once_with(func_code_max_size=256)
        set_optimization_enabled.assert_called_once_with(False)
        clear_all_caches.assert_called_once_with(reason="config_change")
        initialize_runtime.assert_called_once_with(self.manager.config)
        evaluator.clear_cache.assert_called_once_with()
        assert evaluator.enabled is False
        assert evaluator._budget_s == pytest.approx(0.25)

    def test_config_backend_serialization(self):
        """Ensure the new ``backend`` field round-trips through to_dict/from_dict."""
        cfg = FrameEvalConfig()
        cfg.backend = FrameEvalConfig.BackendKind.EVAL_FRAME
        d = cfg.to_dict()
        assert d["backend"] == "EVAL_FRAME"
        cfg2 = FrameEvalConfig.from_dict(d)
        assert cfg2.backend is FrameEvalConfig.BackendKind.EVAL_FRAME

    def test_backend_selection_logic(self):
        """The manager should pick an appropriate backend based on compatibility."""
        # AUTO should prefer eval-frame when available
        self.manager._compatibility_policy.can_use_eval_frame = lambda **kwargs: (True, "")
        cfg = FrameEvalConfig()
        cfg.backend = FrameEvalConfig.BackendKind.AUTO
        backend = self.manager._create_backend(cfg)
        assert isinstance(backend, EvalFrameBackend)

        # AUTO falls back to tracing if eval-frame unavailable
        self.manager._compatibility_policy.can_use_eval_frame = lambda **kwargs: (
            False,
            "Eval-frame hook API not available in this runtime",
        )
        cfg.backend = FrameEvalConfig.BackendKind.AUTO
        backend = self.manager._create_backend(cfg)
        # should fall back to a tracing backend of some kind
        assert not isinstance(backend, EvalFrameBackend)

        # Explicit EVAL_FRAME requested but not supported -> tracing fallback
        cfg.backend = FrameEvalConfig.BackendKind.EVAL_FRAME
        backend = self.manager._create_backend(cfg)
        assert not isinstance(backend, EvalFrameBackend)

        # Explicit TRACING always returns some tracing backend
        cfg.backend = FrameEvalConfig.BackendKind.TRACING
        backend = self.manager._create_backend(cfg)
        assert not isinstance(backend, EvalFrameBackend)

    def test_explicit_eval_frame_request_can_fail_without_tracing_fallback(self):
        """Explicit eval-frame requests should fail when tracing fallback is disabled."""
        self.manager._compatibility_policy.can_use_eval_frame = lambda **kwargs: (
            False,
            "Incompatible coverage tool detected: coverage",
        )

        cfg = FrameEvalConfig()
        cfg.backend = FrameEvalConfig.BackendKind.EVAL_FRAME
        cfg.fallback_to_tracing = False

        with pytest.raises(RuntimeError, match="Eval-frame backend explicitly requested"):
            self.manager._create_backend(cfg)

    def test_initialize_components_cleans_up_runtime_on_backend_failure(self):
        """Initialization should not leave the runtime half-initialized if backend selection fails."""
        self.manager._frame_eval_config.backend = FrameEvalConfig.BackendKind.EVAL_FRAME
        self.manager._frame_eval_config.fallback_to_tracing = False
        self.manager._compatibility_policy.can_use_eval_frame = lambda **kwargs: (
            False,
            "Eval-frame hook API not available in this runtime",
        )

        with (
            patch.object(self.manager._runtime, "initialize", return_value=True),
            patch.object(
                self.manager._runtime,
                "shutdown",
            ) as shutdown_runtime,
        ):
            assert self.manager._initialize_components() is False

        shutdown_runtime.assert_called_once_with()
        assert self.manager.active_backend is None

    def test_manager_selects_eval_frame_backend_and_integrates_it(self):
        """The manager-selected eval-frame backend should integrate through the backend router."""
        self.manager._compatibility_policy.can_use_eval_frame = lambda **kwargs: (True, "")
        self.manager._frame_eval_config.backend = FrameEvalConfig.BackendKind.EVAL_FRAME

        with patch.object(self.manager._runtime, "initialize", return_value=True):
            assert self.manager._initialize_components() is True

        assert isinstance(self.manager.active_backend, EvalFrameBackend)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as handle:
            handle.write("x = 1\ny = 2\nz = 3\nresult = x + y\nprint(z)\n")
            path = handle.name

        mock_send = MagicMock()
        debugger = DebuggerBDB(send_message=mock_send)
        debugger.reset()
        debugger.process_commands = MagicMock()
        debugger.set_break(path, 4)
        frame = make_real_frame({"x": 1, "y": 2}, filename=path, lineno=4)

        try:
            with (
                patch("dapper._frame_eval.eval_frame_backend.install_eval_frame_hook"),
                patch("dapper._frame_eval.eval_frame_backend.uninstall_eval_frame_hook"),
            ):
                assert integrate_with_backend(self.manager.active_backend, debugger) is True
                assert _dispatch_trace_callback(frame, "line", None) is True

                mock_send.assert_any_call(
                    "stopped",
                    threadId=threading.get_ident(),
                    reason="breakpoint",
                    allThreadsStopped=True,
                )
        finally:
            _clear_thread_trace_func()
            Path(path).unlink(missing_ok=True)

    def test_eval_frame_backend_set_stepping_updates_thread_info(self):
        """Eval-frame stepping should toggle the hook's thread-local step flag."""
        backend = EvalFrameBackend()
        thread_info = get_thread_info()
        thread_info.step_mode = False

        backend.set_stepping("STEP_IN")
        assert thread_info.step_mode is True
        assert backend.get_statistics()["step_mode"] == "STEP_IN"
        assert backend.get_statistics()["stepping_active"] is True

        backend.set_stepping("continue")
        assert thread_info.step_mode is False
        assert backend.get_statistics()["step_mode"] == "CONTINUE"
        assert backend.get_statistics()["stepping_active"] is False

    @pytest.mark.parametrize(
        ("mode", "expected_mode", "expected_active"),
        [
            ("STEP_IN", "STEP_IN", True),
            ("STEP_OVER", "STEP_OVER", True),
            ("STEP_OUT", "STEP_OUT", True),
            ("PAUSE", "PAUSE", True),
            ("RUN", "RUN", False),
        ],
    )
    def test_eval_frame_backend_preserves_step_mode_strings(
        self,
        mode,
        expected_mode,
        expected_active,
    ):
        """Eval-frame backend should retain the concrete debugger stepping mode."""
        backend = EvalFrameBackend()
        thread_info = get_thread_info()
        thread_info.step_mode = False

        backend.set_stepping(mode)

        assert backend.get_statistics()["step_mode"] == expected_mode
        assert backend.get_statistics()["stepping_active"] is expected_active
        assert thread_info.step_mode is expected_active

    def test_eval_frame_backend_shutdown_clears_stepping(self):
        """Shutdown should leave eval-frame thread stepping state disabled."""
        backend = EvalFrameBackend()
        thread_info = get_thread_info()

        backend.set_stepping("STEP_OVER")
        assert thread_info.step_mode is True

        with patch("dapper._frame_eval.eval_frame_backend.uninstall_eval_frame_hook"):
            backend.shutdown()

        assert thread_info.step_mode is False
        assert backend.get_statistics()["step_mode"] == "CONTINUE"
        assert backend.get_statistics()["stepping_active"] is False

    def test_eval_frame_backend_update_breakpoints_updates_shared_state(self):
        """Eval-frame breakpoint updates should fan out to both shared breakpoint stores."""
        backend = EvalFrameBackend()

        with (
            patch("dapper._frame_eval.eval_frame_backend._set_breakpoints") as set_breakpoints,
            patch(
                "dapper._frame_eval.eval_frame_backend._update_breakpoints"
            ) as update_breakpoints,
        ):
            backend.update_breakpoints("/tmp/example.py", {7, 3})

        set_breakpoints.assert_called_once_with("/tmp/example.py", {3, 7})
        update_breakpoints.assert_called_once_with("/tmp/example.py", {3, 7})
        stats = backend.get_statistics()
        assert stats["breakpoint_files"] == 1
        assert stats["breakpoint_lines"] == 2

    def test_eval_frame_backend_update_breakpoints_supports_clear(self):
        """Empty breakpoint updates should clear the backend's tracked file entries."""
        backend = EvalFrameBackend()

        with (
            patch("dapper._frame_eval.eval_frame_backend._set_breakpoints"),
            patch("dapper._frame_eval.eval_frame_backend._update_breakpoints"),
        ):
            backend.update_breakpoints("/tmp/example.py", {10, 20})
            backend.update_breakpoints("/tmp/example.py", set())

        stats = backend.get_statistics()
        assert stats["breakpoint_files"] == 1
        assert stats["breakpoint_lines"] == 0

    def test_eval_frame_backend_set_exception_breakpoints_normalizes_filters(self):
        """Exception breakpoint filters should be normalized and deduplicated."""
        backend = EvalFrameBackend()

        backend.set_exception_breakpoints(["Raised", " uncaught ", "raised", ""])

        assert backend.get_statistics()["exception_breakpoint_filters"] == [
            "raised",
            "uncaught",
        ]

    def test_eval_frame_backend_shutdown_clears_exception_breakpoints(self):
        """Shutdown should clear configured exception breakpoint filters."""
        backend = EvalFrameBackend()
        backend.set_exception_breakpoints(["raised", "uncaught"])
        assert backend.get_statistics()["exception_breakpoint_filters"] == [
            "raised",
            "uncaught",
        ]

        with patch("dapper._frame_eval.eval_frame_backend.uninstall_eval_frame_hook"):
            backend.shutdown()

        assert backend.get_statistics()["exception_breakpoint_filters"] == []

    def test_integrate_with_backend_records_eval_frame_install_failure_context(self):
        """Eval-frame install failures should emit debugger-integration telemetry with context."""
        from dapper._frame_eval.debugger_integration import integrate_with_backend
        from dapper._frame_eval.telemetry import get_frame_eval_telemetry
        from dapper._frame_eval.telemetry import reset_frame_eval_telemetry

        backend = MagicMock(spec=EvalFrameBackend)
        backend.install.side_effect = RuntimeError("install failed")
        debugger = MagicMock()

        reset_frame_eval_telemetry()
        assert integrate_with_backend(backend, debugger) is False

        snap = get_frame_eval_telemetry()
        assert snap.reason_counts.integration_bdb_failed == 1
        assert snap.recent_events[-1].context["backend_type"] == "EvalFrameBackend"
