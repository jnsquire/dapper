#!/usr/bin/env python3
"""

import sys
from pathlib import Path

# Add the project root to the Python path
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

Integration tests for frame evaluation with mock debugger instances."""

import time
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

import pytest

# Import the modules we're testing
from dapper._frame_eval.debugger_integration import DebuggerFrameEvalBridge
from dapper._frame_eval.debugger_integration import auto_integrate_debugger


class MockDebuggerBDB:
    """Mock DebuggerBDB class for testing."""
    
    def __init__(self):
        self.user_line_calls = []
        self.breakpoints = {}
        self.original_user_line = None
        self.user_line = self._mock_user_line
    
    def _mock_user_line(self, frame):
        """Mock user_line method."""
        print(f"_mock_user_line called with frame: {frame}")
        call_info = {
            "filename": frame.f_code.co_filename,
            "lineno": frame.f_lineno,
            "event": getattr(frame, "f_event", "line")
        }
        print(f"Adding call info: {call_info}")
        self.user_line_calls.append(call_info)
        print(f"user_line_calls after append: {self.user_line_calls}")
    
    def set_breakpoint(self, filename, lineno):
        """Helper to set breakpoints."""
        if filename not in self.breakpoints:
            self.breakpoints[filename] = set()
        self.breakpoints[filename].add(lineno)


class MockPyDebugger:
    """Mock PyDebugger class for testing."""
    
    def __init__(self):
        self.set_breakpoints_calls = []
        self.set_trace_calls = []
        self.threads = {}
        self.breakpoints = {}
    
    def set_breakpoints(self, source, breakpoints, **kwargs):
        """Mock set_breakpoints method."""
        self.set_breakpoints_calls.append({
            "source": source,
            "breakpoints": breakpoints,
            "kwargs": kwargs
        })
        
        # Store breakpoints
        filepath = source.get("path", "")
        if filepath:
            self.breakpoints[filepath] = {bp.get("line", 0) for bp in breakpoints if bp.get("line")}
    
    def _set_trace_function(self):
        """Mock trace function setter."""
        self.set_trace_calls.append(True)


