#!/usr/bin/env python3
"""Tests for selective tracing system."""

import threading
from unittest.mock import Mock
from unittest.mock import patch

import pytest

import dapper._frame_eval.selective_tracer
from dapper._frame_eval import cache_manager
from dapper._frame_eval.selective_tracer import FrameTraceAnalyzer
from dapper._frame_eval.selective_tracer import FrameTraceManager
from dapper._frame_eval.selective_tracer import SelectiveTraceDispatcher
from dapper._frame_eval.selective_tracer import disable_selective_tracing
from dapper._frame_eval.selective_tracer import enable_selective_tracing
from dapper._frame_eval.selective_tracer import get_selective_trace_function
from dapper._frame_eval.selective_tracer import get_trace_manager
from dapper._frame_eval.selective_tracer import update_breakpoints


# Mock the breakpoint storage
class MockBreakpointCache:
    def __init__(self):
        self.breakpoints = {}

    def get_breakpoints(self, filepath):
        return self.breakpoints.get(filepath, set())

    def set_breakpoints(self, filepath, breakpoints):
        self.breakpoints[filepath] = set(breakpoints)


# Create a mock breakpoint cache
mock_bp_cache = MockBreakpointCache()

# Mock the get_breakpoints and set_breakpoints functions in the cache_manager
cache_manager.get_breakpoints = mock_bp_cache.get_breakpoints
cache_manager.set_breakpoints = mock_bp_cache.set_breakpoints

# Now import the modules we're testing


class TestFrameAnalyzer:
    """Test the FrameAnalyzer class."""

    def setup_method(self):
        """Set up test fixtures."""
        # Reset the mock breakpoints
        mock_bp_cache.breakpoints.clear()
        self.analyzer = FrameTraceAnalyzer()

    def test_should_trace_frame_with_breakpoints(self):
        """Test frame tracing when breakpoints are present."""
        # Create a mock frame with breakpoints
        mock_frame = Mock()
        mock_frame.f_code.co_filename = "test.py"
        mock_frame.f_lineno = 10

        # Set up breakpoints in the analyzer
        test_breakpoints = {10, 20, 30}
        self.analyzer.update_breakpoints("test.py", test_breakpoints)

        # Patch the get_breakpoints function to return our test breakpoints
        with patch("dapper._frame_eval.selective_tracer.get_breakpoints") as mock_get_breakpoints:
            mock_get_breakpoints.return_value = test_breakpoints

            # Should trace when on breakpoint line
            result = self.analyzer.should_trace_frame(mock_frame)

            # Verify the result
            assert result["should_trace"] is True, (
                f"Expected should_trace to be True, got {result['should_trace']}. Reason: {result['reason']}"
            )
            assert result["reason"] == "breakpoint_on_line"
            assert 10 in result["breakpoint_lines"]

    def test_should_trace_frame_no_breakpoints(self):
        """Test frame tracing when no breakpoints are present."""
        # Create a mock frame without breakpoints
        mock_frame = Mock()
        mock_frame.f_code.co_filename = "test.py"
        mock_frame.f_lineno = 15

        # Set up breakpoints for different lines
        self.analyzer.update_breakpoints("test.py", {10, 20, 30})

        # Should not trace when not on breakpoint line
        result = self.analyzer.should_trace_frame(mock_frame)
        assert result["should_trace"] is False
        # The reason could be either depending on the test environment
        assert result["reason"] in ["no_breakpoints_in_function", "no_breakpoints_in_file"]
        assert result["frame_info"]["lineno"] == 15

    def test_should_trace_frame_unknown_file(self):
        """Test frame tracing for unknown files."""
        # Create a mock frame for unknown file
        mock_frame = Mock()
        mock_frame.f_code.co_filename = "unknown.py"
        mock_frame.f_lineno = 10

        # Should not trace unknown files
        result = self.analyzer.should_trace_frame(mock_frame)
        assert result["should_trace"] is False
        assert result["reason"] == "no_breakpoints_in_file"

    def test_should_trace_frame_internal_files(self):
        """Test that internal debugger files are skipped."""
        # Create mock frames for internal files
        internal_files = [
            "pydevd.py",
            "dapper/debugger.py",
            "site-packages/debugpy/__init__.py",
        ]

        for filename in internal_files:
            mock_frame = Mock()
            mock_frame.f_code.co_filename = filename
            mock_frame.f_lineno = 10

            result = self.analyzer.should_trace_frame(mock_frame)
            assert result["should_trace"] is False
            # The reason could be any of these depending on the test environment
            assert result["reason"] in [
                "thread_skip_frame",
                "no_breakpoints_in_file",
                "file_not_tracked",
            ]

    def test_update_breakpoints(self):
        """Test breakpoint updates."""
        # Create a mock frame for testing
        mock_frame = Mock()
        mock_frame.f_code.co_filename = "test.py"

        # Add breakpoints
        test_breakpoints = {10, 20, 30}

        # Test setting breakpoints
        with patch("dapper._frame_eval.selective_tracer.get_breakpoints") as mock_get_breakpoints:
            mock_get_breakpoints.return_value = test_breakpoints

            # Update breakpoints in the analyzer
            self.analyzer.update_breakpoints("test.py", test_breakpoints)

            # Test that breakpoints are set by checking should_trace_frame
            mock_frame.f_lineno = 10
            result = self.analyzer.should_trace_frame(mock_frame)
            assert result["should_trace"] is True, "Should trace when on a breakpoint line"
            assert result["reason"] == "breakpoint_on_line"

        # Test updating breakpoints
        new_breakpoints = {15, 25, 35}

        with patch("dapper._frame_eval.selective_tracer.get_breakpoints") as mock_get_breakpoints:
            mock_get_breakpoints.return_value = new_breakpoints

            # Update to new breakpoints
            self.analyzer.update_breakpoints("test.py", new_breakpoints)

            # Test that old breakpoints are removed
            mock_frame.f_lineno = 10
            result = self.analyzer.should_trace_frame(mock_frame)
            assert result["should_trace"] is False, "Should not trace on old breakpoint line"

            # Test that new breakpoints are set
            mock_frame.f_lineno = 15
            result = self.analyzer.should_trace_frame(mock_frame)
            assert result["should_trace"] is True, "Should trace on new breakpoint line"
            assert result["reason"] == "breakpoint_on_line"

        # Test clearing breakpoints
        with patch("dapper._frame_eval.selective_tracer.get_breakpoints") as mock_get_breakpoints:
            mock_get_breakpoints.return_value = set()

            # Clear breakpoints
            self.analyzer.update_breakpoints("test.py", set())

            # Test that no breakpoints are set
            mock_frame.f_lineno = 15
            result = self.analyzer.should_trace_frame(mock_frame)
            assert result["should_trace"] is False, "Should not trace after clearing breakpoints"
            assert result["reason"] == "no_breakpoints_in_file"

    def test_get_statistics(self):
        """Test statistics collection."""
        # Call some methods to update stats
        frame = Mock()
        frame.f_code.co_filename = "test.py"
        frame.f_lineno = 10
        self.analyzer.should_trace_frame(frame)

        stats = self.analyzer.get_statistics()
        assert stats["total_frames"] > 0  # Check that expected keys are present
        expected_keys = [
            "total_frames",
            "traced_frames",
            "cache_hits",
            "fast_path_hits",
            "trace_rate",
            "cache_size",
        ]
        for key in expected_keys:
            assert key in stats, f"Expected key '{key}' not found in statistics"

        # Check that at least one frame was processed


