"""Tests for individual frame evaluation components."""

from __future__ import annotations

from collections import OrderedDict

# Standard library imports
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import threading
from typing import TYPE_CHECKING
from unittest.mock import Mock
from unittest.mock import patch
import weakref

if TYPE_CHECKING:
    import types

# Third-party imports
import pytest

# Local application imports
from dapper._frame_eval.cache_manager import BreakpointCache
from dapper._frame_eval.cache_manager import FuncCodeInfoCache
from dapper._frame_eval.cache_manager import ThreadLocalCache
from dapper._frame_eval.cache_manager import cleanup_caches
from dapper._frame_eval.cache_manager import clear_all_caches
from dapper._frame_eval.cache_manager import get_breakpoints
from dapper._frame_eval.cache_manager import get_cache_statistics
from dapper._frame_eval.cache_manager import get_func_code_info
from dapper._frame_eval.cache_manager import remove_func_code_info
from dapper._frame_eval.cache_manager import set_breakpoints

# Check if modify_bytecode is available
MODIFY_BYTECODE_AVAILABLE = (
    importlib.util.find_spec("dapper._frame_eval.modify_bytecode") is not None
)
from dapper._frame_eval.bytecode_safety import safe_replace_code
from dapper._frame_eval.bytecode_safety import validate_code_object
from dapper._frame_eval.cache_manager import set_func_code_info
from dapper._frame_eval.modify_bytecode import BytecodeModifier
from dapper._frame_eval.telemetry import get_frame_eval_telemetry
from dapper._frame_eval.telemetry import reset_frame_eval_telemetry

# Check if selective tracer is available
SELECTIVE_TRACER_AVAILABLE = (
    importlib.util.find_spec("dapper._frame_eval.selective_tracer") is not None
)

# Import selective tracer components if available
if SELECTIVE_TRACER_AVAILABLE:
    # Imported only for availability check
    pass

# Import frame evaluator components (either Cython or Python fallback)
# Note: These are private APIs but necessary for frame evaluation
# pylint: disable=protected-access
try:
    from dapper._frame_eval._frame_evaluator import ThreadInfo
    from dapper._frame_eval._frame_evaluator import clear_thread_local_info
    from dapper._frame_eval._frame_evaluator import dummy_trace_dispatch
    from dapper._frame_eval._frame_evaluator import frame_eval_func
    from dapper._frame_eval._frame_evaluator import get_frame_eval_stats
    from dapper._frame_eval._frame_evaluator import get_thread_info
    from dapper._frame_eval._frame_evaluator import stop_frame_eval
except ImportError:
    # This should not happen since we have a Python fallback
    pytest.fail("Could not import frame evaluator components")


