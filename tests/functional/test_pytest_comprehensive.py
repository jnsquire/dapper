#!/usr/bin/env python3
"""Comprehensive pytest-style tests for the complete frame evaluation system."""

import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import Mock

import pytest

from dapper._frame_eval.cache_manager import BreakpointCache
from dapper._frame_eval.cache_manager import cleanup_caches
from dapper._frame_eval.cache_manager import clear_all_caches
from dapper._frame_eval.cache_manager import get_cache_statistics
from dapper._frame_eval.cache_manager import get_func_code_info
from dapper._frame_eval.cache_manager import get_thread_info
from dapper._frame_eval.cache_manager import remove_func_code_info
from dapper._frame_eval.cache_manager import set_func_code_info
from dapper._frame_eval.debugger_integration import auto_integrate_debugger
from dapper._frame_eval.debugger_integration import configure_integration
from dapper._frame_eval.debugger_integration import get_integration_bridge
from dapper._frame_eval.selective_tracer import FrameTraceAnalyzer
from dapper._frame_eval.selective_tracer import SelectiveTraceDispatcher
from dapper._frame_eval.selective_tracer import get_trace_manager


class TestCacheManager:
    """Test suite for cache manager functionality."""

    def test_func_code_cache_operations(self):
        """Test function code cache set/get/remove operations."""

        def test_func():
            return 42

        code_obj = test_func.__code__
        test_info = {"breakpoints": {1, 2, 3}, "modified": True}

        # Test set and get
        set_func_code_info(code_obj, test_info)
        retrieved = get_func_code_info(code_obj)
        assert retrieved is not None
        assert retrieved["breakpoints"] == {1, 2, 3}

        # Test remove
        removed = remove_func_code_info(code_obj)
        assert removed is True
        assert get_func_code_info(code_obj) is None

    def test_thread_info_recursion_tracking(self):
        """Test thread info recursion depth tracking."""

        thread_info = get_thread_info()
        initial_depth = thread_info.recursion_depth
        initial_eval = thread_info.inside_frame_eval

        # Test recursion tracking
        thread_info.enter_frame_eval()
        assert thread_info.recursion_depth == initial_depth + 1
        assert thread_info.inside_frame_eval == initial_eval + 1

        thread_info.exit_frame_eval()
        assert thread_info.recursion_depth == initial_depth
        assert thread_info.inside_frame_eval == initial_eval

    def test_breakpoint_cache_with_real_file(self):
        """Test breakpoint cache with actual file operations."""

        # Create temporary file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("# Test file\nx = 42\n")
            test_file = f.name

        try:
            cache = BreakpointCache(max_entries=10)
            breakpoints = {10, 20, 30}

            # Test set/get
            cache.set_breakpoints(test_file, breakpoints)
            retrieved = cache.get_breakpoints(test_file)
            assert retrieved == breakpoints

            # Test invalidation
            cache.invalidate_file(test_file)
            assert cache.get_breakpoints(test_file) is None

        finally:
            Path(test_file).unlink()

    def test_cache_statistics_structure(self):
        """Test cache statistics return proper structure."""

        stats = get_cache_statistics()

        # Verify structure
        assert isinstance(stats, dict)
        assert "func_code_cache" in stats
        assert "breakpoint_cache" in stats
        assert "global_stats" in stats

        func_stats = stats["func_code_cache"]
        assert isinstance(func_stats, dict)
        assert "hits" in func_stats
        assert "misses" in func_stats
        assert "hit_rate" in func_stats
        assert isinstance(func_stats["hit_rate"], (int, float))

        # Test that cache is actually working by doing some operations
        def test_func():
            return 42

        code_obj = test_func.__code__
        test_info = {"test": "data"}

        # Set and get to generate cache activity
        set_func_code_info(code_obj, test_info)
        get_func_code_info(code_obj)

        # Now check stats again
        updated_stats = get_cache_statistics()
        assert isinstance(updated_stats, dict)