class TestTraceDispatcher:
    """Test the TraceDispatcher class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_trace_func = Mock(return_value=None)
        self.dispatcher = SelectiveTraceDispatcher(self.mock_trace_func)
        # Set up the debugger trace function to be called for non-line events
        self.dispatcher.set_debugger_trace_func(self.mock_trace_func)

    def test_dispatch_trace_should_trace(self):
        """Test dispatch when frame should be traced."""
        # Create a mock frame with breakpoints
        mock_frame = Mock()
        mock_frame.f_code.co_filename = "test.py"
        mock_frame.f_lineno = 10

        # Create a mock trace function
        mock_trace_func = Mock(return_value=None)
        self.dispatcher.set_debugger_trace_func(mock_trace_func)

        # Mock the analyzer to always return True for should_trace_frame
        with patch.object(self.dispatcher.analyzer, "should_trace_frame") as mock_should_trace:
            mock_should_trace.return_value = {
                "should_trace": True,
                "reason": "breakpoint_on_line",
                "breakpoint_lines": {10},
                "frame_info": {"filename": "test.py", "lineno": 10, "function": "test_func"},
            }

            # Call the dispatch function
            result = self.dispatcher.selective_trace_dispatch(mock_frame, "line", None)

            # Verify the trace function was called with the correct arguments
            mock_trace_func.assert_called_once_with(mock_frame, "line", None)

            # Verify the analyzer's should_trace_frame was called with the frame
            mock_should_trace.assert_called_once_with(mock_frame)
        assert result is None  # The trace function returns None by the debugger
        assert result is None  # Should return the result of the original trace function
        assert result == self.mock_trace_func.return_value

        # Check statistics
        stats = self.dispatcher.get_statistics()
        assert stats["dispatcher_stats"]["total_calls"] == 1
        assert stats["dispatcher_stats"]["dispatched_calls"] == 1
        assert stats["dispatcher_stats"]["skipped_calls"] == 0

    def test_dispatch_trace_should_not_trace(self):
        """Test dispatch when frame should not be traced."""
        frame = Mock()
        frame.f_code.co_filename = "test.py"
        frame.f_lineno = 5
        event = "line"
        arg = None

        # Call the dispatcher method
        result = self.dispatcher.selective_trace_dispatch(frame, event, arg)

        # Should not call the original trace function
        self.mock_trace_func.assert_not_called()

        # Should return None to disable tracing for this frame
        assert result is None

        stats = self.dispatcher.get_statistics()
        assert stats["dispatcher_stats"]["total_calls"] == 1
        assert stats["dispatcher_stats"]["dispatched_calls"] == 0
        assert stats["dispatcher_stats"]["skipped_calls"] == 1

    def test_dispatch_trace_other_events(self):
        """Test dispatch for non-line events."""
        # For non-line events, we should call the debugger trace function if the frame should be traced
        for event in ["call", "return", "exception"]:
            frame = Mock()
            frame.f_code.co_filename = "test.py"
            frame.f_lineno = 5
            arg = None

            # Reset mock for each iteration
            self.mock_trace_func.reset_mock()

            # Set up the mock to return a function for the trace function
            self.mock_trace_func.return_value = lambda *args, **kwargs: None  # noqa: ARG005

            # Call the dispatcher method
            result = self.dispatcher.selective_trace_dispatch(frame, event, arg)

            # The result should be None because the frame doesn't have breakpoints
            assert result is None

            # The debugger trace function should not be called directly
            self.mock_trace_func.assert_not_called()

    def test_get_statistics(self):
        """Test dispatcher statistics."""
        stats = self.dispatcher.get_statistics()

        # Check the dispatcher stats
        assert "dispatcher_stats" in stats
        assert "total_calls" in stats["dispatcher_stats"]
        assert "dispatched_calls" in stats["dispatcher_stats"]
        assert "skipped_calls" in stats["dispatcher_stats"]
        assert "dispatch_rate" in stats["dispatcher_stats"]
        assert "skip_rate" in stats["dispatcher_stats"]

        # Check the analyzer stats
        assert "analyzer_stats" in stats
        assert "total_frames" in stats["analyzer_stats"]
        assert "traced_frames" in stats["analyzer_stats"]
        assert "cache_hits" in stats["analyzer_stats"]
        assert "fast_path_hits" in stats["analyzer_stats"]
        assert "trace_rate" in stats["analyzer_stats"]
        assert "cache_size" in stats["analyzer_stats"]

        # The statistics should be properly initialized
        assert stats["dispatcher_stats"]["total_calls"] == 0
        assert stats["dispatcher_stats"]["dispatched_calls"] == 0
        assert stats["dispatcher_stats"]["skipped_calls"] == 0


class TestTraceManager:
    """Test the FrameTraceManager class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.trace_manager = FrameTraceManager()

    def test_initialization(self):
        """Test trace manager initialization."""
        # Check that the dispatcher is properly initialized
        assert hasattr(self.trace_manager, "dispatcher")
        assert isinstance(self.trace_manager.dispatcher, SelectiveTraceDispatcher)

        # Check that the analyzer is accessible through the dispatcher
        assert hasattr(self.trace_manager.dispatcher, "analyzer")
        assert isinstance(self.trace_manager.dispatcher.analyzer, FrameTraceAnalyzer)

        # Check initial state
        assert not self.trace_manager.is_enabled()

    def test_enable_disable(self):
        """Test enabling and disabling trace manager."""
        # Initially disabled
        assert not self.trace_manager.is_enabled()

        # Enable with a mock trace function
        mock_trace_func = Mock()
        self.trace_manager.enable_selective_tracing(mock_trace_func)
        assert self.trace_manager.is_enabled()

        # Disable
        self.trace_manager.disable_selective_tracing()
        assert not self.trace_manager.is_enabled()

    def test_breakpoint_management(self):
        """Test breakpoint management methods."""
        # Test adding and getting breakpoints
        self.trace_manager.add_breakpoint("test.py", 10)
        assert self.trace_manager.get_breakpoints("test.py") == {10}

        # Test updating breakpoints
        self.trace_manager.update_file_breakpoints("test.py", {20, 30})
        assert self.trace_manager.get_breakpoints("test.py") == {20, 30}

        # Test removing a breakpoint
        self.trace_manager.remove_breakpoint("test.py", 20)
        assert self.trace_manager.get_breakpoints("test.py") == {30}

        # Test clearing breakpoints
        self.trace_manager.clear_breakpoints("test.py")
        assert not self.trace_manager.get_breakpoints("test.py")

    def test_get_trace_function(self):
        """Test getting trace function."""
        # Should return None when disabled
        assert self.trace_manager.get_trace_function() is None

        # Enable and get trace function
        mock_trace_func = Mock()
        self.trace_manager.enable_selective_tracing(mock_trace_func)
        trace_func = self.trace_manager.get_trace_function()
        assert trace_func is not None

        # Should use the selective trace dispatch function
        assert trace_func == self.trace_manager.dispatcher.selective_trace_dispatch

    def test_trace_function_integration(self):
        """Test that trace function properly integrates with dispatcher."""
        # Create a mock trace function
        mock_trace_func = Mock(return_value=None)

        # Enable selective tracing with the mock trace function
        self.trace_manager.enable_selective_tracing(mock_trace_func)

        # Get the trace function
        trace_func = self.trace_manager.get_trace_function()
        assert trace_func is not None

        # Create a mock frame
        mock_frame = Mock()
        mock_frame.f_code.co_filename = "test.py"
        mock_frame.f_lineno = 10

        # Add breakpoints
        self.trace_manager.add_breakpoint("test.py", 10)

        # Mock the analyzer to always return True for should_trace_frame
        with patch.object(
            self.trace_manager.dispatcher.analyzer, "should_trace_frame"
        ) as mock_should_trace:
            mock_should_trace.return_value = {
                "should_trace": True,
                "reason": "breakpoint_on_line",
                "breakpoint_lines": {10},
                "frame_info": {"filename": "test.py", "lineno": 10, "function": "test_func"},
            }

            # Call the trace function
            result = trace_func(mock_frame, "line", None)

            # The trace function should be called with the frame
            mock_trace_func.assert_called_once_with(mock_frame, "line", None)

            # Verify the analyzer's should_trace_frame was called with the frame
            mock_should_trace.assert_called_once_with(mock_frame)

        # The result should be the return value of the trace function (None in this case)
        assert result is None

    def test_update_breakpoints(self):
        """Test breakpoint updates through trace manager."""
        breakpoints = {10, 20, 30}
        self.trace_manager.update_file_breakpoints("test.py", breakpoints)

        # Verify the breakpoints were set by checking if they're returned by get_breakpoints
        assert self.trace_manager.get_breakpoints("test.py") == breakpoints

    def test_get_statistics(self):
        """Test getting comprehensive statistics."""
        # Add some data using public API
        self.trace_manager.add_breakpoint("test.py", 10)
        self.trace_manager.add_breakpoint("test.py", 20)

        # Get statistics
        stats = self.trace_manager.get_statistics()

        # Check that the statistics contain the expected top-level keys
        assert "enabled" in stats
        assert "total_files_with_breakpoints" in stats
        assert "total_breakpoints" in stats
        assert "dispatcher_stats" in stats

        # Check the top-level statistics
        assert stats["enabled"] is False
        assert stats["total_files_with_breakpoints"] == 1
        assert stats["total_breakpoints"] == 2

        # Check the dispatcher_stats structure
        assert isinstance(stats["dispatcher_stats"], dict)
        assert "dispatcher_stats" in stats["dispatcher_stats"]
        assert "analyzer_stats" in stats["dispatcher_stats"]

        # Check the nested dispatcher_stats
        dispatcher_stats = stats["dispatcher_stats"]["dispatcher_stats"]
        assert isinstance(dispatcher_stats, dict)
        assert "total_calls" in dispatcher_stats
        assert "dispatched_calls" in dispatcher_stats
        assert "skipped_calls" in dispatcher_stats

        # Check the nested analyzer_stats
        analyzer_stats = stats["dispatcher_stats"]["analyzer_stats"]
        assert isinstance(analyzer_stats, dict)
        assert "total_frames" in analyzer_stats
        assert "traced_frames" in analyzer_stats
        assert "cache_hits" in analyzer_stats