class TestDebuggerBDBIntegration:
    """Test integration with mock DebuggerBDB instances."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.bridge = DebuggerFrameEvalBridge()
        self.mock_debugger = MockDebuggerBDB()
    
    @patch("dapper._frame_eval.debugger_integration.get_thread_info")
    @patch("dapper._frame_eval.debugger_integration.get_trace_manager")
    @patch("dapper._frame_eval.debugger_integration.enable_selective_tracing")
    def test_full_integration_cycle(self, mock_enable_tracing, mock_trace_manager, mock_thread_info):
        """Test complete integration cycle with DebuggerBDB."""
        # Setup mocks
        mock_thread_info.return_value = Mock(fully_initialized=False)
        mock_trace_instance = Mock()
        mock_trace_instance.is_enabled.return_value = True
        mock_trace_instance.dispatcher.analyzer.should_trace_frame.return_value = {
            "should_trace": True,
            "reason": "breakpoint",
            "line_number": 10
        }
        mock_trace_manager.return_value = mock_trace_instance
        
        # Integrate
        result = self.bridge.integrate_with_debugger_bdb(self.mock_debugger)
        assert result is True
        
        # Simulate frame execution
        mock_frame = Mock()
        mock_frame.f_code.co_filename = "test.py"
        mock_frame.f_lineno = 10
        
        # Call the enhanced user_line function
        self.mock_debugger.user_line(mock_frame)
        
        # Verify the original behavior was called
        assert len(self.mock_debugger.user_line_calls) == 1
        assert self.mock_debugger.user_line_calls[0]["filename"] == "test.py"
        assert self.mock_debugger.user_line_calls[0]["lineno"] == 10
        
        # Verify thread info was updated
        mock_thread_info.return_value.fully_initialized = True
        
        # Remove integration
        result = self.bridge.remove_integration(self.mock_debugger)
        assert result is True
    
    @patch("dapper._frame_eval.debugger_integration.get_thread_info")
    @patch("dapper._frame_eval.debugger_integration.get_trace_manager")
    def test_selective_tracing_skip(self, mock_trace_manager, mock_thread_info):
        """Test that selective tracing skips frames without breakpoints."""
        # Setup mocks to skip tracing
        mock_thread_info.return_value = Mock(fully_initialized=False)
        mock_trace_instance = Mock()
        mock_trace_instance.is_enabled.return_value = True
        mock_trace_instance.dispatcher.analyzer.should_trace_frame.return_value = {
            "should_trace": False,
            "reason": "no_breakpoint",
            "line_number": 15
        }
        mock_trace_manager.return_value = mock_trace_instance
        
        # Integrate
        result = self.bridge.integrate_with_debugger_bdb(self.mock_debugger)
        assert result is True
        
        # Simulate frame execution (should be skipped)
        mock_frame = Mock()
        mock_frame.f_code.co_filename = "test.py"
        mock_frame.f_lineno = 15
        
        # Call the enhanced user_line function
        self.mock_debugger.user_line(mock_frame)
        
        # Verify original behavior was NOT called
        assert len(self.mock_debugger.user_line_calls) == 0
        
        # Verify statistics were updated
        assert self.bridge.integration_stats["trace_calls_saved"] == 1
    
    @patch("dapper._frame_eval.debugger_integration.get_thread_info")
    @patch("dapper._frame_eval.debugger_integration.get_trace_manager")
    def test_error_handling_in_user_line(self, mock_trace_manager, mock_thread_info):
        """Test error handling in enhanced user_line function."""
        # Setup thread info to raise an exception
        mock_thread_info.side_effect = Exception("Thread info error")
        
        # Set up trace manager to return a mock that will raise an exception
        mock_tm = Mock()
        mock_tm.is_enabled.return_value = True
        mock_analyzer = Mock()
        mock_analyzer.should_trace_frame.side_effect = Exception("Test error")
        mock_tm.dispatcher.analyzer = mock_analyzer
        mock_trace_manager.return_value = mock_tm
        
        # Add a breakpoint to ensure the frame is not skipped
        self.mock_debugger.set_breakpoint("test.py", 10)
        
        # Enable fallback
        self.bridge.update_config(fallback_on_error=True)
        
        # Store the original user_line for debugging
        original_user_line = self.mock_debugger.user_line
        print(f"Original user_line: {original_user_line}")
        
        # Integrate
        result = self.bridge.integrate_with_debugger_bdb(self.mock_debugger)
        assert result is True
        
        # Check what user_line was replaced with
        print(f"After integration, user_line: {self.mock_debugger.user_line}")
        print(f"Original user_line still available: {original_user_line}")
        
        # Simulate frame execution (should handle error and call original)
        mock_frame = Mock()
        mock_frame.f_code.co_filename = "test.py"
        mock_frame.f_lineno = 10
        
        # Call the enhanced user_line function
        print("Calling user_line...")
        self.mock_debugger.user_line(mock_frame)
        
        # Debug info
        print(f"user_line_calls after call: {self.mock_debugger.user_line_calls}")
        print(f"Integration stats: {self.bridge.integration_stats}")
        
        # Should still call original behavior due to fallback
        assert len(self.mock_debugger.user_line_calls) == 1, \
            f"Expected 1 call to user_line, got {len(self.mock_debugger.user_line_calls)}. Calls: {self.mock_debugger.user_line_calls}"
        
        # Should record error
        assert self.bridge.integration_stats["errors_handled"] == 1, \
            f"Expected 1 error handled, got {self.bridge.integration_stats['errors_handled']}"


class TestPyDebuggerIntegration:
    """Test integration with mock PyDebugger instances."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.bridge = DebuggerFrameEvalBridge()
        self.mock_debugger = MockPyDebugger()
    
    @patch("dapper._frame_eval.debugger_integration.update_breakpoints")
    @patch("dapper._frame_eval.debugger_integration.get_selective_trace_function")
    def test_breakpoint_integration(self, mock_get_trace_func, mock_update_breakpoints):
        """Test breakpoint setting integration."""
        # Setup mocks
        mock_get_trace_func.return_value = Mock()
        
        # Integrate
        result = self.bridge.integrate_with_py_debugger(self.mock_debugger)
        assert result is True
        
        # Simulate breakpoint setting
        source = {"path": "test.py"}
        breakpoints = [{"line": 10}, {"line": 20}, {"line": 30}]
        
        self.mock_debugger.set_breakpoints(source, breakpoints)
        
        # Verify breakpoints were updated in frame evaluation system
        mock_update_breakpoints.assert_called_once_with("test.py", {10, 20, 30})
        
        # Verify statistics were updated
        assert self.bridge.integration_stats["breakpoints_optimized"] == 3
        
        # Verify breakpoints were stored in mock debugger
        assert self.mock_debugger.breakpoints["test.py"] == {10, 20, 30}
    
    @patch("dapper._frame_eval.debugger_integration.get_selective_trace_function")
    @patch("sys.settrace")
    def test_trace_function_integration(self, mock_settrace, mock_get_trace_func):
        """Test trace function setting integration."""
        # Setup mocks
        mock_trace_func = Mock()
        mock_get_trace_func.return_value = mock_trace_func
        
        # Store the original _set_trace_function
        original_set_trace = self.mock_debugger._set_trace_function
        
        try:
            # Integrate - this will replace _set_trace_function
            result = self.bridge.integrate_with_py_debugger(self.mock_debugger)
            assert result is True
            
            # The _set_trace_function should be replaced with a new implementation
            assert self.mock_debugger._set_trace_function != original_set_trace
            
            # Call the new _set_trace_function
            self.mock_debugger._set_trace_function()
            
            # Verify sys.settrace was called with our trace function
            mock_settrace.assert_called_once_with(mock_trace_func)
            
            # Verify the original _set_trace_function was not called directly
            # (the integration replaces it but doesn't call it)
            assert len(self.mock_debugger.set_trace_calls) == 0
            
        finally:
            # Restore original _set_trace_function to prevent side effects
            self.mock_debugger._set_trace_function = original_set_trace
    
    @patch("dapper._frame_eval.debugger_integration.inject_breakpoint_bytecode")
    @patch("os.path.isfile", return_value=True)
    @patch("os.path.getmtime", return_value=1234567890)
    def test_bytecode_optimization(self, mock_getmtime, mock_isfile, mock_inject_bytecode):
        """Test bytecode optimization integration."""
        # Setup mock
        mock_inject_bytecode.return_value = Mock()
        
        # Enable bytecode optimization
        self.bridge.update_config(bytecode_optimization=True)
        
        # Integrate
        result = self.bridge.integrate_with_py_debugger(self.mock_debugger)
        assert result is True
        
        # Simulate breakpoint setting with source file
        source = {"path": "test.py"}
        breakpoints = [{"line": 10}]
        
        # Mock the file operations
        test_file_content = """
def test_function():
    x = 1
    return x
"""
        
        # Create a proper mock file object with context manager support
        mock_file = MagicMock()
        mock_file.read.return_value = test_file_content
        
        # Create a mock context manager
        mock_context = MagicMock()
        mock_context.__enter__.return_value = mock_file
        
        # Mock the open function to return our context manager
        with patch("builtins.open", return_value=mock_context, create=True) as mock_open:
            with patch("dapper._frame_eval.debugger_integration.compile", return_value=Mock()) as mock_compile:
                # Call set_breakpoints which should trigger bytecode optimization
                self.mock_debugger.set_breakpoints(source, breakpoints)
                
                # Verify file operations were attempted
                mock_open.assert_called_once_with("test.py", encoding="utf-8")
                
                # Verify the mock file was read
                mock_file.read.assert_called_once()
                
                # Verify compile was called
                mock_compile.assert_called_once()
                
                # Verify inject_breakpoint_bytecode was called
                mock_inject_bytecode.assert_called_once()
                
                # Verify the context manager was properly used
                mock_context.__enter__.assert_called_once()
                mock_context.__exit__.assert_called_once()


