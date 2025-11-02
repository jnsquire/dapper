#!/usr/bin/env python3
"""Test to verify unittest discovery works with our configuration."""

import sys
import unittest
from pathlib import Path

# Import local modules with try/except to handle path issues
try:
    from dapper._frame_eval.cache_manager import get_cache_statistics
    from dapper._frame_eval.debugger_integration import get_integration_bridge
    from dapper._frame_eval.selective_tracer import get_trace_manager
except ImportError:
    # Add the project root to the Python path if imports fail
    project_root = str(Path(__file__).parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    from dapper._frame_eval.cache_manager import get_cache_statistics
    from dapper._frame_eval.debugger_integration import get_integration_bridge
    from dapper._frame_eval.selective_tracer import get_trace_manager

class TestDiscovery(unittest.TestCase):
    """Test case to verify unittest discovery."""
    
    def test_python_environment(self):
        """Test that Python environment is properly configured."""
        # Test that basic functionality works
        stats = get_cache_statistics()
        assert isinstance(stats, dict)
        
        manager = get_trace_manager()
        assert manager is not None
        
        bridge = get_integration_bridge()
        assert bridge is not None
    
    def test_working_directory(self):
        """Test that working directory is correct."""
        cwd = str(Path.cwd())
        assert cwd.endswith("dapper")
    
    def test_python_path(self):
        """Test that PYTHONPATH includes our workspace."""
        workspace_path = str(Path.cwd())
        assert workspace_path in sys.path

if __name__ == "__main__":
    unittest.main(verbosity=2)
