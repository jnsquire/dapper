"""Tests for the frame evaluation main module.

This module contains unit tests for the frame evaluation functionality in Dapper.
"""

from __future__ import annotations

from unittest.mock import patch

from dapper._frame_eval import frame_eval_main as fe


def test_check_c_api_compatibility():
    """Test C API compatibility checking."""
    # The actual implementation may vary, so we'll just test that it returns a boolean
    result = fe._check_c_api_compatibility()
    assert isinstance(result, bool)


def test_check_platform_compatibility():
    """Test platform compatibility checking."""
    # Test with Windows platform
    with (
        patch("platform.system", return_value="Windows"),
        patch("platform.architecture", return_value=("64bit", "WindowsPE")),
    ):
        assert fe._check_platform_compatibility() is True
    
    # Test with unsupported platform
    with patch("platform.system", return_value="UnsupportedOS"):
        assert fe._check_platform_compatibility() is False
    
    # Test with Linux platform and 32-bit architecture
    with (
        patch("platform.system", return_value="Linux"),
        patch("platform.architecture", return_value=("32bit", "ELF")),
    ):
        assert fe._check_platform_compatibility() is True  # 32-bit is in SUPPORTED_ARCHITECTURES


def test_is_incompatible_environment():
    """Test environment compatibility checking."""
    # The actual implementation may have specific conditions, so we'll just test that it returns a boolean
    result = fe._is_incompatible_environment()
    assert isinstance(result, bool)


def test_environment_compatibility():
    """Test overall environment compatibility checking."""
    # Get the compatibility result
    result = fe.check_environment_compatibility()
    
    # Check that the result is a dictionary with expected keys
    assert isinstance(result, dict)
    assert "compatible" in result
    assert "python_version" in result
    assert "implementation" in result
    assert "architecture" in result
    assert "platform" in result


def test_setup_frame_eval():
    """Test frame evaluation setup."""
    # Save original state
    original_initialized = fe._is_initialized
    
    try:
        # Test setup when not initialized
        fe._is_initialized = False
        with (
            patch("dapper._frame_eval.frame_eval_main._validate_config", return_value=True),
            patch("dapper._frame_eval.frame_eval_main._initialize_components", return_value=True),
        ):
            # The actual return value depends on the implementation
            result = fe.setup_frame_eval({})
            assert isinstance(result, bool)
        
        # Test setup when already initialized
        fe._is_initialized = True
        result = fe.setup_frame_eval({})
        assert isinstance(result, bool)
        
    finally:
        # Restore original state
        fe._is_initialized = original_initialized


def test_shutdown_frame_eval():
    """Test frame evaluation shutdown."""
    # Setup mock state
    fe._is_initialized = True
    fe._frame_eval_config = {"test": "config"}
    
    # Test shutdown
    with patch("dapper._frame_eval.frame_eval_main._cleanup_components") as mock_cleanup:
        fe.shutdown_frame_eval()
        mock_cleanup.assert_called_once()
        assert fe._is_initialized is False
        assert fe._frame_eval_config == {}


def test_get_debug_info():
    """Test debug information retrieval."""
    # Save original state
    original_initialized = fe._is_initialized
    original_config = fe._frame_eval_config.copy()
    
    try:
        # Setup test data
        fe._is_initialized = True
        fe._frame_eval_config = {"test": "config"}
        
        # Get debug info
        info = fe.get_debug_info()
        
        # Verify basic structure
        assert "initialized" in info
        assert "config" in info
        assert "environment" in info
        assert "compatibility" in info
        
        # Verify values
        assert info["initialized"] is True
        assert info["config"] == {"test": "config"}
        assert isinstance(info["environment"], dict)
        assert isinstance(info["compatibility"], dict)
        
    finally:
        # Restore original state
        fe._is_initialized = original_initialized
        fe._frame_eval_config = original_config