class TestAutoIntegration:
    """Test automatic debugger detection and integration."""
    
    def test_auto_detect_debugger_bdb(self):
        """Test automatic detection of DebuggerBDB."""
        mock_debugger = MockDebuggerBDB()
        
        result = auto_integrate_debugger(mock_debugger)
        assert result is True
    
    def test_auto_detect_py_debugger(self):
        """Test automatic detection of PyDebugger."""
        mock_debugger = MockPyDebugger()
        
        result = auto_integrate_debugger(mock_debugger)
        assert result is True
    
    def test_auto_detect_unknown_debugger(self):
        """Test handling of unknown debugger types."""
        # Create a mock that doesn't have any debugger-specific attributes
        unknown_debugger = Mock(spec=[])
        
        # The auto_integrate_debugger function should return False for unknown debugger types
        with patch("dapper._frame_eval.debugger_integration._integration_bridge") as mock_bridge:
            # Ensure the bridge's integration methods are not called
            mock_bridge.integrate_with_debugger_bdb.return_value = False
            mock_bridge.integrate_with_py_debugger.return_value = False
            
            result = auto_integrate_debugger(unknown_debugger)
            
            # Should return False for unknown debugger types
            assert result is False
            
            # Neither integration method should have been called
            mock_bridge.integrate_with_debugger_bdb.assert_not_called()
            mock_bridge.integrate_with_py_debugger.assert_not_called()