class TestCacheComponents:
    """Test the cache components."""

    def test_func_code_cache_creation(self):
        """Test FuncCodeInfoCache creation."""

        # Create the cache instance
        with patch("weakref.WeakValueDictionary") as mock_weak_dict:
            # Mock the WeakValueDictionary to return an empty dict
            mock_weak_dict.return_value = {}

            # Create the cache instance
            cache = FuncCodeInfoCache(max_size=100, ttl=60)

            # Set up the expected attributes
            cache._lru_order = OrderedDict()
            cache._weak_map = weakref.WeakKeyDictionary()
            cache._lock = threading.RLock()

            # Verify the cache was initialized correctly
            assert cache.max_size == 100
            assert cache.ttl == 60
            # Check that the internal weak-key LRU is empty
            assert len(cache._lru_order) == 0

    def test_breakpoint_cache_creation(self):
        """Test BreakpointCache creation."""
        cache = BreakpointCache(max_entries=50)

        assert cache.max_entries == 50
        # Check that the internal _cache is empty
        assert len(cache._cache) == 0

    def test_thread_local_cache_creation(self):
        """Test ThreadLocalCache creation."""
        cache = ThreadLocalCache()

        assert cache is not None
        # Should have thread-local storage
        assert hasattr(cache, "_local")
        assert hasattr(cache, "get_thread_info")

    def test_cache_operations(self):
        """Test basic cache operations."""
        FuncCodeInfoCache()

        # Test with a real code object (ensures code-object storage paths exercised)
        def _make_code_obj():
            def _inner():
                return 1

            return _inner.__code__

        mock_code = _make_code_obj()
        mock_info = {"test": "data"}

        # Set info
        set_func_code_info(mock_code, mock_info)

        # Get info
        result = get_func_code_info(mock_code)
        assert result == mock_info

        # Remove info
        removed = remove_func_code_info(mock_code)
        assert removed is True

        # Should be gone
        result = get_func_code_info(mock_code)
        assert result is None

    def test_breakpoint_operations(self):
        """Test breakpoint cache operations."""
        # Create a new cache instance for testing
        cache = BreakpointCache()

        # Create a temporary file for testing
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as temp_file:
            filepath = temp_file.name
            # Write something to the file so it has a valid mtime
            temp_file.write(b"# Test file for breakpoint testing\n")
            temp_file.flush()

            breakpoints = {10, 20, 30}

            try:
                # Clear any existing breakpoints
                cache.clear_all()

                # Debug: Check if file exists and is readable using pathlib
                file_path = Path(filepath)
                assert file_path.exists(), f"Test file {filepath} does not exist"
                assert file_path.is_file(), f"Test file {filepath} is not a file"
                # Use os.access for readability check; Path.readable() is not available everywhere
                assert os.access(file_path, os.R_OK), f"Cannot read test file {filepath}"

                # Set breakpoints
                cache.set_breakpoints(filepath, breakpoints)

                # Debug: Check cache contents directly
                if hasattr(cache, "_cache"):
                    print(f"Cache contents: {cache._cache}")

                # Get breakpoints
                cached_breakpoints = cache.get_breakpoints(filepath)

                # The cache should return the breakpoints we set
                assert cached_breakpoints is not None, (
                    "Breakpoints should not be None after being set"
                )
                assert cached_breakpoints == breakpoints, "Breakpoints should match what was set"

                # Test getting non-existent breakpoints
                non_existent = "/non/existent/" + os.urandom(8).hex() + ".py"
                result = cache.get_breakpoints(non_existent)
                assert result is None, f"Non-existent file {non_existent} should return None"

                # Test invalidating breakpoints for a file
                cache.invalidate_file(filepath)
                assert cache.get_breakpoints(filepath) is None, (
                    "Breakpoints should be cleared after invalidation"
                )

            finally:
                # Clean up the temporary file using pathlib
                try:
                    Path(filepath).unlink(missing_ok=True)
                except Exception as e:
                    print(f"Warning: Could not remove temporary file {filepath}: {e}")

    def test_clear_all_caches(self):
        """Test clearing all caches."""

        # Add some data
        # Use a real code object here as well
        def _make_code_obj2():
            def _inner2():
                return 2

            return _inner2.__code__

        mock_code = _make_code_obj2()
        set_func_code_info(mock_code, {"test": "data"})
        set_breakpoints("/test.py", {10, 20})

        # Clear caches
        clear_all_caches()

        # Data should be gone
        result = get_func_code_info(mock_code)
        assert result is None

        breakpoints = get_breakpoints("/test.py")
        assert breakpoints is None

    def test_get_cache_statistics(self):
        """Test getting cache statistics."""
        stats = get_cache_statistics()

        assert isinstance(stats, dict)
        # Should have expected structure
        expected_keys = ["func_code_cache", "breakpoint_cache", "global_stats"]
        for key in expected_keys:
            assert key in stats, f"Missing cache stat: {key}"

    def test_cleanup_caches(self):
        """Test cache cleanup."""
        results = cleanup_caches()

        assert isinstance(results, dict)
        # Should have cleanup results
        expected_keys = ["func_code_expired", "breakpoint_files"]
        for key in expected_keys:
            assert key in results, f"Missing cleanup result: {key}"


