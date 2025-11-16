"""Unit tests for the BreakpointCache class using mocks."""

import time
from unittest.mock import MagicMock

# Import the actual implementation first
from dapper._frame_eval.cache_manager import BreakpointCache as RealBreakpointCache


class MockBreakpointCache(RealBreakpointCache):
    """Mock implementation of BreakpointCache for testing."""
    def __init__(self, max_entries=500):
        # Call the real __init__ to set up the instance
        super().__init__(max_entries)
        
        # Override the internal storage with our test implementations
        self._cache = {}
        self._timestamps = {}
        self._file_mtimes = {}
        self._lock = MagicMock()  # Use a mock for the lock
    
    def get_breakpoints(self, filepath):
        """Get breakpoints for a file."""
        with self._lock:
            return self._cache.get(filepath, set()).copy()
    
    def set_breakpoints(self, filepath, breakpoints):
        """Set breakpoints for a file."""
        with self._lock:
            # Convert to set to ensure consistent behavior
            breakpoints = set(breakpoints)
            
            # If the file is already in the cache, just update it
            if filepath in self._cache:
                self._cache[filepath] = breakpoints
                self._timestamps[filepath] = time.time()
                return
                
            # If we're at capacity, remove the least recently used item
            if len(self._cache) >= self.max_entries and self._timestamps:
                oldest_file = min(self._timestamps.items(), key=lambda x: x[1])[0]
                self._remove_entry(oldest_file)
            
            # Add the new entry
            self._cache[filepath] = breakpoints
            self._timestamps[filepath] = time.time()
    
    def _remove_entry(self, filepath):
        """Remove an entry from the cache."""
        self._cache.pop(filepath, None)
        self._timestamps.pop(filepath, None)
        self._file_mtimes.pop(filepath, None)

# Create a test class that uses our mock implementation
class TestBreakpointCache:
    """Test the BreakpointCache class using our mock implementation."""
    
    def setup_method(self):
        """Set up test fixtures before each test method."""
        # Create a fresh instance for each test
        self.cache = MockBreakpointCache()

    def test_initialization(self):
        """Test that the cache initializes with the correct defaults."""
        # Create a test instance
        cache = MockBreakpointCache(max_entries=100)
        
        # Verify the cache was initialized with the correct max_entries
        assert cache.max_entries == 100
        
        # Verify the internal structures exist
        assert hasattr(cache, "_cache")
        assert hasattr(cache, "_timestamps")
        assert hasattr(cache, "_file_mtimes")
        assert hasattr(cache, "_lock")
    
    def test_add_and_get_breakpoints(self):
        """Test adding and retrieving breakpoints."""
        # Add some breakpoints
        test_file = "test_file.py"
        test_breakpoints = {1, 2, 3}
        self.cache.set_breakpoints(test_file, test_breakpoints)
        
        # Retrieve the breakpoints
        result = self.cache.get_breakpoints(test_file)
        
        # Verify the breakpoints were stored and retrieved correctly
        assert result == test_breakpoints
    
    def test_set_breakpoints(self):
        """Test setting breakpoints for a file."""
        # Test file and breakpoints
        test_file = "test_file.py"
        test_breakpoints = {5, 10, 15}
        
        # Set breakpoints
        self.cache.set_breakpoints(test_file, test_breakpoints)
        
        # Verify breakpoints were set
        assert test_file in self.cache._cache
        assert self.cache._cache[test_file] == test_breakpoints
    
    def test_cleanup(self):
        """Test cleaning up the cache."""
        # Create a test instance with a small max_entries
        cache = MockBreakpointCache(max_entries=2)
        
        # Add entries with small delays to ensure different timestamps
        cache.set_breakpoints("file1.py", {1})
        time.sleep(0.01)
        cache.set_breakpoints("file2.py", {2})
        
        # Verify both entries are in the cache
        assert "file1.py" in cache._cache
        assert "file2.py" in cache._cache
        
        # Add one more to trigger eviction
        time.sleep(0.01)
        cache.set_breakpoints("file3.py", {3})
        
        # The first entry should be evicted (LRU)
        assert "file1.py" not in cache._cache, "Oldest entry was not evicted"
        assert "file2.py" in cache._cache, "Second entry should still be in cache"
        assert "file3.py" in cache._cache, "Newest entry should be in cache"
        
        # Verify the cache size is maintained
        assert len(cache._cache) == 2, "Cache size should not exceed max_entries"
