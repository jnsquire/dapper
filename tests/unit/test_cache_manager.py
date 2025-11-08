"""Unit tests for the cache manager module."""

from collections import OrderedDict
from unittest.mock import patch

import pytest

# Import the module with the _init_code_extra_index method patched
with patch("dapper._frame_eval.cache_manager.FuncCodeInfoCache._init_code_extra_index"):
    from dapper._frame_eval.cache_manager import BreakpointCache
    from dapper._frame_eval.cache_manager import FuncCodeInfoCache
    from dapper._frame_eval.cache_manager import ThreadLocalCache


class TestFuncCodeInfoCache:
    """Tests for the FuncCodeInfoCache class."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test fixtures."""
        # Patch the _init_code_extra_index method to do nothing
        self.patcher = patch.object(
            FuncCodeInfoCache, "_init_code_extra_index", return_value=None
        )
        self.mock_init = self.patcher.start()
        yield
        self.patcher.stop()

    def test_initialization(self):
        """Test that the cache initializes correctly."""
        # Create a test instance
        cache = FuncCodeInfoCache(max_size=100, ttl=60)
        
        # Check that _init_code_extra_index was called
        self.mock_init.assert_called_once()
        
        # Check that the cache was initialized with the correct values
        assert cache.max_size == 100
        assert cache.ttl == 60
        assert isinstance(cache._lru_cache, OrderedDict)
        assert len(cache._lru_cache) == 0
        assert isinstance(cache._timestamps, dict)
        assert len(cache._timestamps) == 0
        assert hasattr(cache, "_lock")


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