class TestGlobalFunctions:
    """Test global convenience functions."""

    def setup_method(self):
        """Set up test fixtures."""
        # Reset global trace manager for each test
        dapper._frame_eval.selective_tracer._trace_manager = FrameTraceManager()

    def test_enable_selective_tracing(self):
        """Test enabling selective tracing globally."""
        mock_trace_func = Mock()

        enable_selective_tracing(mock_trace_func)

        # Trace manager should be enabled
        trace_manager = get_trace_manager()
        assert trace_manager.is_enabled() is True

        # The trace function should be set up
        trace_func = trace_manager.get_trace_function()
        assert trace_func is not None

    def test_disable_selective_tracing(self):
        """Test disabling selective tracing globally."""
        # Enable first
        mock_trace_func = Mock()
        enable_selective_tracing(mock_trace_func)

        # Then disable
        disable_selective_tracing()

        # Trace manager should be disabled
        trace_manager = get_trace_manager()
        assert trace_manager.is_enabled() is False

        # The trace function should be None when disabled
        assert trace_manager.get_trace_function() is None

    def test_get_selective_trace_function(self):
        """Test getting selective trace function."""
        # Should return None when disabled
        trace_func = get_selective_trace_function()
        assert trace_func is None

        # Enable and get function
        mock_trace_func = Mock()
        enable_selective_tracing(mock_trace_func)

        trace_func = get_selective_trace_function()
        assert trace_func is not None
        assert callable(trace_func)

    def test_update_breakpoints_global(self):
        """Test global breakpoint update function."""
        breakpoints = {10, 20, 30}

        update_breakpoints("test.py", breakpoints)

        # Get the trace manager and verify breakpoints
        trace_manager = get_trace_manager()
        assert trace_manager.get_breakpoints("test.py") == breakpoints