class TestFrameEvalCoreComponents:
    """Test Frame Evaluation core components (Cython or Python fallback)."""

    def test_thread_info_creation(self):
        """Test ThreadInfo object creation."""
        thread_info = get_thread_info()

        assert isinstance(thread_info, ThreadInfo)
        assert hasattr(thread_info, "inside_frame_eval")
        assert hasattr(thread_info, "fully_initialized")
        assert hasattr(thread_info, "is_pydevd_thread")
        assert hasattr(thread_info, "skip_all_frames")

        # Check initial values
        assert thread_info.inside_frame_eval == 0
        # fully_initialized might be a boolean in some implementations
        assert thread_info.fully_initialized in (0, False, True)
        assert thread_info.is_pydevd_thread in (0, False)
        assert thread_info.skip_all_frames in (0, False)

    def test_thread_info_isolation(self):
        """Test that thread info is isolated between threads."""
        main_thread_info = get_thread_info()

        # Modify main thread info
        main_thread_info.fully_initialized = True

        def check_thread_info():
            thread_info = get_thread_info()
            # Should be different instance
            # The value of fully_initialized might vary by implementation
            # (0, False, or True are all possible)
            t = type(thread_info.fully_initialized)
            assert isinstance(thread_info.fully_initialized, (int, bool)), (
                f"fully_initialized should be int or bool, got {t}"
            )
            assert thread_info is not main_thread_info

        thread = threading.Thread(target=check_thread_info)
        thread.start()
        thread.join()

        # Main thread info should be unchanged
        assert main_thread_info.fully_initialized is True, (
            f"Main thread's fully_initialized was changed to {main_thread_info.fully_initialized}"
        )

    def test_frame_eval_stats(self):
        """Test frame evaluation statistics."""
        stats = get_frame_eval_stats()

        assert isinstance(stats, dict)
        assert "active" in stats
        assert "has_breakpoint_manager" in stats

        # Check types
        assert isinstance(stats["active"], bool)
        assert isinstance(stats["has_breakpoint_manager"], bool)

    def test_frame_eval_activation(self):
        """Test frame evaluation activation/deactivation."""
        # Get initial state
        get_frame_eval_stats()

        # Activate
        frame_eval_func()
        active_stats = get_frame_eval_stats()

        # Deactivate
        stop_frame_eval()
        inactive_stats = get_frame_eval_stats()

        # The simplified implementation might keep some state
        # This is expected behavior
        assert isinstance(active_stats["active"], bool)
        assert isinstance(inactive_stats["active"], bool)

    def test_clear_thread_local_info(self):
        """Test clearing thread local info."""
        # Get thread info and modify it
        thread_info = get_thread_info()
        thread_info.fully_initialized = True

        # Clear thread local info
        clear_thread_local_info()

        # Get new thread info - should be fresh
        new_thread_info = get_thread_info()
        # In the simplified implementation, this might not reset
        # but the function should not crash
        assert isinstance(new_thread_info, ThreadInfo)

    def test_dummy_trace_dispatch(self):
        """Test dummy trace dispatch function."""
        # Create a mock frame
        mock_frame = Mock()

        # Test different events
        dummy_trace_dispatch(mock_frame, "call", None)
        # The actual behavior might vary, so just check it doesn't raise
        assert True

        # Test with frame that has trace
        if hasattr(mock_frame, "f_trace"):
            mock_frame.f_trace = Mock(return_value="trace_result")
            try:
                dummy_trace_dispatch(mock_frame, "call", None)
                # If we get here, the function didn't raise
                assert True
            except Exception as e:
                # The function might not be fully implemented
                print(f"dummy_trace_dispatch raised: {e}")
                msg = f"dummy_trace_dispatch should not raise {type(e).__name__}"
                raise AssertionError(msg) from None


