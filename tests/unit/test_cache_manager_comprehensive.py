"""Comprehensive unit tests for the cache manager module."""

# Standard library imports
import threading

# Third-party imports
# Local application imports
from dapper._frame_eval.cache_manager import BreakpointCache
from dapper._frame_eval.cache_manager import FuncCodeInfoCache
from dapper._frame_eval.cache_manager import ThreadLocalCache


class TestFuncCodeInfoCache:
    """Tests for the FuncCodeInfoCache class."""

    def test_initialization(self):
        """Test that the cache initializes correctly."""
        cache = FuncCodeInfoCache(max_size=100, ttl=60)

        # Verify the cache was created with correct parameters
        assert cache.max_size == 100
        assert cache.ttl == 60

        # Verify the cache has the expected attributes (weak-key LRU)
        assert hasattr(cache, "_lru_order")
        assert hasattr(cache, "_weak_map")
        assert hasattr(cache, "_lock")

    def test_get_set_item(self):
        """Test setting and getting items from the cache."""
        cache = FuncCodeInfoCache(max_size=10, ttl=60)
        code_obj = compile("pass", "<string>", "exec")
        test_data = {"key": "value"}

        # Test setting and getting an item
        cache.set(code_obj, test_data)
        result = cache.get(code_obj)
        assert result == test_data

        # Test getting a non-existent item
        non_existent = compile("x = 1", "<string>", "exec")
        assert cache.get(non_existent) is None

    def test_eviction_policy(self):
        """Test that the cache evicts the least recently used items."""
        cache = FuncCodeInfoCache(max_size=2, ttl=60)

        # Add items to the cache
        code1 = compile("pass", "<string1>", "exec")
        code2 = compile("x = 1", "<string2>", "exec")
        code3 = compile("y = 2", "<string3>", "exec")

        cache.set(code1, {"data": 1})
        cache.set(code2, {"data": 2})

        # Access code1 to make it more recently used
        cache.get(code1)

        # Add a third item - code2 should be evicted as it's the least recently used
        cache.set(code3, {"data": 3})

        # Verify code2 was evicted
        assert cache.get(code1) is not None
        assert cache.get(code2) is None
        assert cache.get(code3) is not None


class TestBreakpointCache:
    """Tests for the BreakpointCache class."""

    def test_initialization(self):
        """Test that the cache initializes correctly."""
        cache = BreakpointCache(max_entries=50)
        assert cache.max_entries == 50
        assert isinstance(cache._cache, dict)
        assert len(cache._cache) == 0

    def test_add_and_get_breakpoints(self):
        """Test adding and getting breakpoints."""
        cache = BreakpointCache(max_entries=10)
        test_file = "test_file.py"
        test_breakpoints = {1, 5, 10}

        # Add breakpoints
        cache.set_breakpoints(test_file, test_breakpoints)

        # Verify they can be retrieved
        result = cache.get_breakpoints(test_file)
        assert result == test_breakpoints

        # Test getting non-existent file
        assert cache.get_breakpoints("non_existent.py") is None

    def test_eviction_policy(self):
        """Test that the cache evicts the least recently used items."""
        cache = BreakpointCache(max_entries=2)

        # Add first file
        cache.set_breakpoints("file1.py", {1, 2})
        print(
            "After adding file1.py:",
            cache._cache.keys(),
            "Access order:",
            getattr(cache, "_access_order", []),
        )

        # Add second file
        cache.set_breakpoints("file2.py", {3, 4})
        print(
            "After adding file2.py:",
            cache._cache.keys(),
            "Access order:",
            getattr(cache, "_access_order", []),
        )

        # Access file1 to make it more recently used
        result = cache.get_breakpoints("file1.py")
        print(
            "After accessing file1.py:",
            cache._cache.keys(),
            "Result:",
            result,
            "Access order:",
            getattr(cache, "_access_order", []),
        )

        # Add a third file - file2 should be evicted as it's the least recently used
        cache.set_breakpoints("file3.py", {5, 6})
        print(
            "After adding file3.py:",
            cache._cache.keys(),
            "Access order:",
            getattr(cache, "_access_order", []),
        )

        # Verify file1 is still in cache
        file1_result = cache.get_breakpoints("file1.py")
        print(
            "After final access to file1.py:",
            cache._cache.keys(),
            "Result:",
            file1_result,
            "Access order:",
            getattr(cache, "_access_order", []),
        )

        # Verify file2 was evicted
        file2_result = cache.get_breakpoints("file2.py")
        print(
            "After checking file2.py:",
            cache._cache.keys(),
            "Result:",
            file2_result,
            "Access order:",
            getattr(cache, "_access_order", []),
        )

        # Verify file3 is in cache
        file3_result = cache.get_breakpoints("file3.py")
        print(
            "After checking file3.py:",
            cache._cache.keys(),
            "Result:",
            file3_result,
            "Access order:",
            getattr(cache, "_access_order", []),
        )

        # Final assertions
        assert file1_result == {1, 2}, f"Expected file1.py to be in cache, but got {file1_result}"
        assert file2_result is None, f"Expected file2.py to be evicted, but got {file2_result}"
        assert file3_result == {5, 6}, f"Expected file3.py to be in cache, but got {file3_result}"

    def test_cleanup(self):
        """Test cleaning up the cache."""
        cache = BreakpointCache(max_entries=2)

        # Add more items than the cache can hold
        cache.set_breakpoints("file1.py", {1})
        cache.set_breakpoints("file2.py", {2})
        cache.set_breakpoints("file3.py", {3})

        # The oldest item should be evicted
        assert len(cache._cache) == 2


class TestThreadLocalCache:
    """Tests for the ThreadLocalCache class."""

    def test_initialization(self):
        """Test that the cache initializes correctly."""
        cache = ThreadLocalCache()
        assert hasattr(cache, "_local")
        assert hasattr(cache._local, "storage")

    def test_thread_safety(self):
        """Test that the cache is thread-local."""
        cache = ThreadLocalCache()

        # Test that the storage is thread-local
        cache._local.storage = {}
        assert hasattr(cache._local, "storage")

        # Test that each thread gets its own storage
        result = []

        def thread_func():
            if not hasattr(cache._local, "storage"):
                cache._local.storage = {}
            cache._local.storage["key"] = "thread_value"
            result.append(cache._local.storage.get("key"))

        # Set a different value in the main thread
        cache._local.storage["key"] = "main_value"

        # Start the thread
        thread = threading.Thread(target=thread_func)
        thread.start()
        thread.join()

        # Verify thread-local storage
        assert result[0] == "thread_value"
        assert cache._local.storage["key"] == "main_value"
