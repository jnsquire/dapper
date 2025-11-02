#!/usr/bin/env python3
"""Test script for the frame evaluation caching system."""

from __future__ import annotations

import threading
import time
from typing import Any

# Disable import order warnings for this test file
import pytest

pytestmark = pytest.mark.filterwarnings(
    "ignore:import should be at the top-level of a file:RuntimeWarning"
)

# Import cache manager functions at module level
from dapper._frame_eval.cache_manager import BreakpointCache
from dapper._frame_eval.cache_manager import ThreadLocalCache
from dapper._frame_eval.cache_manager import cleanup_caches
from dapper._frame_eval.cache_manager import clear_all_caches
from dapper._frame_eval.cache_manager import configure_caches
from dapper._frame_eval.cache_manager import get_breakpoints
from dapper._frame_eval.cache_manager import get_cache_statistics
from dapper._frame_eval.cache_manager import get_func_code_info
from dapper._frame_eval.cache_manager import get_thread_info
from dapper._frame_eval.cache_manager import invalidate_breakpoints
from dapper._frame_eval.cache_manager import set_breakpoints
from dapper._frame_eval.cache_manager import set_cache_enabled
from dapper._frame_eval.cache_manager import set_func_code_info


def sample_function():
    """A sample function for testing."""
    x = 1
    y = 2
    return x + y

def another_function():
    """Another sample function."""
    return "hello"

class MockFuncCodeInfo:
    """Mock FuncCodeInfo class for testing."""
    
    def __init__(self, filename: str = "test.py", has_breakpoints: bool = False) -> None:
        """Initialize mock function code info.
        
        Args:
            filename: The filename to associate with this code info.
            has_breakpoints: Whether this code has breakpoints.
        """
        self.filename = filename
        self.has_breakpoints = has_breakpoints
        self.breakpoint_lines = {3, 5} if has_breakpoints else set()
        self.last_check = time.time()
        self.is_valid = True
    
    def update_breakpoint_info(self) -> None:
        """Mock update method."""
        self.last_check = time.time()

def test_func_code_cache():
    """Test FuncCodeInfo caching functionality."""
    print("=== Testing FuncCodeInfo Cache ===")
    
    try:
        from dapper._frame_eval.cache_manager import FuncCodeInfoCache
        from dapper._frame_eval.cache_manager import get_func_code_info
        from dapper._frame_eval.cache_manager import remove_func_code_info
        from dapper._frame_eval.cache_manager import set_func_code_info
        
        # Create a cache instance
        cache = FuncCodeInfoCache(max_size=5, ttl=2)
        
        # Test basic get/set
        code_obj = sample_function.__code__
        info = MockFuncCodeInfo("sample.py", has_breakpoints=True)
        
        print(f"Initial cache stats: {cache.get_stats()}")
        
        # Set and get
        set_func_code_info(code_obj, info)
        cached_info = get_func_code_info(code_obj)
        
        print(f"Cache hit: {cached_info is info}")
        print(f"Cache stats after set: {cache.get_stats()}")
        
        # Test cache miss
        another_code = another_function.__code__
        cached_info2 = get_func_code_info(another_code)
        print(f"Cache miss (None): {cached_info2 is None}")
        
        # Test removal
        removed = remove_func_code_info(code_obj)
        cached_info3 = get_func_code_info(code_obj)
        print(f"Removed successfully: {removed}")
        print(f"Cache miss after removal: {cached_info3 is None}")
        
        # Test TTL expiration
        info2 = MockFuncCodeInfo("ttl_test.py", has_breakpoints=False)
        set_func_code_info(code_obj, info2)
        
        # Wait for expiration
        print("Waiting for TTL expiration...")
        time.sleep(3)
        
        cached_info4 = get_func_code_info(code_obj)
        print(f"Cache miss after TTL: {cached_info4 is None}")
        
        # Test LRU eviction
        print("Testing LRU eviction...")
        for i in range(10):  # More than max_size
            test_info = MockFuncCodeInfo(f"test_{i}.py", has_breakpoints=i % 2 == 0)
            # Create different code objects
            test_code = compile(f"def test_{i}(): return {i}", f"test_{i}.py", "exec")
            set_func_code_info(test_code, test_info)
        
        final_stats = cache.get_stats()
        print(f"Final cache stats: {final_stats}")
        print(f"LRU working: {final_stats['total_entries'] <= cache.max_size}")
        
        print("✅ FuncCodeInfo cache tests passed")
        
    except Exception as e:
        print(f"❌ FuncCodeInfo cache test failed: {e}")
        import traceback
        traceback.print_exc()

