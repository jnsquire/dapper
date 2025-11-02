#!/usr/bin/env python3
"""
Pytest-style tests for frame evaluation system.
"""

import os
import sys

import pytest

# Disable import order warnings for this test file
pytestmark = pytest.mark.filterwarnings(
    "ignore:import should be at the top-level of a file:RuntimeWarning"
)


def test_imports():
    """Test that we can import our modules."""
    from dapper._frame_eval.cache_manager import get_cache_statistics
    from dapper._frame_eval.debugger_integration import get_integration_bridge
    from dapper._frame_eval.selective_tracer import get_trace_manager
    
    # Basic assertions that imports work
    assert get_cache_statistics is not None
    assert get_trace_manager is not None
    assert get_integration_bridge is not None


def test_basic_functionality():
    """Test basic functionality works."""
    from dapper._frame_eval.cache_manager import get_cache_statistics
    
    stats = get_cache_statistics()
    assert isinstance(stats, dict)
    assert "func_code_cache" in stats
    assert "breakpoint_cache" in stats
    assert "global_stats" in stats


def test_working_directory():
    """Test that working directory is correct."""
    cwd = os.getcwd()
    assert cwd.endswith("dapper")


def test_python_path():
    """Test that PYTHONPATH includes our workspace."""
    workspace_path = os.getcwd()
    assert workspace_path in sys.path


def test_cache_manager_basic():
    """Test basic cache manager functionality."""
    from dapper._frame_eval.cache_manager import get_func_code_info
    from dapper._frame_eval.cache_manager import remove_func_code_info
    from dapper._frame_eval.cache_manager import set_func_code_info
    
    # Create a test code object
    def test_function():
        return 42
    
    code_obj = test_function.__code__
    
    # Test setting and getting
    test_info = {"breakpoints": {1, 2, 3}, "modified": True}
    set_func_code_info(code_obj, test_info)
    
    retrieved_info = get_func_code_info(code_obj)
    assert retrieved_info is not None
    assert retrieved_info["breakpoints"] == {1, 2, 3}
    assert retrieved_info["modified"] is True
    
    # Test removal
    removed = remove_func_code_info(code_obj)
    assert removed is True
    
    # Verify it's gone
    after_removal = get_func_code_info(code_obj)
    assert after_removal is None


def test_thread_info():
    """Test thread info functionality."""
    from dapper._frame_eval.cache_manager import get_thread_info
    
    thread_info = get_thread_info()
    assert thread_info is not None
    assert hasattr(thread_info, "inside_frame_eval")
    assert hasattr(thread_info, "recursion_depth")
    assert hasattr(thread_info, "should_skip_frame")
    
    # Test recursion tracking
    initial_depth = thread_info.recursion_depth
    assert initial_depth >= 0
    
    thread_info.enter_frame_eval()
    assert thread_info.recursion_depth == initial_depth + 1
    assert thread_info.inside_frame_eval > 0  # It's a counter, not boolean
    
    thread_info.exit_frame_eval()
    assert thread_info.recursion_depth == initial_depth
    assert thread_info.inside_frame_eval == 0


def test_breakpoint_cache():
    """Test breakpoint cache functionality."""
    import os
    import tempfile

    from dapper._frame_eval.cache_manager import BreakpointCache
    
    # Create a temporary file for testing
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("# Test file\nx = 42\n")
        test_file = f.name
    
    try:
        # Test with a fresh cache instance to avoid conflicts
        cache = BreakpointCache(max_entries=10)
        
        test_breakpoints = {10, 20, 30}
        
        # Test setting breakpoints
        cache.set_breakpoints(test_file, test_breakpoints)
        
        # Test getting breakpoints
        retrieved = cache.get_breakpoints(test_file)
        assert retrieved is not None
        assert retrieved == test_breakpoints
        
        # Test cache miss
        miss = cache.get_breakpoints("nonexistent.py")
        assert miss is None
        
        # Test invalidation
        cache.invalidate_file(test_file)
        after_invalidation = cache.get_breakpoints(test_file)
        assert after_invalidation is None
        
    finally:
        # Clean up the temporary file
        if os.path.exists(test_file):
            os.unlink(test_file)


def test_selective_tracer():
    """Test selective tracer functionality."""
    from dapper._frame_eval.selective_tracer import FrameTraceAnalyzer
    from dapper._frame_eval.selective_tracer import get_trace_manager
    
    # Test trace manager
    manager = get_trace_manager()
    assert manager is not None
    assert hasattr(manager, "is_enabled")
    assert hasattr(manager, "get_trace_function")
    
    # Test frame analyzer
    analyzer = FrameTraceAnalyzer()
    assert analyzer is not None
    assert hasattr(analyzer, "should_trace_frame")
    
    # Test file tracking logic
    should_track_user = analyzer._should_track_file("user_code.py")
    assert should_track_user is True
    
    should_track_system = analyzer._should_track_file("<string>")
    assert should_track_system is False
    
    should_track_lib = analyzer._should_track_file("site-packages/package.py")
    assert should_track_lib is False


