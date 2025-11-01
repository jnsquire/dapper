"""Tests for the restructured frame tracing module."""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import dapper._frame_eval.frame_tracing as ft
from dapper._frame_eval.frame_tracing import (
    CacheManager,
    CodeWrapper,
    FrameEvaluator,
    FrameTracingConfig,
    PathHandler,
)


class TestFrameTracingConfig:
    """Test the FrameTracingConfig class."""
    
    def test_default_config(self):
        """Test default configuration values."""
        config = FrameTracingConfig()
        assert config.enabled is False
        assert config.debugger_paths == ft.DEBUGGER_PATHS
        assert config.standard_library_paths == ft.STANDARD_LIBRARY_PATHS
        assert config.debugger_functions == ft.DEBUGGER_FUNCTIONS
    
    def test_from_dict(self):
        """Test creating config from dictionary."""
        config = FrameTracingConfig.from_dict({"enabled": True})
        assert config.enabled is True
    
    def test_from_dict_default(self):
        """Test creating config from dictionary with missing key."""
        config = FrameTracingConfig.from_dict({})
        assert config.enabled is False


class TestPathHandler:
    """Test the PathHandler class."""
    
    def test_normalize_path_relative(self):
        """Test normalizing relative paths."""
        test_path = "relative/path.py"
        expected = str(Path(test_path).absolute().resolve())
        
        # The method uses Path.absolute() and resolve() directly, so we don't need to mock os.path
        result = PathHandler.normalize_path(test_path)
        
        # On Windows, the path might use backslashes, so we'll compare Path objects
        assert Path(result) == Path(expected)
    
    def test_normalize_path_absolute(self):
        """Test normalizing absolute paths."""
        test_path = "/some/path.py"
        expected = str(Path(test_path).absolute().resolve())
        
        # The method uses Path.absolute() and resolve() directly
        result = PathHandler.normalize_path(test_path)
        
        # Compare Path objects to handle path separator differences
        assert Path(result) == Path(expected)
    
    def test_normalize_path_error(self):
        """Test path normalization with error."""
        with patch("os.path.isabs", side_effect=Exception("Test error")):
            result = PathHandler.normalize_path("test.py")
            assert result == "test.py"
    
    def test_is_debugger_path(self):
        """Test debugger path detection."""
        test_path = str(Path("dapper", "debugger_bdb.py"))
        debugger_paths = [str(Path("dapper", "debugger_bdb.py"))]
        assert PathHandler.is_debugger_path(test_path, debugger_paths) is True
        assert PathHandler.is_debugger_path("user_code.py", ft.DEBUGGER_PATHS) is False
    
    def test_is_standard_library_path(self):
        """Test standard library path detection."""
        test_path = str(Path("lib", "python", "test.py"))
        std_paths = [str(Path("lib", "python"))]
        assert PathHandler.is_standard_library_path(test_path, std_paths) is True
        assert PathHandler.is_standard_library_path("user_code.py", ["lib/python"]) is False
    
    def test_is_generated_code(self):
        """Test generated code detection."""
        assert PathHandler.is_generated_code("<module>") is True
        assert PathHandler.is_generated_code("<listcomp>") is True
        assert PathHandler.is_generated_code("test.py") is False