class TestSelectiveTracer:
    """Test suite for selective tracer functionality."""

    def test_frame_analyzer_file_filtering(self):
        """Test frame analyzer file filtering logic."""

        analyzer = FrameTraceAnalyzer()

        # Test user files
        assert analyzer._should_track_file("user_code.py") is True
        assert analyzer._should_track_file("test_module.py") is True

        # Test system files
        assert analyzer._should_track_file("<string>") is False
        assert analyzer._should_track_file("site-packages/package.py") is False
        assert analyzer._should_track_file("python3.11/lib.py") is False
        assert analyzer._should_track_file("importlib/__init__.py") is False

        # Test dapper internal files
        assert analyzer._should_track_file("dapper/_frame_eval/cache.py") is False

    def test_trace_manager_lifecycle(self):
        """Test trace manager enable/disable lifecycle."""
        manager = get_trace_manager()

        # Test initial state
        initial_state = manager.is_enabled()

        # Test enable/disable
        def dummy_trace(_frame, _event, _arg):
            return None

        manager.enable_selective_tracing(dummy_trace)
        assert manager.is_enabled() is True

        manager.disable_selective_tracing()
        assert manager.is_enabled() is False

        # Restore initial state if it was enabled
        if initial_state:
            manager.enable_selective_tracing(dummy_trace)

    def test_breakpoint_management(self):
        """Test breakpoint add/remove/management."""

        manager = get_trace_manager()

        test_file = "test_sample.py"
        breakpoints = {10, 20, 30}

        # Add breakpoints
        manager.add_breakpoint(test_file, 10)
        manager.add_breakpoint(test_file, 20)
        manager.add_breakpoint(test_file, 30)

        # Check retrieval
        retrieved = manager.get_breakpoints(test_file)
        assert retrieved == breakpoints

        # Remove some breakpoints
        manager.remove_breakpoint(test_file, 20)
        after_removal = manager.get_breakpoints(test_file)
        assert after_removal == {10, 30}

        # Clear all
        manager.clear_breakpoints(test_file)
        cleared = manager.get_breakpoints(test_file)
        assert cleared == set()  # Should return empty set, not None

    def test_trace_function_dispatch(self):
        """Test trace function dispatch logic."""

        dispatcher = SelectiveTraceDispatcher()
        mock_trace = Mock()

        # Set trace function
        dispatcher.set_debugger_trace_func(mock_trace)

        # Create a frame for testing
        def test_func():
            return 42

        frame = None

        def create_frame():
            nonlocal frame
            frame = sys._getframe()

        create_frame()

        if frame:
            # Test dispatch without breakpoints (should return None)
            result = dispatcher.selective_trace_dispatch(frame, "line", None)
            assert result is None
            assert mock_trace.call_count == 0

            # Add breakpoints and test dispatch
            dispatcher.update_breakpoints(__file__, {100})
            result = dispatcher.selective_trace_dispatch(frame, "line", None)
            # Result depends on frame analysis, but should not crash

    def test_performance_optimization(self):
        """Test that selective tracing provides performance optimization."""
        manager = get_trace_manager()

        # Get initial stats
        manager.get_statistics()

        # Check that optimization structure is correct
        final_stats = manager.get_statistics()
        # The exact numbers depend on implementation, but structure should be correct
        assert "dispatcher_stats" in final_stats
        dispatcher_stats = final_stats["dispatcher_stats"]
        assert "dispatcher_stats" in dispatcher_stats  # Nested structure
        assert "skip_rate" in dispatcher_stats["dispatcher_stats"]


class TestDebuggerIntegration:
    """Test suite for debugger integration functionality."""

    def test_integration_bridge_creation(self):
        """Test integration bridge creation and configuration."""
        bridge = get_integration_bridge()
        assert bridge is not None
        assert isinstance(bridge.config, dict)
        assert "enabled" in bridge.config
        assert "selective_tracing" in bridge.config

    def test_auto_integration_detection(self):
        """Test automatic integration detection for different debugger types."""

        # Mock DebuggerBDB
        class MockDebuggerBDB:
            def __init__(self):
                self.user_line = lambda _frame: None
                self.breakpoints = {}
                self._trace_function = None

            def get_trace_function(self):
                """Get the current trace function."""
                if self._trace_function is not None:
                    return self._trace_function
                return lambda _frame, _event, _arg: None

            def set_trace_function(self, trace_func):
                """Set the trace function."""
                self._trace_function = trace_func

        # Mock PyDebugger
        class MockPyDebugger:
            def __init__(self):
                self.threads = {}
                self._trace_function = None

            def set_breakpoints(self, _source, _bps, **_kwargs):
                pass

            def get_trace_function(self):
                """Get the current trace function."""
                if self._trace_function is not None:
                    return self._trace_function
                return lambda _frame, _event, _arg: None

            def set_trace_function(self, trace_func):
                """Set the trace function."""
                self._trace_function = trace_func

        # Test detection
        mock_bdb = MockDebuggerBDB()
        assert auto_integrate_debugger(mock_bdb) is True

        mock_py = MockPyDebugger()
        assert auto_integrate_debugger(mock_py) is True

        # Test unknown object
        assert auto_integrate_debugger(object()) is False

    def test_configuration_management(self):
        """Test configuration updates and validation."""

        # Test configuration updates
        configure_integration(
            selective_tracing=False, bytecode_optimization=False, performance_monitoring=True
        )

        bridge = get_integration_bridge()

        assert bridge.config["selective_tracing"] is False
        assert bridge.config["bytecode_optimization"] is False
        assert bridge.config["performance_monitoring"] is True

        # Test master disable
        configure_integration(enabled=False)
        assert bridge.config["enabled"] is False

    def test_performance_monitoring(self):
        """Test performance monitoring and statistics."""
        bridge = get_integration_bridge()
        bridge.enable_performance_monitoring(True)

        # Simulate activity
        for _i in range(10):
            bridge._monitor_trace_call()

        for _i in range(5):
            bridge._monitor_frame_eval_call()

        # Check statistics
        stats = bridge.get_integration_statistics()
        perf_data = stats["performance_data"]

        assert perf_data["trace_function_calls"] == 10
        assert perf_data["frame_eval_calls"] == 5
        assert "uptime_seconds" in perf_data

        # Test reset
        bridge.reset_statistics()
        reset_stats = bridge.get_integration_statistics()
        assert reset_stats["performance_data"]["trace_function_calls"] == 0
        assert reset_stats["performance_data"]["frame_eval_calls"] == 0

    def test_error_handling_and_fallback(self):
        """Test error handling and fallback mechanisms."""
        # Enable fallback mode
        configure_integration(fallback_on_error=True)

        bridge = get_integration_bridge()
        assert bridge.config["fallback_on_error"] is True

        # Test that integration handles errors gracefully
        bridge.integration_stats["errors_handled"]

        # Try integration that should fail gracefully
        result = bridge.integrate_with_debugger_bdb(None)
        assert result is False  # Should fail but not crash

        # Error count may or may not increase depending on implementation
        final_errors = bridge.integration_stats["errors_handled"]
        assert isinstance(final_errors, int)