def test_debugger_integration():
    """Test debugger integration functionality."""

    from dapper._frame_eval.debugger_integration import auto_integrate_debugger
    from dapper._frame_eval.debugger_integration import get_integration_bridge
    
    # Test integration bridge
    bridge = get_integration_bridge()
    assert bridge is not None
    assert hasattr(bridge, "config")
    assert hasattr(bridge, "integration_stats")
    
    # Test configuration
    config = bridge.config
    assert isinstance(config, dict)
    assert "enabled" in config
    assert "selective_tracing" in config
    
    # Test auto-integration with mock objects
    class MockDebuggerBDB:
        def __init__(self):
            self.user_line = lambda frame: None
            self.breakpoints = {}
    
    class MockPyDebugger:
        def __init__(self):
            self.set_breakpoints = lambda source, bps, **kwargs: None
            self.threads = {}
    
    # Test auto-integration
    mock_bdb = MockDebuggerBDB()
    result_bdb = auto_integrate_debugger(mock_bdb)
    assert result_bdb is True
    
    mock_py = MockPyDebugger()
    result_py = auto_integrate_debugger(mock_py)
    assert result_py is True
    
    # Test with unknown object
    result_unknown = auto_integrate_debugger(object())
    assert result_unknown is False


def test_performance_monitoring():
    """Test performance monitoring functionality."""
    from dapper._frame_eval.debugger_integration import get_integration_bridge
    
    bridge = get_integration_bridge()
    
    # Test performance monitoring
    bridge.enable_performance_monitoring(True)
    assert bridge.config["performance_monitoring"] is True
    
    # Simulate some activity
    for i in range(10):
        bridge._monitor_trace_call()
    
    for i in range(5):
        bridge._monitor_frame_eval_call()
    
    # Get statistics
    stats = bridge.get_integration_statistics()
    assert "performance_data" in stats
    assert stats["performance_data"]["trace_function_calls"] == 10
    assert stats["performance_data"]["frame_eval_calls"] == 5
    
    # Test reset
    bridge.reset_statistics()
    reset_stats = bridge.get_integration_statistics()
    assert reset_stats["performance_data"]["trace_function_calls"] == 0
    assert reset_stats["performance_data"]["frame_eval_calls"] == 0


def test_configuration():
    """Test configuration management."""
    from dapper._frame_eval.debugger_integration import configure_integration
    
    # Test configuration updates
    configure_integration(
        selective_tracing=False,
        bytecode_optimization=False,
        performance_monitoring=True
    )
    
    from dapper._frame_eval.debugger_integration import get_integration_bridge
    bridge = get_integration_bridge()
    
    assert bridge.config["selective_tracing"] is False
    assert bridge.config["bytecode_optimization"] is False
    assert bridge.config["performance_monitoring"] is True
    
    # Test disabling
    configure_integration(enabled=False)
    assert bridge.config["enabled"] is False


@pytest.mark.parametrize("test_file,should_track", [
    ("user_code.py", True),
    ("test_module.py", True),
    ("<string>", False),
    ("site-packages/package.py", False),
    ("python3.11/lib.py", False),
    ("importlib/__init__.py", False),
    ("dapper/_frame_eval/cache.py", False),
])
def test_file_tracking_patterns(test_file, should_track):
    """Test file tracking patterns with parametrization."""
    from dapper._frame_eval.selective_tracer import FrameTraceAnalyzer
    
    analyzer = FrameTraceAnalyzer()
    result = analyzer._should_track_file(test_file)
    assert result == should_track


def test_cache_statistics():
    """Test cache statistics functionality."""
    from dapper._frame_eval.cache_manager import cleanup_caches
    from dapper._frame_eval.cache_manager import clear_all_caches
    from dapper._frame_eval.cache_manager import get_cache_statistics
    
    # Get initial statistics
    stats = get_cache_statistics()
    assert isinstance(stats, dict)
    
    # Test structure
    assert "func_code_cache" in stats
    assert "breakpoint_cache" in stats
    assert "global_stats" in stats
    
    func_cache_stats = stats["func_code_cache"]
    assert isinstance(func_cache_stats, dict)
    assert "hits" in func_cache_stats
    assert "misses" in func_cache_stats
    assert "hit_rate" in func_cache_stats
    
    # Test cleanup
    cleanup_results = cleanup_caches()
    assert isinstance(cleanup_results, dict)
    assert "func_code_expired" in cleanup_results
    assert "breakpoint_files" in cleanup_results
    
    # Test clear
    clear_all_caches()
    cleared_stats = get_cache_statistics()
    assert cleared_stats["global_stats"]["total_entries"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])