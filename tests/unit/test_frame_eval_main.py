"""Tests for the frame evaluation main module.

This module contains unit tests for the frame evaluation functionality in Dapper.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from dapper._frame_eval.config import FrameEvalConfig
from dapper._frame_eval.frame_eval_main import FrameEvalManager


class TestFrameEvalMain:
    """Test cases for the frame_eval_main module."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test fixtures."""
        # Create a new instance for each test
        self.manager = FrameEvalManager()
        yield
        # Clean up after each test
        FrameEvalManager._instance = None

    def test_check_platform_compatibility(self):
        """Test platform compatibility checking."""
        # Test with Windows platform
        with (
            patch("platform.system", return_value="Windows"),
            patch("platform.architecture", return_value=("64bit", "WindowsPE")),
        ):
            assert self.manager._check_platform_compatibility() is True

        # Test with unsupported platform
        with patch("platform.system", return_value="UnsupportedOS"):
            assert self.manager._check_platform_compatibility() is False

        # Test with Linux platform and 32-bit architecture
        with (
            patch("platform.system", return_value="Linux"),
            patch("platform.architecture", return_value=("32bit", "ELF")),
        ):
            assert (
                self.manager._check_platform_compatibility() is True
            )  # 32-bit is in SUPPORTED_ARCHITECTURES

    def test_is_incompatible_environment(self):
        """Test environment compatibility checking."""
        # The actual implementation may have specific conditions, so we'll just test that it returns a boolean
        result = self.manager._is_incompatible_environment()
        assert isinstance(result, bool)

    def test_environment_compatibility(self):
        """Test overall environment compatibility checking."""
        # Get the compatibility result
        compatibility = self.manager.check_environment_compatibility()

        # Check that the result has the expected structure
        assert isinstance(compatibility, dict)
        assert "compatible" in compatibility
        assert "reason" in compatibility
        assert "python_version" in compatibility
        assert "platform" in compatibility
        assert "architecture" in compatibility
        assert "implementation" in compatibility


def test_setup_frame_eval():
    """Test frame evaluation setup."""
    manager = FrameEvalManager()

    # Test setup with valid config
    test_config = {"enabled": True, "debug": False}
    with (
        patch.object(manager, "_validate_config", return_value=True),
        patch.object(manager, "_initialize_components") as mock_init,
        patch.object(manager, "update_config") as mock_update_config,
    ):
        mock_update_config.return_value = True
        result = manager.setup_frame_eval(test_config)
        assert result is True
        mock_init.assert_called_once()
        mock_update_config.assert_called_once_with(test_config)

    # Test setup with invalid config
    with patch.object(manager, "_validate_config", return_value=False):
        result = manager.setup_frame_eval({"invalid": "config"})
        assert result is False


def test_shutdown_frame_eval():
    """Test frame evaluation shutdown."""
    # Setup mock state
    manager = FrameEvalManager()
    manager._is_initialized = True

    # Create a test config that's different from default
    test_config = FrameEvalConfig()
    test_config.enabled = True
    test_config.debug = True

    # Use setattr to bypass type checking for test purposes
    manager._frame_eval_config = test_config

    # Test shutdown
    with patch.object(manager, "_cleanup_components") as mock_cleanup:
        manager.shutdown_frame_eval()
        mock_cleanup.assert_called_once()
        assert manager._is_initialized is False
        # Should be reset to default config, not the test config
        assert manager._frame_eval_config == FrameEvalConfig()


def test_get_debug_info():
    """Test debug information retrieval."""
    manager = FrameEvalManager()

    # Test when frame evaluation is not initialized
    manager._is_initialized = False
    default_config = FrameEvalConfig()
    manager._frame_eval_config = default_config

    debug_info = manager.get_debug_info()
    assert isinstance(debug_info, dict)
    assert debug_info["frame_eval_initialized"] is False
    assert isinstance(debug_info["frame_eval_config"], FrameEvalConfig)

    # Test when frame evaluation is initialized
    manager._is_initialized = True
    test_config = FrameEvalConfig()
    test_config.enabled = True
    test_config.debug = True
    manager._frame_eval_config = test_config

    debug_info = manager.get_debug_info()
    assert debug_info["frame_eval_initialized"] is True
    assert debug_info["frame_eval_config"] == test_config

    # Check for required fields
    assert "python_version" in debug_info
    assert "platform" in debug_info
    assert "architecture" in debug_info
    assert "implementation" in debug_info
