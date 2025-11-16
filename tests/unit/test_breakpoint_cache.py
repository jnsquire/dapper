"""Unit tests for the BreakpointCache class."""

import tempfile
import time
from collections import OrderedDict
from pathlib import Path

# Import the module without any mocks first to avoid import-time side effects
from dapper._frame_eval.cache_manager import BreakpointCache


class TestBreakpointCache:
    """Tests for the BreakpointCache class."""

    def setup_method(self):
        """Set up test fixtures before each test method."""
        # Create a temporary file for testing
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_file = Path(self.temp_dir.name) / "test_file.py"
        # Create the file with some content
        with self.test_file.open("w", encoding="utf-8") as f:
            f.write("# Test file\n" * 20)  # Create a file with 20 lines

        self.test_breakpoints = {1, 5, 10}
        self.cache = BreakpointCache(max_entries=10)

    def teardown_method(self):
        """Clean up after each test method."""
        self.temp_dir.cleanup()

    def test_initialization(self):
        """Test that the cache initializes correctly."""
        assert self.cache.max_entries == 10
        assert isinstance(self.cache._cache, OrderedDict)
        assert len(self.cache._cache) == 0
        assert hasattr(self.cache, "_lock")
        assert hasattr(self.cache, "_access_order")
        assert hasattr(self.cache, "_file_mtimes")

    def test_add_and_get_breakpoints(self):
        """Test adding and getting breakpoints."""
        # Add breakpoints
        self.cache.set_breakpoints(self.test_file, self.test_breakpoints)

        # Verify they can be retrieved
        result = self.cache.get_breakpoints(self.test_file)
        assert result == self.test_breakpoints

    def test_cleanup(self):
        """Test cleaning up the cache."""
        # Create a new cache with max_entries=2
        cache = BreakpointCache(max_entries=2)

        # Create temporary files for testing
        with (
            tempfile.NamedTemporaryFile(suffix=".py", dir=self.temp_dir.name, delete=False) as f1,
            tempfile.NamedTemporaryFile(suffix=".py", dir=self.temp_dir.name, delete=False) as f2,
            tempfile.NamedTemporaryFile(suffix=".py", dir=self.temp_dir.name, delete=False) as f3,
        ):
            file1 = f1.name
            file2 = f2.name
            file3 = f3.name

        # Add more items than the cache can hold
        cache.set_breakpoints(file1, {1})
        time.sleep(0.01)  # Ensure timestamps are different
        cache.set_breakpoints(file2, {2})
        time.sleep(0.01)
        cache.set_breakpoints(file3, {3})

        # The oldest item should be evicted
        assert len(cache._cache) == 2
        assert file1 not in cache._cache  # Oldest item should be removed
        assert file2 in cache._cache
        assert file3 in cache._cache