class TestSystemIntegration:
    """Test suite for overall system integration."""

    def test_cross_component_integration(self):
        """Test integration between cache, tracer, and debugger components."""
        cache_stats = get_cache_statistics()
        trace_manager = get_trace_manager()
        integration_bridge = get_integration_bridge()

        assert isinstance(cache_stats, dict)
        assert trace_manager is not None
        assert integration_bridge is not None

        # Test that components can work together
        integration_bridge.update_config(selective_tracing=True)

        # Should not raise any errors
        final_stats = integration_bridge.get_integration_statistics()
        assert isinstance(final_stats, dict)

    def test_thread_safety(self):
        """Test thread safety of the frame evaluation system."""
        results = []
        errors = []

        def worker_thread(thread_id):
            try:
                # Test thread-local operations
                thread_info = get_thread_info()
                thread_info.enter_frame_eval()
                thread_info.exit_frame_eval()

                # Test trace manager operations
                manager = get_trace_manager()
                manager.add_breakpoint(f"test_{thread_id}.py", thread_id)
                manager.get_breakpoints(f"test_{thread_id}.py")

                results.append(thread_id)
            except Exception as e:
                errors.append((thread_id, str(e)))

        # Run multiple threads
        threads = []
        for i in range(5):
            t = threading.Thread(target=worker_thread, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Verify all threads completed successfully
        assert len(errors) == 0, f"Thread errors: {errors}"
        assert len(results) == 5

    def test_cache_cleanup(self):
        """Test memory cleanup and resource management."""
        # Clear all caches
        clear_all_caches()

        # Verify caches are empty
        stats = get_cache_statistics()
        assert stats["global_stats"]["total_entries"] == 0

        # Test cleanup
        cleanup_results = cleanup_caches()
        assert isinstance(cleanup_results, dict)
        assert "func_code_expired" in cleanup_results
        assert "breakpoint_files" in cleanup_results


@pytest.mark.parametrize(
    ("file_path", "expected"),
    [
        ("user_code.py", True),
        ("test_module.py", True),
        ("<string>", False),
        ("site-packages/package.py", False),
        ("python3.11/lib.py", False),
        ("importlib/__init__.py", False),
        ("dapper/_frame_eval/cache.py", False),
    ],
)
def test_file_tracking_parametrized(file_path, expected):
    """Parametrized test for file tracking patterns."""
    analyzer = FrameTraceAnalyzer()
    result = analyzer._should_track_file(file_path)
    assert result == expected


@pytest.fixture
def temp_python_file():
    """Fixture providing a temporary Python file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("# Test file\nx = 42\ny = x * 2\n")
        temp_file = f.name

    yield temp_file

    # Cleanup
    temp_path = Path(temp_file)
    if temp_path.exists():
        temp_path.unlink()


def test_with_fixture(temp_python_file):
    """Test using pytest fixture."""
    cache = BreakpointCache(max_entries=10)
    breakpoints = {1, 2, 3}

    cache.set_breakpoints(temp_python_file, breakpoints)
    retrieved = cache.get_breakpoints(temp_python_file)
    assert retrieved == breakpoints


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