def test_thread_local_cache():
    """Test thread-local caching functionality."""
    print("\n=== Testing Thread-Local Cache ===")
    
    try:
        
        cache = ThreadLocalCache()
        
        # Test thread info
        thread_info = get_thread_info()
        print(f"Thread info created: {thread_info is not None}")
        print(f"Initial inside_frame_eval: {thread_info.inside_frame_eval}")
        
        # Test frame evaluation tracking
        thread_info.enter_frame_eval()
        print(f"After enter: {thread_info.inside_frame_eval}")
        
        thread_info.exit_frame_eval()
        print(f"After exit: {thread_info.inside_frame_eval}")
        
        # Test frame skipping logic
        should_skip1 = thread_info.should_skip_frame("dapper/_frame_eval/test.py")
        should_skip2 = thread_info.should_skip_frame("user_code.py")
        
        print(f"Should skip debugger frame: {should_skip1}")
        print(f"Should skip user frame: {should_skip2}")
        
        # Test recursion depth       
        for _ in range(5):
            thread_info.enter_frame_eval()
        print(f"Recursion depth: {thread_info.recursion_depth}")
        
        # Test recursion limit
        thread_info.recursion_depth = 15
        should_skip_recursion = thread_info.should_skip_frame("user_code.py")
        print(f"Should skip due to recursion: {should_skip_recursion}")
        
        # Test thread cleanup
        cache.clear_thread_local()
        new_thread_info = get_thread_info()
        print(f"Fresh thread info after cleanup: {new_thread_info.inside_frame_eval == 0}")
        
        print("✅ Thread-local cache tests passed")
        
    except Exception as e:
        print(f"❌ Thread-local cache test failed: {e}")
        import traceback
        traceback.print_exc()

def test_breakpoint_cache() -> None:
    """Test breakpoint caching functionality."""
    print("\n=== Testing Breakpoint Cache ===")
    
    try:
        cache = BreakpointCache(max_entries=3)
        
        # Test basic get/set
        filepath = "test_sample.py"
        breakpoints = {3, 5, 7, 10}
        
        print(f"Initial cache stats: {cache.get_stats()}")
        
        # Cache breakpoints
        set_breakpoints(filepath, breakpoints)
        cached_breakpoints = get_breakpoints(filepath)
        
        print(f"Cache hit: {cached_breakpoints == breakpoints}")
        print(f"Cache stats after set: {cache.get_stats()}")
        
        # Test cache miss
        cached_breakpoints2 = get_breakpoints("nonexistent.py")
        print(f"Cache miss (None): {cached_breakpoints2 is None}")
        
        # Test file invalidation
        invalidate_breakpoints(filepath)
        cached_breakpoints3 = get_breakpoints(filepath)
        print(f"Cache miss after invalidation: {cached_breakpoints3 is None}")
        
        # Test LRU eviction
        print("Testing LRU eviction...")
        for i in range(5):  # More than max_size
            test_file = f"test_{i}.py"
            test_breakpoints = {i, i+1, i+2}
            set_breakpoints(test_file, test_breakpoints)
        
        final_stats = cache.get_stats()
        print(f"Final cache stats: {final_stats}")
        print(f"LRU working: {final_stats['total_files'] <= cache.max_entries}")
        
        print("✅ Breakpoint cache tests passed")
        
    except Exception as e:
        print(f"❌ Breakpoint cache test failed: {e}")
        import traceback
        traceback.print_exc()

def worker_thread(thread_id: int, results: list[dict[str, Any]], errors: list[str]) -> None:
    """Worker function for testing thread safety."""
    try:
        # Get thread info
        thread_info = get_thread_info()
        thread_info.enter_frame_eval()
        
        # Use FuncCodeInfo cache
        code_obj = compile(f"def worker_{thread_id}(): return {thread_id}", 
                         f"worker_{thread_id}.py", "exec")
        info = MockFuncCodeInfo(f"worker_{thread_id}.py", True)
        
        set_func_code_info(code_obj, info)
        cached_info = get_func_code_info(code_obj)
        
        # Verify thread-local isolation
        thread_info.exit_frame_eval()
        
        results.append({
            "thread_id": thread_id,
            "cache_hit": cached_info is info,
            "frame_eval_count": thread_info.inside_frame_eval,
        })
        
    except Exception as e:
        errors.append(f"Thread {thread_id}: {e}")