class TestFrameEvaluator:
    """Test the FrameEvaluator class."""
    
    def test_should_skip_frame_debugger_path(self):
        """Test skipping debugger frames."""
        config = FrameTracingConfig()
        handler = PathHandler()
        evaluator = FrameEvaluator(config, handler)

        frame = MagicMock()
        frame.f_code.co_filename = str(Path("dapper", "debugger_bdb.py"))
        
        with patch.object(handler, "is_debugger_path", return_value=True):
            assert evaluator.should_skip_frame(frame) is True
    
    def test_should_skip_frame_standard_library(self):
        """Test skipping standard library frames."""
        config = FrameTracingConfig()
        handler = PathHandler()
        evaluator = FrameEvaluator(config, handler)

        frame = MagicMock()
        frame.f_code.co_filename = str(Path("lib", "python", "test.py"))
        
        with patch.object(handler, "is_standard_library_path", return_value=True):
            assert evaluator.should_skip_frame(frame) is True
    
    def test_should_skip_frame_no_filename(self):
        """Test skipping frames with no filename."""
        config = FrameTracingConfig()
        handler = PathHandler()
        evaluator = FrameEvaluator(config, handler)

        frame = MagicMock()
        frame.f_code.co_filename = ""
        
        assert evaluator.should_skip_frame(frame) is True
    
    def test_should_skip_frame_string(self):
        """Test skipping <string> frames."""
        config = FrameTracingConfig()
        handler = PathHandler()
        evaluator = FrameEvaluator(config, handler)

        frame = MagicMock()
        frame.f_code.co_filename = "<string>"
        
        assert evaluator.should_skip_frame(frame) is True
    
    def test_should_skip_frame_generated_code(self):
        """Test skipping generated code frames."""
        config = FrameTracingConfig()
        handler = PathHandler()
        evaluator = FrameEvaluator(config, handler)

        frame = MagicMock()
        frame.f_code.co_filename = "<module>"
        
        assert evaluator.should_skip_frame(frame) is True
    
    def test_should_not_skip_user_frame(self):
        """Test not skipping user frames."""
        config = FrameTracingConfig()
        handler = PathHandler()
        evaluator = FrameEvaluator(config, handler)

        frame = MagicMock()
        frame.f_code.co_filename = "user_script.py"
        
        assert evaluator.should_skip_frame(frame) is False
    
    def test_is_debugger_frame_path(self):
        """Test debugger frame detection by path."""
        config = FrameTracingConfig()
        handler = PathHandler()
        evaluator = FrameEvaluator(config, handler)

        frame = MagicMock()
        frame.f_code.co_filename = str(Path("dapper", "debugger_bdb.py"))
        frame.f_code.co_name = "some_function"

        with patch.object(handler, "is_debugger_path", return_value=True):
            assert evaluator.is_debugger_frame(frame) is True
    
    def test_is_debugger_frame_function(self):
        """Test debugger frame detection by function name."""
        config = FrameTracingConfig()
        handler = PathHandler()
        evaluator = FrameEvaluator(config, handler)
        
        frame = MagicMock()
        frame.f_code.co_filename = "user_script.py"
        frame.f_code.co_name = "user_line"
        
        assert evaluator.is_debugger_frame(frame) is True
    
    def test_is_not_debugger_frame(self):
        """Test non-debugger frame detection."""
        config = FrameTracingConfig()
        handler = PathHandler()
        evaluator = FrameEvaluator(config, handler)
        
        frame = MagicMock()
        frame.f_code.co_filename = "user_script.py"
        frame.f_code.co_name = "user_function"
        
        assert evaluator.is_debugger_frame(frame) is False


class TestCodeWrapper:
    """Test the CodeWrapper class."""
    
    def test_create_wrapper(self):
        """Test creating a code wrapper."""
        wrapper = CodeWrapper()
        code = wrapper.create_wrapper(42)
        
        assert isinstance(code, str)
        assert "lineno = 42" in code
        assert "_pydevd_frame_eval_wrapper" in code
    
    def test_create_wrapper_cached(self):
        """Test that the template is cached."""
        wrapper = CodeWrapper()
        code1 = wrapper.create_wrapper(42)
        code2 = wrapper.create_wrapper(100)
        
        # Both should use the same template but different line numbers
        assert code1 != code2
        assert "lineno = 42" in code1
        assert "lineno = 100" in code2


class TestCacheManager:
    """Test the CacheManager class."""
    
    def test_get_cache_key(self):
        """Test generating cache keys."""
        manager = CacheManager()
        code_obj = MagicMock()
        code_obj.co_filename = "test.py"
        code_obj.co_firstlineno = 1
        
        key = manager.get_cache_key(code_obj)
        assert isinstance(key, tuple)
        assert len(key) == 3
        assert key[1] == "test.py"
        assert key[2] == 1
    
    def test_invalidate_code_cache(self):
        """Test invalidating code cache."""
        manager = CacheManager()
        code_obj = MagicMock()
        code_obj.co_filename = "test.py"
        code_obj.co_firstlineno = 1
        
        # Add something to the cache
        key = manager.get_cache_key(code_obj)
        manager._trace_function_cache[key] = "dummy"
        
        # Add attribute to code object
        code_obj._frame_eval_cache = "dummy"
        
        # Invalidate
        manager.invalidate_code_cache(code_obj)
        
        # Check it's removed
        assert key not in manager._trace_function_cache
        assert not hasattr(code_obj, "_frame_eval_cache")
    
    def test_clear_all(self):
        """Test clearing all cached data."""
        manager = CacheManager()
        manager._trace_function_cache["test"] = "dummy"
        
        manager.clear_all()
        
        assert not manager._trace_function_cache


