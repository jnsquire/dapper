#!/usr/bin/env python3
"""
Core tests for frame evaluation system focusing on critical functionality.
"""

import threading
from typing import Any
from unittest.mock import Mock

import pytest

from dapper._frame_eval.cache_manager import cleanup_caches
from dapper._frame_eval.cache_manager import clear_all_caches
from dapper._frame_eval.cache_manager import get_breakpoints
from dapper._frame_eval.cache_manager import get_cache_statistics

# Import cache functions
from dapper._frame_eval.cache_manager import get_func_code_info
from dapper._frame_eval.cache_manager import remove_func_code_info
from dapper._frame_eval.cache_manager import set_breakpoints
from dapper._frame_eval.cache_manager import set_func_code_info

# Import core components
from dapper._frame_eval.debugger_integration import DebuggerFrameEvalBridge

# Import Cython modules for testing
CYTHON_AVAILABLE = False


# Define a protocol for ThreadInfo to ensure type safety
class ThreadInfoProtocol:
    """Protocol defining the ThreadInfo interface."""

    inside_frame_eval: bool
    fully_initialized: bool
    is_pydevd_thread: bool
    skip_all_frames: bool
    step_mode: bool


# Define default implementation
class DefaultThreadInfo(ThreadInfoProtocol):
    """Default implementation of ThreadInfoProtocol."""

    def __init__(self):
        self.inside_frame_eval = False
        self.fully_initialized = False
        self.is_pydevd_thread = False
        self.skip_all_frames = False
        self.step_mode = False


# Define default implementations
def default_frame_eval_func(*_args: Any, **_kwargs: Any) -> None:
    """Default frame evaluation function."""
    return


def default_get_frame_eval_stats() -> dict[str, Any]:
    """Default implementation for get_frame_eval_stats."""
    return {}


def default_get_thread_info() -> ThreadInfoProtocol:
    """Default implementation for get_thread_info."""
    return DefaultThreadInfo()


def default_stop_frame_eval() -> None:
    """Default implementation for stop_frame_eval."""
    return


# Initialize with default values
# Type ignore needed because we're dynamically assigning to ThreadInfo
ThreadInfo: type = DefaultThreadInfo  # type: ignore[assignment]
frame_eval_func = default_frame_eval_func
get_frame_eval_stats = default_get_frame_eval_stats
get_thread_info = default_get_thread_info
stop_frame_eval = default_stop_frame_eval

try:
    from dapper._frame_eval._frame_evaluator import ThreadInfo as CythonThreadInfo
    from dapper._frame_eval._frame_evaluator import frame_eval_func as cy_frame_eval_func
    from dapper._frame_eval._frame_evaluator import get_frame_eval_stats as cy_get_frame_eval_stats
    from dapper._frame_eval._frame_evaluator import get_thread_info as cy_get_thread_info
    from dapper._frame_eval._frame_evaluator import stop_frame_eval as cy_stop_frame_eval

    # Only set these if the imports succeed
    ThreadInfo = CythonThreadInfo
    frame_eval_func = cy_frame_eval_func
    get_frame_eval_stats = cy_get_frame_eval_stats
    get_thread_info = cy_get_thread_info
    stop_frame_eval = cy_stop_frame_eval
    CYTHON_AVAILABLE = True
except ImportError:
    # Fallback implementations for testing when Cython is not available
    class ThreadInfo:  # type: ignore[misc]
        """Mock ThreadInfo class for testing when Cython is not available."""

        inside_frame_eval: bool = False
        fully_initialized: bool = False
        is_pydevd_thread: bool = False
        skip_all_frames: bool = False
        step_mode: bool = False

    def mock_get_thread_info() -> "ThreadInfo":
        return ThreadInfo()

    def mock_get_frame_eval_stats() -> dict[str, Any]:
        return {
            "active": False,
            "has_breakpoint_manager": False,
            "frames_processed": 0,
            "frames_skipped": 0,
        }

    def mock_frame_eval_func(*args, **kwargs) -> None:
        pass

    def mock_stop_frame_eval() -> None:
        pass

    get_thread_info = mock_get_thread_info
    get_frame_eval_stats = mock_get_frame_eval_stats
    frame_eval_func = mock_frame_eval_func
    stop_frame_eval = mock_stop_frame_eval


