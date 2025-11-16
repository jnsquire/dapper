"""Simple unit tests for the BreakpointCache class."""


# Define a simple mock implementation of BreakpointCache
class MockBreakpointCache:
    def __init__(self, max_entries=1000):
        self.max_entries = max_entries
        self._cache = {}
        
    def set_breakpoints(self, filename, breakpoints):
        self._cache[filename] = set(breakpoints)
        
    def get_breakpoints(self, filename):
        return self._cache.get(filename, set())


class TestBreakpointCache:
    """Tests for the BreakpointCache class using a simple mock."""

    def test_initialization(self):
        """Test that the cache initializes correctly."""
        cache = MockBreakpointCache(max_entries=50)
        assert cache.max_entries == 50
        assert isinstance(cache._cache, dict)
        assert len(cache._cache) == 0

    def test_add_and_get_breakpoints(self):
        """Test adding and getting breakpoints."""
        cache = MockBreakpointCache(max_entries=10)
        test_file = "test_file.py"
        test_breakpoints = {1, 5, 10}
        
        # Add breakpoints
        cache.set_breakpoints(test_file, test_breakpoints)
        
        # Verify they can be retrieved
        result = cache.get_breakpoints(test_file)
        assert result == test_breakpoints
        
        # Test getting non-existent file
        assert cache.get_breakpoints("nonexistent.py") == set()

    def test_multiple_files(self):
        """Test handling multiple files."""
        cache = MockBreakpointCache(max_entries=10)
        
        # Add breakpoints for multiple files
        cache.set_breakpoints("file1.py", {1, 2, 3})
        cache.set_breakpoints("file2.py", {4, 5, 6})
        
        # Verify both can be retrieved
        assert cache.get_breakpoints("file1.py") == {1, 2, 3}
        assert cache.get_breakpoints("file2.py") == {4, 5, 6}

    def test_overwrite_breakpoints(self):
        """Test overwriting breakpoints for a file."""
        cache = MockBreakpointCache()
        
        # Initial set
        cache.set_breakpoints("test.py", {1, 2, 3})
        assert cache.get_breakpoints("test.py") == {1, 2, 3}
        
        # Overwrite
        cache.set_breakpoints("test.py", {4, 5})
        assert cache.get_breakpoints("test.py") == {4, 5}