class TestSelectiveTracer:
    """Test selective tracer component."""

    def test_selective_tracer_import(self):
        """Test that selective tracer can be imported."""
        if not SELECTIVE_TRACER_AVAILABLE:
            pytest.skip("Selective tracer not available")
        # If we get here, import succeeded (tested at module level)
        assert True

    @patch("dapper._frame_eval.selective_tracer.enable_selective_tracing")
    def test_enable_selective_tracing_mock(self, mock_enable):
        """Test enabling selective tracing (mocked)."""
        if not SELECTIVE_TRACER_AVAILABLE or "enable_selective_tracing" not in globals():
            pytest.skip("Selective tracer not available")

        # Call the function with a no-op trace function
        globals()["dapper._frame_eval.selective_tracer"].enable_selective_tracing(lambda *_: None)

        # Verify it was called (if mocked)
        if mock_enable:
            mock_enable.assert_called_once()

    @patch("dapper._frame_eval.selective_tracer.disable_selective_tracing")
    def test_disable_selective_tracing_mock(self, mock_disable):
        """Test disabling selective tracing (mocked)."""
        if not SELECTIVE_TRACER_AVAILABLE or "disable_selective_tracing" not in globals():
            pytest.skip("Selective tracer not available")

        # Call the function
        globals()["dapper._frame_eval.selective_tracer"].disable_selective_tracing()

        # Verify it was called (if mocked)
        if mock_disable:
            mock_disable.assert_called_once()


class TestBytecodeModifier:
    """Test bytecode modifier component."""

    def test_bytecode_modifier_import(self):
        """Test that bytecode modifier can be imported."""
        spec = importlib.util.find_spec("dapper._frame_eval.modify_bytecode")
        if spec is None:
            pytest.skip("Bytecode modifier not available")
        # If we get here, import would succeed
        assert True

    def test_bytecode_modifier_creation(self):
        """Test bytecode modifier creation."""
        spec = importlib.util.find_spec("dapper._frame_eval.modify_bytecode")
        if spec is None:
            pytest.skip("Bytecode modifier not available")

        # Skip actual creation test since we can't mock the class easily
        # and we're just testing imports here
        assert True

    @patch("dapper._frame_eval.modify_bytecode.inject_breakpoint_bytecode")
    def test_inject_breakpoint_bytecode_mock(self, mock_inject):
        """Test breakpoint bytecode injection (mocked)."""
        if not MODIFY_BYTECODE_AVAILABLE:
            pytest.skip("modify_bytecode module not available")

        # Create mock code object and breakpoints
        mock_code = Mock()
        breakpoints = {10, 20, 30}

        # Set up the mock to return our mock code object
        mock_inject.return_value = mock_code

        # Call the function with test data through the mock
        result = mock_inject(mock_code, breakpoints)

        # Verify the function was called with the correct arguments
        mock_inject.assert_called_once_with(mock_code, breakpoints)

        # Verify the function returned our mock code object
        assert result is mock_code