class TestCoreDebuggerBridge:
    """Test core debugger bridge functionality."""

    def test_bridge_basic_functionality(self):
        """Test basic bridge functionality."""
        bridge = DebuggerFrameEvalBridge()

        # Test initial state
        assert bridge.config["enabled"] is True
        assert bridge.config["selective_tracing"] is True
        assert bridge.config["bytecode_optimization"] is True
        assert bridge.config["cache_enabled"] is True
        assert bridge.config["performance_monitoring"] is True
        assert bridge.config["fallback_on_error"] is True

        # Test stats initialization
        assert bridge.integration_stats["integrations_enabled"] == 0
        assert bridge.integration_stats["breakpoints_optimized"] == 0
        assert bridge.integration_stats["trace_calls_saved"] == 0
        assert bridge.integration_stats["bytecode_injections"] == 0
        assert bridge.integration_stats["errors_handled"] == 0

    def test_bridge_configuration_management(self):
        """Test bridge configuration management."""
        bridge = DebuggerFrameEvalBridge()

        # Test updating all config options
        bridge.update_config(
            enabled=False,
            selective_tracing=False,
            bytecode_optimization=False,
            cache_enabled=False,
            performance_monitoring=False,
            fallback_on_error=False,
        )

        # Verify all updates
        assert bridge.config["enabled"] is False
        assert bridge.config["selective_tracing"] is False
        assert bridge.config["bytecode_optimization"] is False
        assert bridge.config["cache_enabled"] is False
        assert bridge.config["performance_monitoring"] is False
        assert bridge.config["fallback_on_error"] is False

    def test_bridge_statistics_tracking(self):
        """Test bridge statistics tracking."""
        bridge = DebuggerFrameEvalBridge()

        # Get initial stats
        initial_stats = bridge.get_integration_statistics()
        assert initial_stats["integration_stats"]["integrations_enabled"] == 0

        # Simulate some activity
        bridge.integration_stats["integrations_enabled"] = 5
        bridge.integration_stats["breakpoints_optimized"] = 10
        bridge.integration_stats["trace_calls_saved"] = 100
        bridge.integration_stats["bytecode_injections"] = 2
        bridge.integration_stats["errors_handled"] = 1

        # Check updated stats
        updated_stats = bridge.get_integration_statistics()
        assert updated_stats["integration_stats"]["integrations_enabled"] == 5
        assert updated_stats["integration_stats"]["breakpoints_optimized"] == 10
        assert updated_stats["integration_stats"]["trace_calls_saved"] == 100
        assert updated_stats["integration_stats"]["bytecode_injections"] == 2
        assert updated_stats["integration_stats"]["errors_handled"] == 1

    def test_bridge_performance_monitoring(self):
        """Test bridge performance monitoring."""
        bridge = DebuggerFrameEvalBridge()

        # Test performance monitoring functions don't crash
        bridge._monitor_trace_call()
        bridge._monitor_frame_eval_call()

        # Check that performance data was updated
        assert bridge._performance_data["trace_function_calls"] == 1
        assert bridge._performance_data["frame_eval_calls"] == 1

        # Test with performance monitoring disabled
        bridge.update_config(performance_monitoring=False)
        initial_calls = bridge._performance_data["trace_function_calls"]

        bridge._monitor_trace_call()

        # Should not have updated when disabled
        assert bridge._performance_data["trace_function_calls"] == initial_calls

    def test_bridge_statistics_reset(self):
        """Test bridge statistics reset functionality."""
        bridge = DebuggerFrameEvalBridge()

        # Modify some stats
        bridge.integration_stats["integrations_enabled"] = 10
        bridge._performance_data["trace_function_calls"] = 50

        # Reset statistics
        bridge.reset_statistics()

        # Check they're reset to defaults
        assert bridge.integration_stats["integrations_enabled"] == 0
        assert bridge.integration_stats["breakpoints_optimized"] == 0
        assert bridge.integration_stats["trace_calls_saved"] == 0
        assert bridge.integration_stats["bytecode_injections"] == 0
        assert bridge.integration_stats["errors_handled"] == 0

        assert bridge._performance_data["trace_function_calls"] == 0
        assert bridge._performance_data["frame_eval_calls"] == 0
        assert bridge._performance_data["cache_hits"] == 0
        assert bridge._performance_data["cache_misses"] == 0