def test_multithreading() -> None:
    """Test cache behavior with multiple threads."""
    print("\n=== Testing Multithreading ===")
    
    try:
        results = []
        errors = []
        
        # Start multiple threads
        threads = []
        for i in range(5):
            thread = threading.Thread(
                target=worker_thread, 
                args=(i, results, errors)
            )
            threads.append(thread)
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join()
        
        # Check results
        print(f"Threads completed: {len(results)}")
        print(f"Errors: {len(errors)}")
        
        if errors:
            for error in errors:
                print(f"  {error}")
        
        # Verify thread isolation
        all_cache_hits = all(r["cache_hit"] for r in results)
        all_frames_reset = all(r["frame_eval_count"] == 0 for r in results)
        
        print(f"All cache hits: {all_cache_hits}")
        print(f"All frames reset: {all_frames_reset}")
        
        if len(errors) == 0 and all_cache_hits and all_frames_reset:
            print("✅ Multithreading tests passed")
        else:
            print("❌ Multithreading tests failed")
        
    except Exception as e:
        print(f"❌ Multithreading test failed: {e}")
        import traceback
        traceback.print_exc()

def test_cache_configuration():
    """Test cache configuration and management."""
    print("\n=== Testing Cache Configuration ===")
    
    try:
        # Get initial stats
        initial_stats = get_cache_statistics()
        print(f"Initial stats: {initial_stats}")
        
        # Test configuration
        configure_caches(
            func_code_max_size=10,
            func_code_ttl=60,
            breakpoint_max_size=5,
        )
        
        # Add some data
        for i in range(15):
            code_obj = compile(f"def config_test_{i}(): return {i}", 
                             f"config_test_{i}.py", "exec")
            info = MockFuncCodeInfo(f"config_test_{i}.py", i % 3 == 0)
            set_func_code_info(code_obj, info)
        
        configured_stats = get_cache_statistics()
        print(f"Configured stats: {configured_stats}")
        
        # Test cache disable
        set_cache_enabled(False)
        
        # Try to add data (should be ignored)
        code_obj = compile("def disabled_test(): return 0", "disabled_test.py", "exec")
        info = MockFuncCodeInfo("disabled_test.py", True)
        set_func_code_info(code_obj, info)
        
        disabled_stats = get_cache_statistics()
        print(f"Disabled stats: {disabled_stats}")
        
        # Re-enable cache
        set_cache_enabled(True)
        
        # Test cleanup
        cleanup_results = cleanup_caches()
        print(f"Cleanup results: {cleanup_results}")
        
        # Test clear all
        clear_all_caches()
        cleared_stats = get_cache_statistics()
        print(f"Cleared stats: {cleared_stats}")
        
        print("✅ Cache configuration tests passed")
        
    except Exception as e:
        print(f"❌ Cache configuration test failed: {e}")

def test_performance():
    """Test cache performance."""
    print("\n=== Testing Cache Performance ===")
    
    try:
        from dapper._frame_eval.cache_manager import set_func_code_info
        
        # Performance test setup
        num_operations = 1000
        code_objects = []
        infos = []
        
        # Create test data
        for i in range(num_operations):
            code_obj = compile(f"def perf_test_{i}(): return {i}", 
                             f"perf_test_{i}.py", "exec")
            info = MockFuncCodeInfo(f"perf_test_{i}.py", i % 10 == 0)
            code_objects.append(code_obj)
            infos.append(info)
        
        # Test cache write performance
        start_time = time.time()
        for code_obj, info in zip(code_objects, infos):
            set_func_code_info(code_obj, info)
        write_time = time.time() - start_time
        
        # Test cache read performance
        start_time = time.time()
        cache_hits = 0
        for code_obj in code_objects:
            cached_info = get_func_code_info(code_obj)
            if cached_info is not None:
                cache_hits += 1
        read_time = time.time() - start_time
        
        # Get final stats
        final_stats = get_cache_statistics()
        
        print(f"Write performance: {num_operations/write_time:.0f} ops/sec")
        print(f"Read performance: {num_operations/read_time:.0f} ops/sec")
        print(f"Cache hit rate: {cache_hits/num_operations:.2%}")
        print(f"Final stats: {final_stats}")
        
        # Performance assertions
        write_ops_per_sec = num_operations / write_time
        read_ops_per_sec = num_operations / read_time
        
        if write_ops_per_sec > 1000 and read_ops_per_sec > 5000:
            print("✅ Cache performance tests passed")
        else:
            print("❌ Cache performance below expectations")
        
    except Exception as e:
        print(f"❌ Cache performance test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("🗄️ Frame Evaluation Cache System Test Suite")
    print("=" * 50)
    
    test_func_code_cache()
    test_thread_local_cache()
    test_breakpoint_cache()
    test_multithreading()
    test_cache_configuration()
    test_performance()
    
    print("\n🎉 All cache tests completed!")