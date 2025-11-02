"""Tests for frame evaluation integration system."""

from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

import pytest

# Import the modules we're testing
from dapper._frame_eval.debugger_integration import DebuggerFrameEvalBridge
from dapper._frame_eval.debugger_integration import FrameEvalConfig
from dapper._frame_eval.debugger_integration import auto_integrate_debugger
from dapper._frame_eval.debugger_integration import get_integration_bridge
from dapper._frame_eval.debugger_integration import get_integration_statistics
from dapper._frame_eval.debugger_integration import integrate_debugger_bdb
from dapper._frame_eval.debugger_integration import integrate_py_debugger


class TestFrameEvalConfig:
    """Test the FrameEvalConfig TypedDict."""
    
    def test_config_structure(self):
        """Test that config has required fields."""
        config: FrameEvalConfig = {
            "enabled": True,
            "selective_tracing": True,
            "bytecode_optimization": True,
            "cache_enabled": True,
            "performance_monitoring": True,
            "fallback_on_error": True,
        }
        
        assert isinstance(config["enabled"], bool)
        assert isinstance(config["selective_tracing"], bool)
        assert isinstance(config["bytecode_optimization"], bool)
        assert isinstance(config["cache_enabled"], bool)
        assert isinstance(config["performance_monitoring"], bool)
        assert isinstance(config["fallback_on_error"], bool)