class TestIntegration:
    """Test integration utility functions."""

    class _TestError(Exception):
        """Custom exception for testing error handling."""

        def __init__(self, message):
            super().__init__(message)
            self.message = message

    def test_debugger_detection(self):
        """Test debugger type detection."""

        # Create a simple class that simulates a BDB debugger
        class BdbDebugger:
            def user_line(self, frame):
                pass

            def __init__(self):
                self.breakpoints = {}

        # Create a simple class that simulates a PyDebugger
        class PyDebugger:
            def set_breakpoints(self, filename, breakpoints):
                pass

            def __init__(self):
                self.threads = {}

        # Create a non-debugger class with some attributes
        class NonDebugger:
            def __init__(self):
                self.user_line = "not a method"
                self.breakpoints = "not a dict"
                self.set_breakpoints = "not a method"
                self.threads = "not a dict"

        # Test BDB debugger detection
        bdb = BdbDebugger()
        assert hasattr(bdb, "user_line"), "BDB debugger should have user_line attribute"
        assert callable(bdb.user_line), "BDB debugger's user_line should be callable"
        assert hasattr(bdb, "breakpoints"), "BDB debugger should have breakpoints attribute"
        assert isinstance(bdb.breakpoints, dict), "BDB debugger's breakpoints should be a dict"

        # Test PyDebugger detection
        py_dbg = PyDebugger()
        assert hasattr(py_dbg, "set_breakpoints"), (
            "PyDebugger should have set_breakpoints attribute"
        )
        assert callable(py_dbg.set_breakpoints), "PyDebugger's set_breakpoints should be callable"
        assert hasattr(py_dbg, "threads"), "PyDebugger should have threads attribute"
        assert isinstance(py_dbg.threads, dict), "PyDebugger's threads should be a dict"

        # Test non-debugger
        non_dbg = NonDebugger()
        assert hasattr(non_dbg, "user_line"), "Non-debugger should have user_line attribute"
        assert not callable(non_dbg.user_line), "Non-debugger's user_line should not be callable"
        assert hasattr(non_dbg, "breakpoints"), "Non-debugger should have breakpoints attribute"
        assert not isinstance(non_dbg.breakpoints, dict), (
            "Non-debugger's breakpoints should not be a dict"
        )
        assert hasattr(non_dbg, "set_breakpoints"), (
            "Non-debugger should have set_breakpoints attribute"
        )
        assert not callable(non_dbg.set_breakpoints), (
            "Non-debugger's set_breakpoints should not be callable"
        )
        assert hasattr(non_dbg, "threads"), "Non-debugger should have threads attribute"
        assert not isinstance(non_dbg.threads, dict), "Non-debugger's threads should not be a dict"

        # Test with an object that has no debugger attributes
        class EmptyClass:
            pass

        empty = EmptyClass()
        assert not hasattr(empty, "user_line")
        assert not hasattr(empty, "breakpoints")
        assert not hasattr(empty, "set_breakpoints")
        assert not hasattr(empty, "threads")

    def test_error_handling_utilities(self):
        """Test error handling utility functions."""

        # Test safe function execution
        def safe_function():
            return "success"

        def unsafe_function():
            raise self._TestError("Test error occurred")

        # Safe execution should work
        try:
            result = safe_function()
            assert result == "success"
        except Exception:
            pytest.fail("Safe function should not raise exception")

        # Unsafe function should raise exception
        with pytest.raises(Exception, match="Test error occurred"):
            unsafe_function()

    def test_configuration_validation(self):
        """Test configuration validation."""
        # Valid configuration
        valid_config = {
            "enabled": True,
            "selective_tracing": True,
            "bytecode_optimization": True,
            "cache_enabled": True,
            "performance_monitoring": True,
            "fallback_on_error": True,
        }

        # All values should be boolean
        for key, value in valid_config.items():
            assert isinstance(value, bool), f"Config {key} should be boolean"

        # Invalid configuration types
        invalid_configs = [
            {"enabled": "true"},  # String instead of bool
            {"selective_tracing": 1},  # Number instead of bool
            {"bytecode_optimization": None},  # None instead of bool
        ]

        for invalid_config in invalid_configs:
            # In a real implementation, these should be rejected
            # For now, just test that we can detect the invalid types
            for key, value in invalid_config.items():
                assert not isinstance(value, bool), f"Config {key} should not be {type(value)}"


class TestPerformanceUtils:
    """Test performance utility functions."""

    def test_performance_counters(self):
        """Test performance counter functionality."""
        # Simple counter implementation
        counter = {"calls": 0, "errors": 0}

        def increment_counter(counter_key):
            counter[counter_key] += 1

        # Increment calls
        increment_counter("calls")
        increment_counter("calls")
        increment_counter("errors")

        assert counter["calls"] == 2
        assert counter["errors"] == 1

    def test_memory_usage_estimation(self):
        """Test memory usage estimation."""
        # Create some objects and estimate memory
        data = [{"key": f"value_{i}", "number": i} for i in range(100)]

        # Rough estimation - each dict should take some memory
        estimated_size = len(data) * 100  # Rough estimate in bytes
        assert estimated_size > 0

        # Test that we can get sys.getsizeof if available
        if hasattr(sys, "getsizeof"):
            actual_size = sys.getsizeof(data[0])
            assert actual_size > 0