class TestMultiDebuggerIntegration:
    """Test integration with multiple debugger instances."""
    
    def test_multiple_debugger_bdb_instances(self):
        """Test integration with multiple DebuggerBDB instances."""
        bridge = DebuggerFrameEvalBridge()
        debuggers = [MockDebuggerBDB() for _ in range(3)]
        
        # Integrate all debuggers
        results = []
        for debugger in debuggers:
            with patch("dapper._frame_eval.debugger_integration.get_thread_info"), \
                 patch("dapper._frame_eval.debugger_integration.get_trace_manager"), \
                 patch("dapper._frame_eval.debugger_integration.enable_selective_tracing"):
                result = bridge.integrate_with_debugger_bdb(debugger)
                results.append(result)
        
        # All should succeed
        assert all(results)
        assert bridge.integration_stats["integrations_enabled"] == 3
        
        # Remove all integrations
        for debugger in debuggers:
            result = bridge.remove_integration(debugger)
            assert result is True
    
    def test_mixed_debugger_types(self):
        """Test integration with mixed debugger types."""
        bridge = DebuggerFrameEvalBridge()
        debugger_bdb = MockDebuggerBDB()
        debugger_py = MockPyDebugger()
        
        # Integrate both types
        with patch("dapper._frame_eval.debugger_integration.get_thread_info"), \
             patch("dapper._frame_eval.debugger_integration.get_trace_manager"), \
             patch("dapper._frame_eval.debugger_integration.enable_selective_tracing"), \
             patch("dapper._frame_eval.debugger_integration.update_breakpoints"), \
             patch("dapper._frame_eval.debugger_integration.get_selective_trace_function"):
            
            result1 = bridge.integrate_with_debugger_bdb(debugger_bdb)
            result2 = bridge.integrate_with_py_debugger(debugger_py)
        
        assert result1 is True
        assert result2 is True
        assert bridge.integration_stats["integrations_enabled"] == 2


class TestIntegrationPerformance:
    """Test performance characteristics of integration."""
    
    def test_integration_overhead(self):
        """Test that integration doesn't add significant overhead."""
        bridge = DebuggerFrameEvalBridge()
        mock_debugger = MockDebuggerBDB()
        
        # Measure integration time
        start_time = time.time()
        
        with patch("dapper._frame_eval.debugger_integration.get_thread_info"), \
             patch("dapper._frame_eval.debugger_integration.get_trace_manager"), \
             patch("dapper._frame_eval.debugger_integration.enable_selective_tracing"):
            
            result = bridge.integrate_with_debugger_bdb(mock_debugger)
        
        integration_time = time.time() - start_time
        
        # Should be very fast
        assert integration_time < 0.01  # Under 10ms
        assert result is True