class TestCoreCacheFunctions:
    """Test core cache functions."""

    def test_func_code_info_operations(self):
        """Test function code info cache operations."""
        # Create mock code object
        mock_code = Mock()
        mock_info = {"test": "data", "breakpoints": [10, 20, 30]}

        # Test setting and getting info
        set_func_code_info(mock_code, mock_info)
        result = get_func_code_info(mock_code)
        assert result == mock_info

        # Test removing info
        removed = remove_func_code_info(mock_code)
        assert removed is True

        # Should be gone
        result = get_func_code_info(mock_code)
        assert result is None

        # Test removing non-existent info
        removed = remove_func_code_info(mock_code)
        assert removed is False

    def test_breakpoint_operations(self, tmp_path):
        """Test breakpoint cache operations."""
        # Create a temporary file for testing
        test_file = tmp_path / "test_file.py"
        test_file.write_text("# Test file for breakpoints\n")
        test_file_str = str(test_file)

        # Test setting and getting breakpoints
        breakpoints = {10, 20, 30}

        set_breakpoints(test_file_str, breakpoints)
        result = get_breakpoints(test_file_str)
        assert result == breakpoints, f"Expected {breakpoints}, got {result}"

        # Test getting non-existent breakpoints
        non_existent = str(tmp_path / "non_existent.py")
        result = get_breakpoints(non_existent)
        assert result is None, f"Expected None for non-existent file, got {result}"

        # Test overwriting breakpoints
        new_breakpoints = {15, 25}
        set_breakpoints(test_file_str, new_breakpoints)
        result = get_breakpoints(test_file_str)
        assert result == new_breakpoints, f"Expected {new_breakpoints} after update, got {result}"

    def test_cache_statistics_and_cleanup(self):
        """Test cache statistics and cleanup."""
        # Add some data to caches
        mock_code = Mock()
        set_func_code_info(mock_code, {"test": "data"})
        set_breakpoints("/test.py", {10, 20})

        # Test getting statistics
        stats = get_cache_statistics()
        assert isinstance(stats, dict)

        # Test cleanup
        cleanup_results = cleanup_caches()
        assert isinstance(cleanup_results, dict)

        # Test clearing all caches
        clear_all_caches()

        # Data should be gone
        assert get_func_code_info(mock_code) is None
        assert get_breakpoints("/test.py") is None


@pytest.mark.skipif(not CYTHON_AVAILABLE, reason="Cython modules not available")
class TestCoreCythonFunctions:
    """Test core Cython functions."""

    def test_thread_info_basic_operations(self):
        """Test basic thread info operations."""
        thread_info = get_thread_info()

        # Test that it's a ThreadInfo object
        assert isinstance(thread_info, ThreadInfo)

        # Test that it has expected attributes
        assert hasattr(thread_info, "inside_frame_eval")
        assert hasattr(thread_info, "fully_initialized")
        assert hasattr(thread_info, "is_pydevd_thread")
        assert hasattr(thread_info, "skip_all_frames")

        # Test that attributes are accessible (even if not the expected values)
        _ = thread_info.inside_frame_eval
        _ = thread_info.fully_initialized
        _ = thread_info.is_pydevd_thread
        _ = thread_info.skip_all_frames

    def test_frame_eval_stats_structure(self):
        """Test frame evaluation stats structure."""
        stats = get_frame_eval_stats()

        # Test that it's a dict
        assert isinstance(stats, dict)

        # Test that it has expected keys
        assert "active" in stats
        assert "has_breakpoint_manager" in stats

        # Test that values are expected types
        assert isinstance(stats["active"], bool)
        assert isinstance(stats["has_breakpoint_manager"], bool)

    def test_frame_eval_activation_cycle(self):
        """Test frame evaluation activation cycle."""
        # Get initial state
        initial_stats = get_frame_eval_stats()

        # Activate frame evaluation
        frame_eval_func()
        active_stats = get_frame_eval_stats()

        # Deactivate frame evaluation
        stop_frame_eval()
        inactive_stats = get_frame_eval_stats()

        # Test that functions don't crash and return expected types
        assert isinstance(initial_stats["active"], bool)
        assert isinstance(active_stats["active"], bool)
        assert isinstance(inactive_stats["active"], bool)

    def test_multiple_thread_info_access(self):
        """Test accessing thread info from multiple threads."""
        results = []

        def get_thread_info_in_thread():
            thread_info = get_thread_info()
            results.append(thread_info)

        # Create multiple threads
        threads = []
        for _i in range(5):
            thread = threading.Thread(target=get_thread_info_in_thread)
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # All threads should have gotten a ThreadInfo object
        assert len(results) == 5
        for thread_info in results:
            assert isinstance(thread_info, ThreadInfo)


