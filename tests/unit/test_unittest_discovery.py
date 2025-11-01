#!/usr/bin/env python3
"""

import sys
from pathlib import Path

# Add the project root to the Python path
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

Test to verify unittest discovery works with our configuration."""

import unittest
import sys
import os

# Add the current directory to the path
sys.path.insert(0, ".")

class TestDiscovery(unittest.TestCase):
    """Test case to verify unittest discovery."""
    
    def test_python_environment(self):
        """Test that Python environment is properly configured."""
        # Test that we can import our modules
        from dapper._frame_eval.cache_manager import get_cache_statistics
        from dapper._frame_eval.selective_tracer import get_trace_manager
        from dapper._frame_eval.debugger_integration import get_integration_bridge
        
        # Test that basic functionality works
        stats = get_cache_statistics()
        self.assertIsInstance(stats, dict)
        
        manager = get_trace_manager()
        self.assertIsNotNone(manager)
        
        bridge = get_integration_bridge()
        self.assertIsNotNone(bridge)
    
    def test_working_directory(self):
        """Test that working directory is correct."""
        cwd = os.getcwd()
        self.assertTrue(cwd.endswith("dapper"))
    
    def test_python_path(self):
        """Test that PYTHONPATH includes our workspace."""
        workspace_path = os.getcwd()
        self.assertIn(workspace_path, sys.path)

if __name__ == "__main__":
    unittest.main(verbosity=2)
