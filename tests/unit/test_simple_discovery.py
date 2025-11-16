#!/usr/bin/env python3
"""Simple test to verify unittest discovery works."""

import unittest

from dapper._frame_eval.cache_manager import get_cache_statistics
from dapper._frame_eval.debugger_integration import get_integration_bridge
from dapper._frame_eval.selective_tracer import get_trace_manager


class TestSimpleDiscovery(unittest.TestCase):
    """Test case to verify unittest discovery."""

    def test_imports(self):
        """Test that we can import our modules."""
        assert get_cache_statistics is not None
        assert get_integration_bridge is not None
        assert get_trace_manager is not None

    def test_basic_functionality(self):
        """Test basic functionality works."""
        stats = get_cache_statistics()
        assert isinstance(stats, dict)
        assert "func_code_cache" in stats


if __name__ == "__main__":
    unittest.main(verbosity=2)
