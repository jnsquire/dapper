"""Tests for the frame tracing module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

import dapper._frame_eval.frame_tracing as ft

# Set up test paths
TEST_DIR = Path(__file__).parent.parent.parent / "dapper"
DEBUGGER_PATH = str(TEST_DIR / "debugger_bdb.py")


def test_create_pydev_trace_code_wrapper():
    """Test creating a code wrapper for debugging."""
    # Test creating a wrapper for a specific line
    wrapper = ft.create_pydev_trace_code_wrapper(42)
    assert isinstance(wrapper, str)
    assert "lineno = 42" in wrapper
    
    # Test that the template is cached
    wrapper2 = ft.create_pydev_trace_code_wrapper(42)
    assert wrapper == wrapper2
    
    # Test with a different line number
    wrapper3 = ft.create_pydev_trace_code_wrapper(100)
    assert "lineno = 100" in wrapper3


def test_update_globals_dict():
    """Test updating globals dictionary with debug utilities."""
    globals_dict = {}
    ft.update_globals_dict(globals_dict)
    
    assert globals_dict["_pydevd_frame_eval_active"] is True
    assert globals_dict["_pydevd_frame_eval_line"] is None
    assert globals_dict["_pydevd_frame_eval_filename"] is None


def test_should_skip_frame():
    """Test frame skipping logic with comprehensive frame content verification."""
    # Create a mock frame with realistic attributes
    frame = MagicMock(spec=["f_code", "f_globals", "f_locals"])
    frame.f_code = MagicMock(spec=["co_filename", "co_name"])
    frame.f_code.co_filename = "test_file.py"
    frame.f_code.co_name = "test_function"
    frame.f_globals = {"__name__": "__main__"}
    frame.f_locals = {"local_var": 42}
    
    with patch.object(ft, "_evaluator") as mock_evaluator:
        # Configure the mock to verify it receives the correct frame
        def mock_should_skip(f):
            # Verify frame attributes are accessible and have the expected types
            assert isinstance(f.f_code.co_filename, str)
            assert f.f_code.co_name == "test_function"
            assert f.f_globals["__name__"] == "__main__"
            assert f.f_locals["local_var"] == 42
            # Skip generated code or debugger paths
            return f.f_code.co_filename == "<string>" or "debugger_bdb.py" in f.f_code.co_filename
            
        mock_evaluator.should_skip_frame.side_effect = mock_should_skip
        
        # Test with regular Python file
        frame.f_code.co_filename = "regular.py"
        assert ft.should_skip_frame(frame) is False
        
        # Test with generated code (should be skipped)
        frame.f_code.co_filename = "<string>"
        assert ft.should_skip_frame(frame) is True
        
        # Test with debugger path
        frame.f_code.co_filename = str(Path(__file__).parent.parent.parent / "dapper" / "debugger_bdb.py")
        assert ft.should_skip_frame(frame) is True
        
        # Verify the evaluator was called with the frame
        assert mock_evaluator.should_skip_frame.call_count == 3


def test_get_frame_filename():
    """Test getting normalized frame filenames."""
    # Create a mock frame with relative path
    frame = MagicMock()
    test_file = "test.py"
    frame.f_code.co_filename = test_file
    
    # Get the expected path using the same logic as the implementation
    expected_path = str(Path(test_file).absolute().resolve())
    
    # Test that the function returns the expected path
    filename = ft.get_frame_filename(frame)
    assert filename == expected_path
    
    # Test with absolute path
    abs_path = "/already/absolute.py"
    frame.f_code.co_filename = abs_path
    
    # The implementation converts the path to a string, so we can just test that
    # the function returns the expected string representation
    filename = ft.get_frame_filename(frame)
    # The exact format might vary by platform, so we'll just check that it's a string
    # and contains the filename
    assert isinstance(filename, str)
    assert "absolute.py" in filename


def test_is_debugger_frame():
    """Test debugger frame detection."""
    frame = MagicMock()
    
    # Mock the _evaluator.is_debugger_frame method
    with patch.object(ft, "_evaluator") as mock_evaluator:
        # Test debugger frame
        mock_evaluator.is_debugger_frame.return_value = True
        assert ft.is_debugger_frame(frame) is True
        mock_evaluator.is_debugger_frame.assert_called_once_with(frame)
        
        # Reset mock for next test
        mock_evaluator.reset_mock()
        
        # Test non-debugger frame
        mock_evaluator.is_debugger_frame.return_value = False
        assert ft.is_debugger_frame(frame) is False
        mock_evaluator.is_debugger_frame.assert_called_once_with(frame)
    
    # Test non-debugger frame
    frame.f_code.co_name = "regular_function"
    frame.f_code.co_filename = "regular/file.py"
    assert ft.is_debugger_frame(frame) is False


def test_get_frame_info():
    """Test frame information extraction."""
    frame = MagicMock()
    frame.f_lineno = 10
    frame.f_code.co_name = "test_function"
    frame.f_code.co_filename = "test_file.py"
    
    with patch("dapper._frame_eval.frame_tracing.get_frame_filename", return_value="/abs/path/test_file.py"), \
         patch("dapper._frame_eval.frame_tracing.is_debugger_frame", return_value=False), \
         patch("dapper._frame_eval.frame_tracing.should_skip_frame", return_value=False):
        
        info = ft.get_frame_info(frame)
        
        assert info["lineno"] == 10
        assert info["function"] == "test_function"
        assert info["filename"] == "/abs/path/test_file.py"
        assert info["code_object"] == frame.f_code
        assert info["is_debugger_frame"] is False
        assert info["should_skip"] is False
    
    # Test with error getting filename
    with (
        patch("dapper._frame_eval.frame_tracing.get_frame_filename", side_effect=ValueError("Test error")),
        patch("dapper._frame_eval.frame_tracing.is_debugger_frame", return_value=False),
        patch("dapper._frame_eval.frame_tracing.should_skip_frame", return_value=False),
        pytest.raises(ValueError, match="Test error"),
    ):
        # We expect an exception to be raised when get_frame_filename fails
        ft.get_frame_info(frame)


def test_create_trace_function_wrapper():
    """Test trace function wrapper creation."""
    mock_trace = MagicMock()
    wrapper = ft.create_trace_function_wrapper(mock_trace)
    
    # Test with a frame that should be skipped
    frame = MagicMock()
    with patch("dapper._frame_eval.frame_tracing.should_skip_frame", return_value=True):
        wrapper(frame, "line", None)
        mock_trace.assert_called_once_with(frame, "line", None)
    
    # Test with frame evaluation active
    mock_trace.reset_mock()
    with patch("dapper._frame_eval.frame_tracing.should_skip_frame", return_value=False), \
         patch("dapper._frame_eval.frame_tracing._tracing_enabled", True), \
         patch("dapper._frame_eval.frame_tracing.get_frame_info") as mock_get_frame_info:
        
        mock_frame_info = {"should_skip": False}
        mock_get_frame_info.return_value = mock_frame_info
        
        # The function should let frame evaluation handle this
        result = wrapper(frame, "line", None)
        assert result is None
        mock_trace.assert_not_called()
    
    # Test with non-line event
    mock_trace.reset_mock()
    with patch("dapper._frame_eval.frame_tracing.should_skip_frame", return_value=False):
        wrapper(frame, "call", None)
        mock_trace.assert_called_once_with(frame, "call", None)
    
    # Test with frame evaluation active but frame should be skipped
    mock_trace.reset_mock()
    with patch("dapper._frame_eval.frame_tracing.should_skip_frame", return_value=False), \
         patch("dapper._frame_eval.frame_tracing._tracing_enabled", True), \
         patch("dapper._frame_eval.frame_tracing.get_frame_info") as mock_get_frame_info:
        
        mock_frame_info = {"should_skip": True}  # Frame should be skipped
        mock_get_frame_info.return_value = mock_frame_info
        
        result = wrapper(frame, "line", None)
        # The function should return the original trace function since frame should be skipped
        assert result is mock_trace.return_value


def test_invalidate_code_cache():
    """Test code cache invalidation."""
    # Create a mock code object
    code_obj = MagicMock()
    code_obj.co_filename = "test_file.py"
    code_obj.co_firstlineno = 1
    
    # Add to cache manager's cache
    cache_key = ft._cache_manager.get_cache_key(code_obj)
    ft._cache_manager._trace_function_cache[cache_key] = lambda: None
    
    # Invalidate the cache using the public method
    ft._cache_manager.clear_all()
    
    # Verify cache was cleared
    assert not ft._cache_manager._trace_function_cache


def test_get_breakpoint_lines_for_file():
    """Test getting breakpoint lines for a file."""
    # This is a simple wrapper that returns an empty set by default
    assert ft.get_breakpoint_lines_for_file("test.py") == set()


def test_optimize_code_for_debugging():
    """Test code optimization for debugging."""
    # Create a mock code object
    code_obj = MagicMock()
    
    # Test that the function returns the input object
    optimized = ft.optimize_code_for_debugging(code_obj)
    assert optimized is code_obj  # Currently just returns the input


def test_setup_frame_tracing():
    """Test frame tracing setup."""
    # Save original state
    original_tracing_enabled = ft._tracing_enabled
    
    try:
        # Test enabling
        assert ft.setup_frame_tracing({"enabled": True}) is True
        assert ft._tracing_enabled is True
        
        # Test disabling
        assert ft.setup_frame_tracing({"enabled": False}) is True
        assert ft._tracing_enabled is False
        
        # Test with invalid config (should still return True)
        with patch("dapper._frame_eval.frame_tracing._tracing_enabled", side_effect=Exception):
            assert ft.setup_frame_tracing({"enabled": True}) is True
    finally:
        # Restore original state
        ft._tracing_enabled = original_tracing_enabled


def test_cleanup_frame_tracing():
    """Test cleaning up frame tracing state."""
    # Save original state
    original_tracing_enabled = ft._tracing_enabled
    original_cache = ft._trace_function_cache.copy()
    
    try:
        # Set up some state
        ft._tracing_enabled = True
        # Use a properly formatted tuple key (line number, filename, line number)
        ft._trace_function_cache[(1, "test_file.py", 10)] = lambda: None
        
        # Clean up
        ft.cleanup_frame_tracing()
        
        # Verify state was reset
        assert ft._tracing_enabled is False
        assert not ft._trace_function_cache
    finally:
        # Restore original state
        ft._tracing_enabled = original_tracing_enabled
        ft._trace_function_cache = original_cache
