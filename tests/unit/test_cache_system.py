"""Test script for the frame evaluation caching system."""

from __future__ import annotations

import threading
import time
from typing import Any

from dapper._frame_eval.cache_manager import BreakpointCache
from dapper._frame_eval.cache_manager import FuncCodeInfoCache
from dapper._frame_eval.cache_manager import ThreadLocalCache
from dapper._frame_eval.cache_manager import _caches
from dapper._frame_eval.cache_manager import cleanup_caches
from dapper._frame_eval.cache_manager import clear_all_caches
from dapper._frame_eval.cache_manager import configure_caches
from dapper._frame_eval.cache_manager import get_breakpoints
from dapper._frame_eval.cache_manager import get_func_code_info
from dapper._frame_eval.cache_manager import get_thread_info
from dapper._frame_eval.cache_manager import invalidate_breakpoints
from dapper._frame_eval.cache_manager import remove_func_code_info
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
    # Create a cache instance with reduced TTL for faster testing
    cache = FuncCodeInfoCache(max_size=5, ttl=1)  # Use int for ttl
    _caches.func_code = cache

    # Test basic get/set
    code_obj = sample_function.__code__
    info = MockFuncCodeInfo("sample.py", has_breakpoints=True)

    # Set and get
    set_func_code_info(code_obj, info)
    get_func_code_info(code_obj)

    # Test cache miss
    another_code = another_function.__code__
    get_func_code_info(another_code)

    # Test removal
    remove_func_code_info(code_obj)
    get_func_code_info(code_obj)

    # Test TTL expiration by forcing LRU cache usage

    info2 = MockFuncCodeInfo("ttl_test.py", has_breakpoints=False)
    set_func_code_info(code_obj, info2)

    # Wait for expiration (sleep for 1.1s to exceed TTL of 1s)
    time.sleep(1.1)

    # Verify TTL expiration worked
    cached_info = get_func_code_info(code_obj)
    assert cached_info is None, "Cache entry should have expired"

    # Test LRU eviction
    for i in range(10):  # More than max_size
        test_info = MockFuncCodeInfo(f"test_{i}.py", has_breakpoints=i % 2 == 0)
        # Create different code objects
        test_code = compile(f"def test_{i}(): return {i}", f"test_{i}.py", "exec")
        set_func_code_info(test_code, test_info)

    cache.get_stats()


def test_thread_local_cache():
    """Test thread-local caching functionality."""
    cache = ThreadLocalCache()

    # Test thread info
    thread_info = get_thread_info()

    # Test frame evaluation tracking
    thread_info.enter_frame_eval()
    thread_info.exit_frame_eval()

    # Test frame skipping logic
    thread_info.should_skip_frame("dapper/_frame_eval/test.py")
    thread_info.should_skip_frame("user_code.py")

    # Test recursion depth
    for _ in range(5):
        thread_info.enter_frame_eval()

    # Test recursion limit
    thread_info.recursion_depth = 15
    thread_info.should_skip_frame("user_code.py")

    # Test thread cleanup
    cache.clear_thread_local()
    get_thread_info()


def test_breakpoint_cache() -> None:
    """Test breakpoint caching functionality."""
    cache = BreakpointCache(max_entries=3)

    # Test basic get/set
    filepath = "test_sample.py"
    breakpoints = {3, 5, 7, 10}

    # Cache breakpoints
    set_breakpoints(filepath, breakpoints)
    get_breakpoints(filepath)

    # Test cache miss
    get_breakpoints("nonexistent.py")

    # Test file invalidation
    invalidate_breakpoints(filepath)
    get_breakpoints(filepath)

    # Test LRU eviction
    for i in range(5):  # More than max_size
        test_file = f"test_{i}.py"
        test_breakpoints = {i, i + 1, i + 2}
        set_breakpoints(test_file, test_breakpoints)

    cache.get_stats()


def worker_thread(thread_id: int, results: list[dict[str, Any]]) -> None:
    """Worker function for testing thread safety."""
    # Get thread info
    thread_info = get_thread_info()
    thread_info.enter_frame_eval()

    # Use FuncCodeInfo cache
    code_obj = compile(
        f"def worker_{thread_id}(): return {thread_id}", f"worker_{thread_id}.py", "exec"
    )
    info = MockFuncCodeInfo(f"worker_{thread_id}.py", True)

    set_func_code_info(code_obj, info)
    cached_info = get_func_code_info(code_obj)

    # Verify thread-local isolation
    thread_info.exit_frame_eval()

    results.append(
        {
            "thread_id": thread_id,
            "cache_hit": cached_info is info,
            "frame_eval_count": thread_info.inside_frame_eval,
        }
    )


def test_multithreading() -> None:
    """Test cache behavior with multiple threads."""
    results = []

    # Start multiple threads
    threads = []
    for i in range(5):
        thread = threading.Thread(target=worker_thread, args=(i, results))
        threads.append(thread)
        thread.start()

    # Wait for completion
    for thread in threads:
        thread.join()

    # Verify thread isolation
    all_cache_hits = all(r["cache_hit"] for r in results)
    all_frames_reset = all(r["frame_eval_count"] == 0 for r in results)

    assert all_cache_hits, "Not all cache hits were successful"
    assert all_frames_reset, "Not all frame evaluations were properly reset"


def test_cache_configuration():
    """Test cache configuration and management."""
    # Test configuration
    configure_caches(
        func_code_max_size=10,
        func_code_ttl=60,
        breakpoint_max_size=5,
    )

    # Add some data
    for i in range(15):
        code_obj = compile(f"def config_test_{i}(): return {i}", f"config_test_{i}.py", "exec")
        info = MockFuncCodeInfo(f"config_test_{i}.py", i % 3 == 0)
        set_func_code_info(code_obj, info)

    # Test cache disable
    set_cache_enabled(False)

    # Try to add data (should be ignored)
    code_obj = compile("def disabled_test(): return 0", "disabled_test.py", "exec")
    info = MockFuncCodeInfo("disabled_test.py", True)
    set_func_code_info(code_obj, info)

    # Re-enable cache
    set_cache_enabled(True)

    # Test cleanup
    cleanup_caches()

    # Test clear all
    clear_all_caches()