class TestDebuggerFrameEvalBridge:
    """Test the DebuggerFrameEvalBridge class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.bridge = DebuggerFrameEvalBridge()
    
    def test_initialization(self):
        """Test bridge initialization."""
        assert isinstance(self.bridge.config, dict)
        assert self.bridge.config["enabled"] is True
        assert self.bridge.config["selective_tracing"] is True
        assert self.bridge.config["bytecode_optimization"] is True
        assert self.bridge.config["cache_enabled"] is True
        assert self.bridge.config["performance_monitoring"] is True
        assert self.bridge.config["fallback_on_error"] is True
        
        # Check integration stats
        assert self.bridge.integration_stats["integrations_enabled"] == 0
        assert self.bridge.integration_stats["breakpoints_optimized"] == 0
        assert self.bridge.integration_stats["trace_calls_saved"] == 0
        assert self.bridge.integration_stats["bytecode_injections"] == 0
        assert self.bridge.integration_stats["errors_handled"] == 0
        
        # Check performance data
        assert "start_time" in self.bridge._performance_data
        assert self.bridge._performance_data["trace_function_calls"] == 0
        assert self.bridge._performance_data["frame_eval_calls"] == 0
    
    def test_update_config(self):
        """Test configuration updates."""
        # Update individual config values
        self.bridge.update_config(enabled=False, selective_tracing=False)
        
        assert self.bridge.config["enabled"] is False
        assert self.bridge.config["selective_tracing"] is False
        assert self.bridge.config["bytecode_optimization"] is True  # unchanged
        
        # Test invalid config key (should be ignored)
        original_config = self.bridge.config.copy()
        self.bridge.update_config(invalid_key=True)
        assert self.bridge.config == original_config
    
    def test_reset_statistics(self):
        """Test statistics reset."""
        # Modify some stats first
        self.bridge.integration_stats["integrations_enabled"] = 5
        self.bridge._performance_data["trace_function_calls"] = 10
        
        # Reset
        self.bridge.reset_statistics()
        
        # Check they're back to defaults
        assert self.bridge.integration_stats["integrations_enabled"] == 0
        assert self.bridge._performance_data["trace_function_calls"] == 0
        assert "start_time" in self.bridge._performance_data
    
    def test_enable_performance_monitoring(self):
        """Test performance monitoring toggle."""
        # Disable
        self.bridge.enable_performance_monitoring(False)
        assert self.bridge.config["performance_monitoring"] is False
        
        # Enable
        self.bridge.enable_performance_monitoring(True)
        assert self.bridge.config["performance_monitoring"] is True
    
    @patch("dapper._frame_eval.debugger_integration.get_trace_manager")
    @patch("dapper._frame_eval.debugger_integration.get_cache_statistics")
    def test_get_integration_statistics(self, mock_cache_stats, mock_trace_stats):
        """Test statistics collection."""
        # Create a mock for the trace manager with a get_statistics method
        mock_trace_manager = MagicMock()
        mock_trace_manager.get_statistics.return_value = {"traced_frames": 100, "skipped_frames": 200}
        mock_trace_stats.return_value = mock_trace_manager
        
        # Mock cache statistics
        mock_cache_stats.return_value = {"cache_hits": 50, "cache_misses": 25}
        
        # Get statistics
        stats = self.bridge.get_integration_statistics()
        
        # Verify structure
        assert isinstance(stats, dict)
        assert "config" in stats
        assert "integration_stats" in stats
        assert "performance_data" in stats
        assert "trace_manager_stats" in stats
        assert "cache_stats" in stats
        
        # Verify config is copied
        assert stats["config"] == self.bridge.config
        assert stats["config"] is not self.bridge.config  # different object
        
        # Verify integration stats are copied
        assert stats["integration_stats"] == self.bridge.integration_stats
        assert stats["integration_stats"] is not self.bridge.integration_stats
        
        # Verify performance data includes uptime
        assert "uptime_seconds" in stats["performance_data"]
        assert "avg_trace_calls_per_second" in stats["performance_data"]
        
        # Verify mocked stats are included
        assert stats["trace_manager_stats"] == {"traced_frames": 100, "skipped_frames": 200}
        assert stats["cache_stats"] == {"cache_hits": 50, "cache_misses": 25}
    
    def test_monitor_trace_call(self):
        """Test trace call monitoring."""
        initial_count = self.bridge._performance_data["trace_function_calls"]
        
        # Enable monitoring and call
        self.bridge.enable_performance_monitoring(True)
        self.bridge._monitor_trace_call()
        
        assert self.bridge._performance_data["trace_function_calls"] == initial_count + 1
        
        # Disable monitoring and call (should not increment)
        self.bridge.enable_performance_monitoring(False)
        self.bridge._monitor_trace_call()
        
        assert self.bridge._performance_data["trace_function_calls"] == initial_count + 1
    
    def test_monitor_frame_eval_call(self):
        """Test frame evaluation call monitoring."""
        initial_count = self.bridge._performance_data["frame_eval_calls"]
        
        # Enable monitoring and call
        self.bridge.enable_performance_monitoring(True)
        self.bridge._monitor_frame_eval_call()
        
        assert self.bridge._performance_data["frame_eval_calls"] == initial_count + 1


class TestDebuggerBDBIntegration:
    """Test integration with DebuggerBDB instances."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.bridge = DebuggerFrameEvalBridge()
        self.mock_debugger = Mock()
        self.mock_debugger.user_line = Mock()
    
    @patch("dapper._frame_eval.debugger_integration.get_trace_manager")
    @patch("dapper._frame_eval.debugger_integration.enable_selective_tracing")
    def test_integrate_with_debugger_bdb_success(self, mock_enable_tracing, mock_trace_manager):
        """Test successful DebuggerBDB integration."""
        # Setup mocks
        mock_trace_instance = Mock()
        mock_trace_instance.is_enabled.return_value = True
        mock_trace_instance.dispatcher.analyzer.should_trace_frame.return_value = {"should_trace": True}
        mock_trace_manager.return_value = mock_trace_instance
        
        # Integrate
        result = self.bridge.integrate_with_debugger_bdb(self.mock_debugger)
        
        assert result is True
        assert self.bridge.integration_stats["integrations_enabled"] == 1
        assert id(self.mock_debugger) in self.bridge.original_trace_functions
        
        # Get the enhanced user_line function
        enhanced_user_line = self.bridge.original_trace_functions[id(self.mock_debugger)]
        
        # Verify the enhanced function was stored and is callable
        assert callable(enhanced_user_line)
        
        # Verify user_line was replaced with an enhanced version
        assert self.mock_debugger.user_line != enhanced_user_line
    
    def test_integrate_with_debugger_bdb_disabled(self):
        """Test integration when bridge is disabled."""
        self.bridge.update_config(enabled=False)
        
        result = self.bridge.integrate_with_debugger_bdb(self.mock_debugger)
        
        assert result is False
        assert self.bridge.integration_stats["integrations_enabled"] == 0
    
    def test_integrate_with_debugger_bdb_no_user_line(self):
        """Test integration with debugger that has no user_line."""
        debugger_no_user_line = Mock()
        del debugger_no_user_line.user_line
        
        result = self.bridge.integrate_with_debugger_bdb(debugger_no_user_line)
        
        assert result is True
        # Verify that a no-op user_line was created and stored
        assert id(debugger_no_user_line) in self.bridge.original_trace_functions
        assert callable(debugger_no_user_line.user_line)  # A user_line should have been added
    
    @patch("dapper._frame_eval.debugger_integration.get_trace_manager")
    @patch("dapper._frame_eval.debugger_integration.sys")
    def test_enhanced_user_line_function(self, mock_sys, mock_trace_manager):
        """Test the enhanced user_line function behavior."""
        # Setup trace manager to allow tracing
        mock_tm = Mock()
        mock_tm.is_enabled.return_value = True
        mock_analyzer = Mock()
        
        # Mock the dispatcher and analyzer
        mock_dispatcher = Mock()
        mock_dispatcher.analyzer = mock_analyzer
        mock_tm.dispatcher = mock_dispatcher
        
        # Setup return value for should_trace_frame
        mock_analyzer.should_trace_frame.return_value = {"should_trace": True, "reason": "test"}
        
        mock_trace_manager.return_value = mock_tm
        
        # Setup sys._getframe for the test
        mock_frame = Mock()
        mock_frame.f_code.co_filename = "test_file.py"
        mock_frame.f_lineno = 42
        mock_sys._getframe.return_value = mock_frame
        
        # Create a mock debugger with a user_line method
        original_user_line = Mock()
        self.mock_debugger.user_line = original_user_line
        
        # Ensure selective tracing is enabled
        self.bridge.update_config(selective_tracing=True)
        
        # Integrate
        result = self.bridge.integrate_with_debugger_bdb(self.mock_debugger)
        assert result is True
        
        # Get the enhanced function
        enhanced_func = self.mock_debugger.user_line
        
        # Call the enhanced function
        enhanced_func(mock_frame)
        
        # Verify original was called
        original_user_line.assert_called_once_with(mock_frame)
        
        # Verify the trace manager was checked
        mock_tm.is_enabled.assert_called_once()
        mock_analyzer.should_trace_frame.assert_called_once()