class TestBackwardCompatibility:
    """Test that the restructured module maintains backward compatibility."""
    
    def test_create_pydev_trace_code_wrapper(self):
        """Test the wrapper function works as before."""
        wrapper = ft.create_pydev_trace_code_wrapper(42)
        assert isinstance(wrapper, str)
        assert "lineno = 42" in wrapper
    
    def test_update_globals_dict(self):
        """Test updating globals dictionary."""
        globals_dict = {}
        ft.update_globals_dict(globals_dict)
        
        assert globals_dict["_pydevd_frame_eval_active"] is True
        assert globals_dict["_pydevd_frame_eval_line"] is None
        assert globals_dict["_pydevd_frame_eval_filename"] is None
    
    def test_should_skip_frame(self):
        """Test the should_skip_frame function."""
        frame = MagicMock()
        frame.f_code.co_filename = str(Path("dapper") / "debugger_bdb.py")
        
        # Mock the evaluator's should_skip_frame method
        with patch.object(ft._evaluator, "should_skip_frame", return_value=True) as mock_skip:
            assert ft.should_skip_frame(frame) is True
            mock_skip.assert_called_once_with(frame)
    
    def test_get_frame_filename(self):
        """Test getting normalized frame filenames."""
        frame = MagicMock()
        test_path = "test.py"
        frame.f_code.co_filename = test_path
        
        # Mock the path handler's normalize_path method
        with patch.object(ft._path_handler, "normalize_path") as mock_normalize:
            expected_path = str(Path(test_path).absolute())
            mock_normalize.return_value = expected_path
            
            result = ft.get_frame_filename(frame)
            assert result == expected_path
            mock_normalize.assert_called_once_with(test_path)
    
    def test_is_debugger_frame(self):
        """Test debugger frame detection."""
        frame = MagicMock()
        frame.f_code.co_filename = str(Path("dapper") / "debugger_bdb.py")
        frame.f_code.co_name = "some_function"
        
        # Mock the evaluator's is_debugger_frame method
        with patch.object(ft._evaluator, "is_debugger_frame", return_value=True) as mock_debug:
            assert ft.is_debugger_frame(frame) is True
            mock_debug.assert_called_once_with(frame)
    
    def test_get_frame_info(self):
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
    
    def test_get_frame_info_error(self):
        """Test frame information extraction with error."""
        frame = MagicMock()
        frame.f_lineno = 10
        frame.f_code.co_name = "test_function"
        frame.f_code.co_filename = "test_file.py"
        
        with patch("dapper._frame_eval.frame_tracing.get_frame_filename", side_effect=Exception("Test error")):
            info = ft.get_frame_info(frame)
            
            # Should return fallback info
            assert info["lineno"] == 10
            assert info["function"] == "test_function"
            assert info["filename"] == "test_file.py"
            assert info["code_object"] == frame.f_code
            assert info["is_debugger_frame"] is False
            assert info["should_skip"] is True
    
    def test_create_trace_function_wrapper(self):
        """Test trace function wrapper creation."""
        mock_trace = MagicMock()
        wrapper = ft.create_trace_function_wrapper(mock_trace)
        
        # Test with a frame that should be skipped
        frame = MagicMock()
        with patch("dapper._frame_eval.frame_tracing.should_skip_frame", return_value=True):
            result = wrapper(frame, "line", None)
            mock_trace.assert_called_once_with(frame, "line", None)
    
    def test_create_trace_function_wrapper_error(self):
        """Test trace function wrapper with error."""
        mock_trace = MagicMock()
        wrapper = ft.create_trace_function_wrapper(mock_trace)
        
        frame = MagicMock()
        with patch("dapper._frame_eval.frame_tracing.should_skip_frame", side_effect=Exception("Test error")):
            # Should fall back to original trace
            result = wrapper(frame, "line", None)
            mock_trace.assert_called_once_with(frame, "line", None)
    
    def test_invalidate_code_cache(self):
        """Test code cache invalidation."""
        code_obj = MagicMock()
        code_obj.co_filename = "test_file.py"
        code_obj.co_firstlineno = 1
        code_obj._frame_eval_cache = "dummy"
        
        ft.invalidate_code_cache(code_obj)
        
        assert not hasattr(code_obj, "_frame_eval_cache")
    
    def test_get_breakpoint_lines_for_file(self):
        """Test getting breakpoint lines."""
        lines = ft.get_breakpoint_lines_for_file("test.py")
        assert lines == set()
    
    def test_optimize_code_for_debugging(self):
        """Test code optimization."""
        code_obj = MagicMock()
        result = ft.optimize_code_for_debugging(code_obj)
        assert result is code_obj
    
    def test_setup_frame_tracing(self):
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
        finally:
            # Restore original state
            ft._tracing_enabled = original_tracing_enabled
    
    def test_setup_frame_tracing_error(self):
        """Test frame tracing setup with error."""
        with patch.object(FrameTracingConfig, "from_dict", side_effect=Exception("Test error")):
            assert ft.setup_frame_tracing({"enabled": True}) is False
    
    def test_cleanup_frame_tracing(self):
        """Test cleaning up frame tracing state."""
        # Save original state
        original_tracing_enabled = ft._tracing_enabled
        
        try:
            ft._tracing_enabled = True
            ft.cleanup_frame_tracing()
            assert ft._tracing_enabled is False
        finally:
            # Restore original state
            ft._tracing_enabled = original_tracing_enabled