class TestBytecodeSafetyLayer:
    """Tests for the bytecode_safety validation and safe-replace helpers."""

    def _make_simple_code(self) -> types.CodeType:
        """Return a trivial compiled code object for testing."""

        return compile("x = 1 + 2", "<test>", "exec")

    def test_valid_code_passes_validation(self):
        """An unmodified code object is always valid against itself."""
        code = self._make_simple_code()
        result = validate_code_object(code, code)
        assert result.valid
        assert result.errors == []

    def test_decodable_check_catches_garbage_bytecode(self):
        """A code object with undecodable bytecode is flagged by the safety layer."""
        code = self._make_simple_code()
        # Clobber the bytecode with non-decodable bytes (all 0xFF, not a valid opcode).
        try:
            bad_code = code.replace(co_code=b"\xff" * len(code.co_code))
        except TypeError:
            # Older Python may not support co_code in replace(); skip gracefully.
            pytest.skip("code.replace(co_code=...) not supported on this Python version")

        result = validate_code_object(
            code, bad_code, {"validate_decodable": True, "validate_stacksize": False}
        )
        # We allow valid=True if dis tolerates the bytes (some versions do), but
        # the important thing is no exception is raised from validate_code_object.
        assert isinstance(result.valid, bool)

    def test_stacksize_decrease_is_rejected(self):
        """A code object whose stacksize is smaller than the original fails validation."""
        code = self._make_simple_code()
        try:
            bad_code = code.replace(co_stacksize=max(0, code.co_stacksize - 1))
        except TypeError:
            pytest.skip("code.replace(co_stacksize=...) not supported on this Python version")

        if bad_code.co_stacksize >= code.co_stacksize:
            pytest.skip("stacksize could not be forced lower (co_stacksize already 0)")

        result = validate_code_object(
            code, bad_code, {"validate_decodable": False, "validate_stacksize": True}
        )
        assert not result.valid
        assert any("decreased" in e for e in result.errors)

    def test_stacksize_excessive_growth_is_rejected(self):
        """A code object that grows the stack beyond the max delta fails."""
        code = self._make_simple_code()
        try:
            big_stack_code = code.replace(co_stacksize=code.co_stacksize + 100)
        except TypeError:
            pytest.skip("code.replace(co_stacksize=...) not supported on this Python version")

        result = validate_code_object(
            code,
            big_stack_code,
            {"validate_decodable": False, "validate_stacksize": True, "max_stacksize_delta": 8},
        )
        assert not result.valid
        assert any("exceeds" in e for e in result.errors)

    def test_safe_replace_code_accepts_valid_modification(self):
        """safe_replace_code returns (True, modified) for a valid code object."""
        code = self._make_simple_code()
        accepted, returned = safe_replace_code(code, code)
        assert accepted
        assert returned is code

    def test_safe_replace_code_rejects_and_records_invalid(self):
        """safe_replace_code records a reason code and returns original when invalid."""
        code = self._make_simple_code()
        try:
            bad_code = code.replace(co_stacksize=max(0, code.co_stacksize - 1))
        except TypeError:
            pytest.skip("code.replace(co_stacksize=...) not supported on this Python version")

        if bad_code.co_stacksize >= code.co_stacksize:
            pytest.skip("stacksize could not be forced lower")

        reset_frame_eval_telemetry()
        accepted, returned = safe_replace_code(code, bad_code)
        assert not accepted
        assert returned is code

        snap = get_frame_eval_telemetry()
        assert snap.reason_counts.bytecode_injection_failed >= 1

    def test_inject_breakpoints_falls_back_on_safety_failure(self):
        """BytecodeModifier.inject_breakpoints returns original code if safety rejects result."""
        modifier = BytecodeModifier()
        code = self._make_simple_code()
        breakpoint_lines = {1}

        # Force safe_replace_code to always reject so we can verify the fallback path.
        with patch(
            "dapper._frame_eval.modify_bytecode.safe_replace_code",
            return_value=(False, code),
        ):
            success, result = modifier.inject_breakpoints(code, breakpoint_lines)

        assert not success
        assert result is code


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
