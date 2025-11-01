#!/usr/bin/env python3
"""

import sys
from pathlib import Path

# Add the project root to the Python path
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

Simple test to verify unittest discovery works."""

import unittest
import sys
import os

# Add the current directory to the path
sys.path.insert(0, ".")

class TestSimpleDiscovery(unittest.TestCase):
    """Test case to verify unittest discovery."""
    
    def test_imports(self):
        """Test that we can import our modules."""
        try:
            from dapper._frame_eval.cache_manager import get_cache_statistics
            from dapper._frame_eval.selective_tracer import get_trace_manager
            from dapper._frame_eval.debugger_integration import get_integration_bridge
            self.assertTrue(True)
        except ImportError as e:
            self.fail(f"Import failed: {e}")
    
    def test_basic_functionality(self):
        """Test basic functionality works."""
        from dapper._frame_eval.cache_manager import get_cache_statistics
        stats = get_cache_statistics()
        self.assertIsInstance(stats, dict)
        self.assertIn('func_code_cache', stats)

if __name__ == "__main__":
    unittest.main(verbosity=2)
