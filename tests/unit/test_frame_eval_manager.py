"""Tests for the FrameEvalManager class.

This module contains unit tests for the FrameEvalManager class in Dapper.
"""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from dapper._frame_eval.config import FrameEvalConfig
from dapper._frame_eval.frame_eval_main import FrameEvalManager


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
            patch.object(self.manager, "_check_platform_compatibility", return_value=True),
            patch.object(self.manager, "_is_incompatible_environment", return_value=False),
            patch("platform.platform", return_value="Windows-10"),
            patch("sys.platform", "win32"),
            patch("platform.python_implementation", return_value="CPython"),
        ):
            # Test with compatible Python version
            with patch("sys.version_info", VersionInfo(3, 8, 0, "final", 0)):
                result = self.manager.check_environment_compatibility()
                assert result["compatible"] is True
                assert result["python_version"] == "3.8.0"

            # Test with incompatible Python version (too old)
            with patch("sys.version_info", VersionInfo(3, 5, 0, "final", 0)):
                result = self.manager.check_environment_compatibility()
                assert result["compatible"] is False
                assert "Python version too old" in result["reason"]

            # Test with incompatible Python version (too new)
            with patch("sys.version_info", VersionInfo(3, 11, 0, "final", 0)):
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