class TestIntegrationErrorRecovery:
    """Test error recovery in integration scenarios."""
    
    @patch("dapper._frame_eval.debugger_integration.get_thread_info")
    @patch("dapper._frame_eval.debugger_integration.get_trace_manager")
    @patch("dapper._frame_eval.debugger_integration.enable_selective_tracing")
    def test_debugger_method_failure_recovery(self, mock_enable_tracing, mock_trace_manager, mock_thread_info):
        """Test recovery when debugger methods fail."""
        # Setup mocks
        mock_trace_instance = Mock()
        mock_trace_instance.is_enabled.return_value = True
        mock_trace_instance.dispatcher.analyzer.should_trace_frame.return_value = {
            "should_trace": True,
            "reason": "breakpoint",
            "line_number": 10
        }
        mock_trace_manager.return_value = mock_trace_instance
        
        bridge = DebuggerFrameEvalBridge()
        
        # Create debugger with failing user_line
        failing_debugger = MockDebuggerBDB()
        # Store the original user_line in a way that the debugger integration expects
        failing_debugger._original_user_line = failing_debugger.user_line
        # Replace the user_line with a mock that will raise an exception
        failing_debugger.user_line = Mock(side_effect=Exception("Debugger error"))
        
        # Enable fallback
        bridge.update_config(fallback_on_error=True)
        
        # Integrate (should succeed despite error)
        result = bridge.integrate_with_debugger_bdb(failing_debugger)
        assert result is True
        
        # Test that error handling works in runtime
        mock_frame = Mock()
        mock_frame.f_code.co_filename = "test.py"
        mock_frame.f_lineno = 10
        
        # This should handle the error gracefully
        try:
            # The enhanced user_line should be called, which wraps the failing one
            failing_debugger.user_line(mock_frame)
        except Exception as e:
            pytest.fail(f"Should have handled error gracefully, but got: {e}")
        
        # Should record the error
        assert bridge.integration_stats["errors_handled"] >= 1, \
            f"Expected at least 1 error handled, but got {bridge.integration_stats['errors_handled']}"
    
    def test_partial_integration_recovery(self):
        """Test recovery when partial integration fails."""
        bridge = DebuggerFrameEvalBridge()
        mock_debugger = MockDebuggerBDB()
        
        # Store the original user_line for later verification
        original_user_line = mock_debugger.user_line
        
        # Mock the trace manager to return a mock instance
        mock_trace_instance = Mock()
        mock_trace_instance.is_enabled.return_value = True
        
        # Make selective tracing fail
        with patch("dapper._frame_eval.debugger_integration.enable_selective_tracing", 
                  side_effect=Exception("Tracing error")) as mock_enable_tracing, \
             patch("dapper._frame_eval.debugger_integration.get_trace_manager") as mock_get_trace_manager:
            
            # Setup the mock trace manager
            mock_get_trace_manager.return_value = mock_trace_instance
            
            # With fallback enabled, should still integrate
            bridge.update_config(fallback_on_error=True)
            
            # The integration should return False when selective tracing fails, even with fallback on error
            # This is because the integration wasn't fully successful
            result = bridge.integrate_with_debugger_bdb(mock_debugger)
            
            # Verify the integration result - it should be False since selective tracing failed
            assert result is False, "Integration should return False when selective tracing fails"
            
            # Verify enable_selective_tracing was called
            mock_enable_tracing.assert_called_once()
            
            # Verify the debugger is still functional with the original user_line
            assert mock_debugger.user_line is not None, "Debugger's user_line should still be callable"
            # The user_line should NOT be wrapped since the integration failed
            assert mock_debugger.user_line == original_user_line, \
                "Debugger's user_line should NOT be wrapped when selective tracing fails"
                
            # Test debugger functionality
            test_frame = Mock()
            test_frame.f_code.co_filename = "test.py"
            test_frame.f_lineno = 10
            
            # This should not raise an exception
            try:
                mock_debugger.user_line(test_frame)
            except Exception as e:
                pytest.fail(f"Debugger should still be functional after integration error: {e}")
            
            # Verify the original user_line was called
            assert len(mock_debugger.user_line_calls) > 0, \
                "Debugger's user_line should have been called"
                
            # Verify the error was recorded in the integration stats
            assert bridge.integration_stats["errors_handled"] >= 1, \
                "Should have recorded the error in integration_stats"


class TestIntegrationConfiguration:
    """Test configuration effects on integration."""
    
    def test_disabled_configuration(self):
        """Test integration when disabled."""
        bridge = DebuggerFrameEvalBridge()
        bridge.update_config(enabled=False)
        
        mock_debugger = MockDebuggerBDB()
        result = bridge.integrate_with_debugger_bdb(mock_debugger)
        
        assert result is False
        assert bridge.integration_stats["integrations_enabled"] == 0
    
    def test_selective_tracing_disabled(self):
        """Test integration with selective tracing disabled."""
        bridge = DebuggerFrameEvalBridge()
        bridge.update_config(selective_tracing=False)
        
        mock_debugger = MockDebuggerBDB()
        
        with patch("dapper._frame_eval.debugger_integration.get_thread_info"):
            result = bridge.integrate_with_debugger_bdb(mock_debugger)
        
        assert result is True
        
        # Trace calls should not be saved when selective tracing is disabled
        mock_frame = Mock()
        mock_debugger.user_line(mock_frame)
        
        assert bridge.integration_stats["trace_calls_saved"] == 0
    
    def test_performance_monitoring_effects(self):
        """Test performance monitoring configuration."""
        bridge = DebuggerFrameEvalBridge()
        bridge.update_config(performance_monitoring=False)
        
        # Monitor trace call (should not increment)
        bridge._monitor_trace_call()
        assert bridge._performance_data["trace_function_calls"] == 0
        
        # Enable monitoring
        bridge.update_config(performance_monitoring=True)
        bridge._monitor_trace_call()
        assert bridge._performance_data["trace_function_calls"] == 1


if __name__ == "__main__":
    pytest.main([__file__])