class TestCoreIntegration:
    """Test core integration functionality."""

    def test_debugger_integration_bdb_basic(self):
        """Test basic BDB debugger integration."""
        bridge = DebuggerFrameEvalBridge()

        # Create mock BDB debugger
        debugger_bdb = Mock()
        debugger_bdb.user_line = Mock()
        debugger_bdb.breakpoints = {}

        # Test integration
        result = bridge.integrate_with_debugger_bdb(debugger_bdb)

        # Should succeed
        assert result is True

        # Should track integration
        assert bridge.integration_stats["integrations_enabled"] >= 1

        # Should store original function
        assert id(debugger_bdb) in bridge.original_trace_functions

    def test_debugger_integration_py_debugger_basic(self):
        """Test basic PyDebugger integration."""
        bridge = DebuggerFrameEvalBridge()

        # Create mock PyDebugger
        debugger_py = Mock()
        debugger_py.set_breakpoints = Mock()
        debugger_py.threads = Mock()

        # Test integration
        result = bridge.integrate_with_py_debugger(debugger_py)

        # Should succeed
        assert result is True

        # Should track integration
        assert bridge.integration_stats["integrations_enabled"] >= 1

    def test_debugger_integration_disabled(self):
        """Test integration when disabled."""
        bridge = DebuggerFrameEvalBridge()
        bridge.update_config(enabled=False)

        # Create mock debugger
        debugger_bdb = Mock()
        debugger_bdb.user_line = Mock()
        debugger_bdb.breakpoints = {}

        # Test integration
        result = bridge.integrate_with_debugger_bdb(debugger_bdb)

        # Should fail when disabled
        assert result is False

        # Should not track integration
        assert bridge.integration_stats["integrations_enabled"] == 0

    def test_debugger_removal(self):
        """Test debugger removal."""
        bridge = DebuggerFrameEvalBridge()

        # Create and integrate debugger
        debugger_bdb = Mock()
        debugger_bdb.user_line = Mock()
        debugger_bdb.breakpoints = {}

        # Integrate first
        integrate_result = bridge.integrate_with_debugger_bdb(debugger_bdb)
        assert integrate_result is True

        # Then remove
        remove_result = bridge.remove_integration(debugger_bdb)
        assert remove_result is True

        # Should clean up
        assert id(debugger_bdb) not in bridge.original_trace_functions


class TestCoreErrorHandling:
    """Test core error handling."""

    def test_none_debugger_handling(self):
        """Test handling of None debugger."""
        bridge = DebuggerFrameEvalBridge()

        # Should handle None gracefully
        result_bdb = bridge.integrate_with_debugger_bdb(None)
        result_py = bridge.integrate_with_py_debugger(None)

        assert result_bdb is False
        assert result_py is False

    def test_missing_attributes_handling(self):
        """Test handling of debuggers with missing attributes."""
        bridge = DebuggerFrameEvalBridge()

        # Create debugger without required attributes
        incomplete_debugger = Mock()
        del incomplete_debugger.user_line  # Remove user_line

        # Should handle missing attributes by creating a no-op user_line
        result = bridge.integrate_with_debugger_bdb(incomplete_debugger)
        assert result is True

        # Verify a user_line method was added
        assert hasattr(incomplete_debugger, "user_line")
        assert callable(incomplete_debugger.user_line)

    def test_statistics_access_safety(self):
        """Test that statistics access is safe."""
        bridge = DebuggerFrameEvalBridge()

        # Should be able to get stats without errors
        stats = bridge.get_integration_statistics()
        assert isinstance(stats, dict)

        # Should have all required sections
        required_sections = [
            "config",
            "integration_stats",
            "performance_data",
            "trace_manager_stats",
            "cache_stats",
        ]
        for section in required_sections:
            assert section in stats


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