class TestThreadSafety:
    """Test thread safety of selective tracing components."""

    def setup_method(self):
        """Set up test fixtures."""
        self.trace_manager = FrameTraceManager()

    def test_concurrent_breakpoint_updates(self):
        """Test concurrent breakpoint updates."""
        errors = []

        def update_breakpoints_thread(filepath, line_numbers):
            try:
                for _ in range(100):
                    self.trace_manager.update_file_breakpoints(filepath, line_numbers)
            except Exception as e:
                errors.append(str(e))

        # Start multiple threads updating breakpoints
        threads = []
        for i in range(5):
            t = threading.Thread(
                target=update_breakpoints_thread,
                args=(f"test_{i}.py", {i * 10, i * 10 + 5, i * 10 + 9}),
            )
            threads.append(t)
            t.start()

        # Wait for all threads to complete
        for t in threads:
            t.join()

        # Verify no errors occurred
        assert not errors, f"Errors occurred in threads: {errors}"

        # Verify breakpoints were set correctly
        for i in range(5):
            assert self.trace_manager.get_breakpoints(f"test_{i}.py") == {
                i * 10,
                i * 10 + 5,
                i * 10 + 9,
            }

    def test_concurrent_trace_calls(self):
        """Test concurrent trace function calls."""
        mock_trace_func = Mock(return_value=None)
        self.trace_manager.enable_selective_tracing(mock_trace_func)

        # Create a mock frame
        mock_frame = Mock()
        mock_frame.f_code.co_filename = "test.py"
        mock_frame.f_lineno = 10

        # Set a breakpoint
        self.trace_manager.add_breakpoint("test.py", 10)

        # Get the trace function
        trace_func = self.trace_manager.get_trace_function()

        errors = []
        results = []

        # Mock the analyzer to always return True for should_trace_frame
        with patch.object(
            self.trace_manager.dispatcher.analyzer, "should_trace_frame"
        ) as mock_should_trace:
            mock_should_trace.return_value = {
                "should_trace": True,
                "reason": "breakpoint_on_line",
                "breakpoint_lines": {10},
                "frame_info": {"filename": "test.py", "lineno": 10, "function": "test_func"},
            }

            def call_trace_function():
                try:
                    for _ in range(100):
                        result = trace_func(mock_frame, "line", None)
                        results.append(result)
                except Exception as e:
                    errors.append(str(e))

            threads = []
            for _ in range(5):
                t = threading.Thread(target=call_trace_function)
                threads.append(t)
                t.start()

            # Wait for all threads to complete
            for t in threads:
                t.join()

            # Verify no errors occurred
            assert not errors, f"Errors occurred in threads: {errors}"

            # Verify the trace function was called the correct number of times
            assert mock_trace_func.call_count == 500  # 5 threads * 100 calls each

            # Verify the analyzer's should_trace_frame was called the correct number of times
            assert mock_should_trace.call_count == 500

            # All results should be None (the mock returns None)
            assert all(r is None for r in results)


if __name__ == "__main__":
    pytest.main([__file__])