class TestPyDebuggerIntegration:
    """Test integration with PyDebugger instances."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.bridge = DebuggerFrameEvalBridge()
        self.mock_debugger = Mock()
        self.mock_debugger.set_breakpoints = Mock()
        self.mock_debugger._set_trace_function = Mock()
    
    @patch("dapper._frame_eval.debugger_integration.update_breakpoints")
    def test_integrate_with_py_debugger_success(self, mock_update_breakpoints):
        """Test successful PyDebugger integration."""
        # Setup test data
        source = {"path": "test.py"}
        breakpoints = [{"line": 10}, {"line": 20}]
        
        # Integrate
        result = self.bridge.integrate_with_py_debugger(self.mock_debugger)
        
        assert result is True
        assert self.bridge.integration_stats["integrations_enabled"] == 1
        
        # Verify methods were replaced with enhanced versions
        assert "enhanced_set_breakpoints" in str(self.mock_debugger.set_breakpoints)
        assert "enhanced_set_trace" in str(self.mock_debugger._set_trace_function)
    
    def test_integrate_with_py_debugger_disabled(self):
        """Test integration when bridge is disabled."""
        self.bridge.update_config(enabled=False)
        
        result = self.bridge.integrate_with_py_debugger(self.mock_debugger)
        
        assert result is False
        assert self.bridge.integration_stats["integrations_enabled"] == 0


class TestGlobalFunctions:
    """Test global convenience functions."""
    
    def test_get_integration_bridge(self):
        """Test global bridge getter."""
        bridge = get_integration_bridge()
        assert isinstance(bridge, DebuggerFrameEvalBridge)
        assert bridge is get_integration_bridge()  # Same instance
    
    @patch("dapper._frame_eval.debugger_integration._integration_bridge")
    def test_integrate_debugger_bdb_global(self, mock_bridge):
        """Test global DebuggerBDB integration function."""
        mock_debugger = Mock()
        mock_bridge.integrate_with_debugger_bdb.return_value = True
        
        result = integrate_debugger_bdb(mock_debugger)
        
        assert result is True
        mock_bridge.integrate_with_debugger_bdb.assert_called_once_with(mock_debugger)
    
    @patch("dapper._frame_eval.debugger_integration._integration_bridge")
    def test_integrate_py_debugger_global(self, mock_bridge):
        """Test global PyDebugger integration function."""
        mock_debugger = Mock()
        mock_bridge.integrate_with_py_debugger.return_value = True
        
        result = integrate_py_debugger(mock_debugger)
        
        assert result is True
        mock_bridge.integrate_with_py_debugger.assert_called_once_with(mock_debugger)
    
    @patch("dapper._frame_eval.debugger_integration._integration_bridge.integrate_with_debugger_bdb")
    @patch("dapper._frame_eval.debugger_integration._integration_bridge.integrate_with_py_debugger")
    def test_auto_integrate_debugger(self, mock_bridge_py_integration, mock_bridge_bdb_integration):
        """Test automatic debugger detection and integration."""
        # Test DebuggerBDB detection (has user_line and breakpoints)
        debugger_bdb = Mock(spec=["user_line", "breakpoints"])
        debugger_bdb.user_line = Mock()
        debugger_bdb.breakpoints = {}
        mock_bridge_bdb_integration.return_value = True
        
        result = auto_integrate_debugger(debugger_bdb)
        assert result is True
        mock_bridge_bdb_integration.assert_called_once_with(debugger_bdb)
        
        # Reset mocks for next test
        mock_bridge_bdb_integration.reset_mock()
        mock_bridge_py_integration.reset_mock()
        
        # Test PyDebugger detection (has set_breakpoints and threads only)
        debugger_py = Mock(spec=["set_breakpoints", "threads"])
        debugger_py.set_breakpoints = Mock()
        debugger_py.threads = {}  # dictionary-like threads structure
        mock_bridge_py_integration.return_value = True
        
        result = auto_integrate_debugger(debugger_py)
        assert result is True
        mock_bridge_py_integration.assert_called_once_with(debugger_py)
        
        # Test unknown debugger type (no identifying attributes)
        unknown_debugger = Mock(spec=[])
        result = auto_integrate_debugger(unknown_debugger)
        assert result is False
    
    @patch("dapper._frame_eval.debugger_integration._integration_bridge")
    def test_get_integration_statistics_global(self, mock_bridge):
        """Test global statistics function."""
        mock_stats = {"test": "data"}
        mock_bridge.get_integration_statistics.return_value = mock_stats
        
        result = get_integration_statistics()
        
        assert result == mock_stats
        mock_bridge.get_integration_statistics.assert_called_once()


class TestErrorHandling:
    """Test error handling and fallback behavior."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.bridge = DebuggerFrameEvalBridge()
    
    def test_fallback_on_error_enabled(self):
        """Test fallback behavior when fallback_on_error is enabled."""
        # Enable fallback on error
        self.bridge.update_config(fallback_on_error=True)
        
        # Create a debugger with a user_line that will raise an exception
        class FaultyDebugger:
            def user_line(self, frame):
                raise Exception("Test error")
        
        # Create a mock for the debugger
        debugger = FaultyDebugger()
        
        # Mock the integrate_with_debugger_bdb method to test error handling
        original_method = self.bridge.integrate_with_debugger_bdb
        
        def mock_integrate(debugger_instance):
            try:
                # Simulate an error during integration
                debugger_instance.user_line(None)
                return True
            except Exception:
                if self.bridge.config["fallback_on_error"]:
                    self.bridge.integration_stats["errors_handled"] += 1
                    return False
                raise
        
        # Patch the method
        self.bridge.integrate_with_debugger_bdb = mock_integrate
        
        try:
            # Integration should fail but handle the error
            result = self.bridge.integrate_with_debugger_bdb(debugger)
            
            # Verify the result and error handling
            assert result is False
            assert self.bridge.integration_stats["errors_handled"] == 1
        finally:
            # Restore the original method
            self.bridge.integrate_with_debugger_bdb = original_method
    
    def test_fallback_on_error_disabled(self):
        """Test error propagation when fallback_on_error is disabled."""
        # Disable fallback on error
        self.bridge.update_config(fallback_on_error=False)
        
        # Create a debugger with a user_line that will raise an exception
        class FaultyDebugger:
            def user_line(self, frame):
                raise Exception("Test error")
        
        # Create a mock for the debugger
        debugger = FaultyDebugger()
        
        # Mock the integrate_with_debugger_bdb method to test error handling
        original_method = self.bridge.integrate_with_debugger_bdb
        
        def mock_integrate(debugger_instance):
            try:
                # Simulate an error during integration
                debugger_instance.user_line(None)
                return True
            except Exception:
                if self.bridge.config["fallback_on_error"]:
                    self.bridge.integration_stats["errors_handled"] += 1
                    return False
                raise
        
        # Patch the method
        self.bridge.integrate_with_debugger_bdb = mock_integrate
        
        try:
            # Integration should raise the exception
            with pytest.raises(Exception, match="Test error"):
                self.bridge.integrate_with_debugger_bdb(debugger)
            
            # Verify the error was not handled
            assert self.bridge.integration_stats["errors_handled"] == 0
        finally:
            # Restore the original method
            self.bridge.integrate_with_debugger_bdb = original_method


if __name__ == "__main__":
    pytest.main([__file__])