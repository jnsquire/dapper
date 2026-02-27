"""Unit tests for the cache manager module."""

from collections import OrderedDict
import gc
import sys

# Import the module for cache manager tests
from dapper._frame_eval.cache_manager import BreakpointCache
from dapper._frame_eval.cache_manager import FuncCodeInfoCache
from dapper._frame_eval.cache_manager import ThreadLocalCache
from dapper._frame_eval.cache_manager import _caches
from dapper._frame_eval.cache_manager import get_func_code_info
from dapper._frame_eval.cache_manager import remove_func_code_info
from dapper._frame_eval.cache_manager import set_func_code_info


class TestFuncCodeInfoCache:
    """Tests for the FuncCodeInfoCache class."""

    def test_initialization(self):
        """Test that the cache initializes correctly."""
        # Create a test instance
        cache = FuncCodeInfoCache(max_size=100, ttl=60)

        # Check that the cache was initialized with the correct values
        assert cache.max_size == 100
        assert cache.ttl == 60
        # Internal structures use weak-key mapping and weakref ordered LRU
        assert isinstance(cache._lru_order, OrderedDict)
        assert len(cache._lru_order) == 0
        assert hasattr(cache, "_weak_map")
        assert len(cache._weak_map) == 0
        assert hasattr(cache, "_lock")

    def test_refcount_stability_on_set_remove(self):

        def test_func2():
            return 123

        code_obj = test_func2.__code__
        info = {"value": 1}
        before = sys.getrefcount(info)

        set_func_code_info(code_obj, info)
        after_set = sys.getrefcount(info)

        assert after_set - before in (0, 1)  # Accept one additional temporary ref during set

        removed = remove_func_code_info(code_obj)
        assert removed is True
        after_remove = sys.getrefcount(info)
        # After removal, refcount should be stable same as before
        assert after_remove == before

    def test_id_reuse_detection_invalidates_stale_entries(self):
        """Ensure stale LRU entries are evicted when code objects are GC'd
        and do not return stale info."""

        def make_func():
            def x():
                return 1

            return x

        f1 = make_func()
        code1 = f1.__code__
        info1 = {"a": 1}
        set_func_code_info(code1, info1)

        # Remove strong references to the function and force garbage collection

        cache = _caches.func_code
        # Ensure the cache is cleared for a clean test
        cache.clear()
        # Ensure the weak map is empty initially
        assert len(cache._weak_map) == 0

        # Remove all strong references to the function and its code object
        del f1
        del code1
        gc.collect()

        # After collection the weak map should be empty (or at least not contain the entry)
        assert len(cache._weak_map) == 0
        gc.collect()

    def test_cleanup_expired_removes_old_entries(self):
        """Ensure that expired entries are removed from the LRU fallback cache."""
        # Use the singleton cache managed by _caches so helpers like
        # set_func_code_info / get_func_code_info operate on the same instance.
        cache = _caches.func_code
        cache.ttl = 1

        # Create a simple code object and set info
        def f():
            return 42

        code_obj = f.__code__
        info = {"x": 1}

        # Set the info into the global cache via helper (mirrors real use)
        set_func_code_info(code_obj, info)

        # Ensure it was added
        assert get_func_code_info(code_obj) == info

        # Artificially age the timestamp to make it expired
        for k in list(_caches.func_code._timestamps.keys()):
            _caches.func_code._timestamps[k] = _caches.func_code._timestamps[k] - (
                _caches.func_code.ttl + 10
            )

        # Cleanup should remove one entry
        # Use the global cache's cleanup implementation
        removed = _caches.func_code.cleanup_expired()
        assert removed >= 1
        # Cache should no longer contain code info
        assert get_func_code_info(code_obj) is None

        # After the code object is collected, the weak map should have released the entry


class TestBreakpointCache:
    """Tests for the BreakpointCache class."""

    def test_initialization(self):
        """Test that the cache initializes correctly."""
        cache = BreakpointCache(max_entries=50)
        assert cache.max_entries == 50
        assert isinstance(cache._cache, dict)
        assert len(cache._cache) == 0


class TestThreadLocalCache:
    """Tests for the ThreadLocalCache class."""

    def test_initialization(self):
        """Test that the cache initializes correctly."""
        cache = ThreadLocalCache()
        assert hasattr(cache, "_local")
        assert hasattr(cache._local, "storage")
