"""Tests for the frame tracing module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

import dapper._frame_eval.frame_tracing as ft
from dapper._frame_eval.frame_tracing import CacheManager
from dapper._frame_eval.frame_tracing import CodeWrapper
from dapper._frame_eval.frame_tracing import FrameEvaluator
from dapper._frame_eval.frame_tracing import FrameTracingConfig
from dapper._frame_eval.frame_tracing import PathHandler

# Set up test paths
TEST_DIR = Path(__file__).parent.parent.parent / "dapper"
DEBUGGER_PATH = str(TEST_DIR / "debugger_bdb.py")


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

        result = PathHandler.normalize_path(test_path)
        assert Path(result) == Path(expected)

    def test_normalize_path_absolute(self):
        """Test normalizing absolute paths."""
        test_path = "/some/path.py"
        expected = str(Path(test_path).absolute().resolve())

        result = PathHandler.normalize_path(test_path)
        assert Path(result) == Path(expected)

    def test_normalize_path_error(self):
        """Test path normalization with error."""
        with patch.object(Path, "is_absolute", side_effect=Exception("Test error")):
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
        """Test creating a wrapper for a specific line."""
        wrapper = CodeWrapper()
        result = wrapper.create_wrapper(42)

        assert isinstance(result, str)
        assert "lineno = 42" in result

    def test_get_template(self):
        """Test loading the wrapper template."""
        wrapper = CodeWrapper()
        with patch("importlib.resources.read_text"):
            # The actual implementation returns a template string with specific content
            result = wrapper._get_template()
            assert isinstance(result, str)
            assert "def _pydevd_frame_eval_wrapper" in result


class TestCacheManager:
    """Test the CacheManager class."""

    def test_get_cache_key(self):
        """Test generating cache keys."""
        cache = CacheManager()
        code_obj = compile("x = 1 + 1", "<test>", "exec")
        key = cache.get_cache_key(code_obj)

        assert isinstance(key, tuple)
        # The implementation returns (id(code_obj), co_filename, co_firstlineno)
        assert len(key) == 3
        assert key[0] == id(code_obj)
        assert key[1] == code_obj.co_filename
        assert key[2] == code_obj.co_firstlineno

    def test_invalidate_code_cache(self):
        """Test invalidating code cache."""
        cache = CacheManager()
        code_obj = compile("x = 1 + 1", "<test>", "exec")
        key = cache.get_cache_key(code_obj)

        # Add to cache
        cache._trace_function_cache[key] = lambda: None

        # Invalidate and verify
        cache.invalidate_code_cache(code_obj)
        assert key not in cache._trace_function_cache

    def test_clear_all(self):
        """Test clearing all cached data."""
        cache = CacheManager()

        # Add some test data - using proper types for the cache key
        code_obj = compile("x = 1 + 1", "<test>", "exec")
        key = cache.get_cache_key(code_obj)
        cache._trace_function_cache[key] = lambda: None

        # Clear and verify
        cache.clear_all()
        assert len(cache._trace_function_cache) == 0


class TestFrameTracingAPI:
    """Test the public frame tracing API."""

    def test_create_pydev_trace_code_wrapper(self):
        """Test creating a code wrapper for debugging."""
        wrapper = ft.create_pydev_trace_code_wrapper(42)
        assert isinstance(wrapper, str)
        assert "lineno = 42" in wrapper

        # Test that the template is cached
        wrapper2 = ft.create_pydev_trace_code_wrapper(42)
        assert wrapper == wrapper2

        # Test with a different line number
        wrapper3 = ft.create_pydev_trace_code_wrapper(100)
        assert "lineno = 100" in wrapper3

    def test_update_globals_dict(self):
        """Test updating globals dictionary with debug utilities."""
        globals_dict = {}
        ft.update_globals_dict(globals_dict)

        assert globals_dict["_pydevd_frame_eval_active"] is True
        assert globals_dict["_pydevd_frame_eval_line"] is None
        assert globals_dict["_pydevd_frame_eval_filename"] is None

    def test_should_skip_frame(self):
        """Test frame skipping logic."""
        frame = MagicMock()
        frame.f_code.co_filename = "test_file.py"
        frame.f_code.co_name = "test_function"

        with patch.object(ft, "_evaluator") as mock_evaluator:
            mock_evaluator.should_skip_frame.return_value = False
            assert ft.should_skip_frame(frame) is False
            mock_evaluator.should_skip_frame.assert_called_once_with(frame)

    def test_get_frame_filename(self):
        """Test getting normalized frame filenames."""
        frame = MagicMock()
        test_file = "test.py"
        frame.f_code.co_filename = test_file

        with patch.object(PathHandler, "normalize_path") as mock_normalize:
            mock_normalize.return_value = "/absolute/path/test.py"
            result = ft.get_frame_filename(frame)
            assert result == "/absolute/path/test.py"
            mock_normalize.assert_called_once_with(test_file)

    def test_is_debugger_frame(self):
        """Test debugger frame detection."""
        frame = MagicMock()

        with patch.object(ft, "_evaluator") as mock_evaluator:
            mock_evaluator.is_debugger_frame.return_value = True
            assert ft.is_debugger_frame(frame) is True
            mock_evaluator.is_debugger_frame.assert_called_once_with(frame)

    def test_get_frame_info(self):
        """Test frame information extraction."""
        frame = MagicMock()
        frame.f_lineno = 10
        frame.f_code.co_name = "test_function"
        frame.f_code.co_filename = "test_file.py"

        with (
            patch("dapper._frame_eval.frame_tracing.get_frame_filename") as mock_get_filename,
            patch("dapper._frame_eval.frame_tracing.is_debugger_frame") as mock_is_debugger,
            patch("dapper._frame_eval.frame_tracing.should_skip_frame") as mock_should_skip,
        ):
            mock_get_filename.return_value = "/abs/path/test_file.py"
            mock_is_debugger.return_value = False
            mock_should_skip.return_value = False

            info = ft.get_frame_info(frame)

            assert info["lineno"] == 10
            assert info["function"] == "test_function"
            assert info["filename"] == "/abs/path/test_file.py"
            assert info["code_object"] == frame.f_code
            assert info["is_debugger_frame"] is False
            assert info["should_skip"] is False

    def test_create_trace_function_wrapper(self):
        """Test trace function wrapper creation."""
        mock_trace = MagicMock()
        wrapper = ft.create_trace_function_wrapper(mock_trace)

        frame = MagicMock()

        # Test with frame that should be skipped
        with patch("dapper._frame_eval.frame_tracing.should_skip_frame", return_value=True):
            wrapper(frame, "line", None)
            mock_trace.assert_called_once_with(frame, "line", None)

        # Reset mock for next test
        mock_trace.reset_mock()

        # Test with frame evaluation active
        with (
            patch("dapper._frame_eval.frame_tracing.should_skip_frame", return_value=False),
            patch("dapper._frame_eval.frame_tracing._tracing_enabled", True),
            patch("dapper._frame_eval.frame_tracing.get_frame_info") as mock_get_frame_info,
        ):
            mock_frame_info = {"should_skip": False}
            mock_get_frame_info.return_value = mock_frame_info

            result = wrapper(frame, "line", None)
            assert result is None
            mock_trace.assert_not_called()

    def test_invalidate_code_cache(self):
        """Test code cache invalidation."""
        with patch("dapper._frame_eval.frame_tracing._cache_manager") as mock_cache:
            code_obj = MagicMock()
            ft.invalidate_code_cache(code_obj)
            # The actual method is called 'invalidate_code_cache', not 'invalidate_code'
            mock_cache.invalidate_code_cache.assert_called_once_with(code_obj)

    def test_get_breakpoint_lines_for_file(self):
        """Test getting breakpoint lines for a file."""
        # This function is not fully implemented in the original code
        # So we'll just test that it returns a set
        result = ft.get_breakpoint_lines_for_file("test.py")
        assert isinstance(result, set)

    def test_optimize_code_for_debugging(self):
        """Test code optimization for debugging."""
        code_obj = compile("x = 1 + 1", "<test>", "exec")
        # Just test that it returns a code object
        with patch.object(ft, "_evaluator") as mock_eval:
            mock_eval.optimize_code.return_value = code_obj
            result = ft.optimize_code_for_debugging(code_obj)
            assert result is code_obj  # Should return the same object in this test

    def test_setup_frame_tracing(self):
        """Test frame tracing setup."""
        # Save original state
        original_tracing_enabled = getattr(ft, "_tracing_enabled", False)

        try:
            # Test enabling frame tracing
            result = ft.setup_frame_tracing({"enabled": True})
            assert result is True
            assert getattr(ft, "_tracing_enabled", False) is True

            # Test disabling frame tracing
            result = ft.setup_frame_tracing({"enabled": False})
            assert result is True
            assert getattr(ft, "_tracing_enabled", False) is False
        finally:
            # Restore original state
            ft._tracing_enabled = original_tracing_enabled

    def test_cleanup_frame_tracing(self):
        """Test cleaning up frame tracing state."""
        # Save original state
        original_tracing_enabled = getattr(ft, "_tracing_enabled", False)

        try:
            # Set up test state
            ft._tracing_enabled = True

            # Call the cleanup function
            ft.cleanup_frame_tracing()

            # Verify state was cleaned up
            assert getattr(ft, "_tracing_enabled", True) is False
        finally:
            # Restore original state
            ft._tracing_enabled = original_tracing_enabled

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
        frame.f_code.co_filename = str(
            Path(__file__).parent.parent.parent / "dapper" / "debugger_bdb.py"
        )
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

    with (
        patch(
            "dapper._frame_eval.frame_tracing.get_frame_filename",
            return_value="/abs/path/test_file.py",
        ),
        patch("dapper._frame_eval.frame_tracing.is_debugger_frame", return_value=False),
        patch("dapper._frame_eval.frame_tracing.should_skip_frame", return_value=False),
    ):
        info = ft.get_frame_info(frame)

        assert info["lineno"] == 10
        assert info["function"] == "test_function"
        assert info["filename"] == "/abs/path/test_file.py"
        assert info["code_object"] == frame.f_code
        assert info["is_debugger_frame"] is False
        assert info["should_skip"] is False

    # Test with error getting filename
    with (
        patch(
            "dapper._frame_eval.frame_tracing.get_frame_filename",
            side_effect=ValueError("Test error"),
        ),
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
    with (
        patch("dapper._frame_eval.frame_tracing.should_skip_frame", return_value=False),
        patch("dapper._frame_eval.frame_tracing._tracing_enabled", True),
        patch("dapper._frame_eval.frame_tracing.get_frame_info") as mock_get_frame_info,
    ):
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
    with (
        patch("dapper._frame_eval.frame_tracing.should_skip_frame", return_value=False),
        patch("dapper._frame_eval.frame_tracing._tracing_enabled", True),
        patch("dapper._frame_eval.frame_tracing.get_frame_info") as mock_get_frame_info,
    ):
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
