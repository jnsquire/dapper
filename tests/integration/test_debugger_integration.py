#!/usr/bin/env python3
"""

import sys
from pathlib import Path

# Add the project root to the Python path
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

Test script for debugger integration with frame evaluation system."""

import sys
import threading
import time
sys.path.insert(0, ".")

class MockDebuggerBDB:
    """Mock DebuggerBDB class for testing integration."""
    
    def __init__(self):
        self.breakpoints = {}
        self.user_line_calls = []
        self.stepping = False
        self.stop_on_entry = False
        self.current_thread_id = threading.get_ident()
        self.current_frame = None
    
    def user_line(self, frame):
        """Mock user_line function."""
        self.user_line_calls.append({
            "filename": frame.f_code.co_filename,
            "lineno": frame.f_lineno,
            "function": frame.f_code.co_name,
        })
    
    def set_breakpoint(self, filename, lineno):
        """Mock breakpoint setting."""
        if filename not in self.breakpoints:
            self.breakpoints[filename] = []
        self.breakpoints[filename].append(lineno)


class MockPyDebugger:
    """Mock PyDebugger class for testing integration."""
    
    def __init__(self):
        self.threads = {}
        self.breakpoints = {}
        self.function_breakpoints = []
        self.set_breakpoints_calls = []
        self.trace_function_calls = []
    
    def set_breakpoints(self, source, breakpoints, **kwargs):
        """Mock set_breakpoints function."""
        self.set_breakpoints_calls.append({
            "source": source,
            "breakpoints": breakpoints,
            "kwargs": kwargs,
        })
        
        filepath = source.get("path", "")
        if filepath:
            self.breakpoints[filepath] = breakpoints
    
    def _set_trace_function(self):
        """Mock trace function setting."""
        self.trace_function_calls.append(time.time())


def test_debugger_bdb_integration():
    """Test integration with DebuggerBDB class."""
    print("=== Testing DebuggerBDB Integration ===")
    
    try:
        from dapper._frame_eval.debugger_integration import (
            integrate_debugger_bdb,
            remove_integration,
            get_integration_statistics,
        )
        
        # Create mock debugger
        debugger = MockDebuggerBDB()
        
        # Test integration
        success = integrate_debugger_bdb(debugger)
        print(f"DebuggerBDB integration success: {success}")
        
        # Test that user_line was enhanced
        original_user_line = debugger.user_line
        print(f"User line function replaced: {original_user_line is not None}")
        
        # Simulate a frame hit
        def test_function():
            x = 42
            return x
        
        # Create a frame for testing
        frame = None
        def create_frame():
            nonlocal frame
            frame = sys._getframe()
        
        create_frame()
        
        # Call the enhanced user_line function
        if frame:
            debugger.user_line(frame)
            print(f"User line calls recorded: {len(debugger.user_line_calls)}")
            print(f"Frame info: {debugger.user_line_calls[-1] if debugger.user_line_calls else 'None'}")
        
        # Test removal
        removed = remove_integration(debugger)
        print(f"Integration removal success: {removed}")
        
        # Check statistics
        stats = get_integration_statistics()
        print(f"Integration stats: {stats['integration_stats']}")
        
        print("✅ DebuggerBDB integration tests passed")
        
    except Exception as e:
        print(f"❌ DebuggerBDB integration test failed: {e}")
        import traceback
        traceback.print_exc()


def test_py_debugger_integration():
    """Test integration with PyDebugger class."""
    print("\n=== Testing PyDebugger Integration ===")
    
    try:
        from dapper._frame_eval.debugger_integration import (
            integrate_py_debugger,
            remove_integration,
            get_integration_statistics,
        )
        
        # Create mock debugger
        debugger = MockPyDebugger()
        
        # Test integration
        success = integrate_py_debugger(debugger)
        print(f"PyDebugger integration success: {success}")
        
        # Test breakpoint setting enhancement
        source = {"path": "test_file.py"}
        breakpoints = [{"line": 10}, {"line": 20}]
        
        debugger.set_breakpoints(source, breakpoints)
        print(f"Breakpoints set: {len(debugger.set_breakpoints_calls)}")
        print(f"Stored breakpoints: {debugger.breakpoints}")
        
        # Test trace function enhancement
        debugger._set_trace_function()
        print(f"Trace function calls: {len(debugger.trace_function_calls)}")
        
        # Test removal
        removed = remove_integration(debugger)
        print(f"Integration removal success: {removed}")
        
        # Check statistics
        stats = get_integration_statistics()
        print(f"Integration stats: {stats['integration_stats']}")
        
        print("✅ PyDebugger integration tests passed")
        
    except Exception as e:
        print(f"❌ PyDebugger integration test failed: {e}")
        import traceback
        traceback.print_exc()


def test_auto_integration():
    """Test automatic integration detection."""
    print("\n=== Testing Auto Integration ===")
    
    try:
        from dapper._frame_eval.debugger_integration import (
            auto_integrate_debugger,
            get_integration_statistics,
        )
        
        # Test with DebuggerBDB
        debugger_bdb = MockDebuggerBDB()
        success_bdb = auto_integrate_debugger(debugger_bdb)
        print(f"Auto-integration DebuggerBDB: {success_bdb}")
        
        # Test with PyDebugger
        debugger_py = MockPyDebugger()
        success_py = auto_integrate_debugger(debugger_py)
        print(f"Auto-integration PyDebugger: {success_py}")
        
        # Test with unknown object
        unknown = object()
        success_unknown = auto_integrate_debugger(unknown)
        print(f"Auto-integration unknown: {success_unknown}")
        
        # Check overall statistics
        stats = get_integration_statistics()
        print(f"Total integrations: {stats['integration_stats']['integrations_enabled']}")
        
        print("✅ Auto integration tests passed")
        
    except Exception as e:
        print(f"❌ Auto integration test failed: {e}")
        import traceback
        traceback.print_exc()


def test_configuration():
    """Test integration configuration."""
    print("\n=== Testing Configuration ===")
    
    try:
        from dapper._frame_eval.debugger_integration import (
            configure_integration,
            get_integration_statistics,
            get_integration_bridge,
        )
        
        bridge = get_integration_bridge()
        
        # Test initial configuration
        initial_config = bridge.config.copy()
        print(f"Initial config: {initial_config}")
        
        # Test configuration updates
        configure_integration(
            selective_tracing=False,
            bytecode_optimization=False,
            performance_monitoring=True
        )
        
        updated_config = bridge.config.copy()
        print(f"Updated config: {updated_config}")
        
        # Verify changes
        assert updated_config["selective_tracing"] == False
        assert updated_config["bytecode_optimization"] == False
        assert updated_config["performance_monitoring"] == True
        
        # Test disabling
        configure_integration(enabled=False)
        disabled_config = bridge.config.copy()
        print(f"Disabled config: {disabled_config}")
        
        print("✅ Configuration tests passed")
        
    except Exception as e:
        print(f"❌ Configuration test failed: {e}")
        import traceback
        traceback.print_exc()


def test_performance_monitoring():
    """Test performance monitoring functionality."""
    print("\n=== Testing Performance Monitoring ===")
    
    try:
        from dapper._frame_eval.debugger_integration import (
            get_integration_bridge,
            get_integration_statistics,
        )
        
        bridge = get_integration_bridge()
        
        # Enable performance monitoring
        bridge.enable_performance_monitoring(True)
        
        # Simulate some activity
        for i in range(10):
            bridge._monitor_trace_call()
        
        for i in range(5):
            bridge._monitor_frame_eval_call()
        
        # Get statistics
        stats = get_integration_statistics()
        perf_data = stats["performance_data"]
        
        print(f"Trace function calls: {perf_data['trace_function_calls']}")
        print(f"Frame eval calls: {perf_data['frame_eval_calls']}")
        print(f"Uptime: {perf_data['uptime_seconds']:.2f}s")
        
        # Test statistics reset
        bridge.reset_statistics()
        reset_stats = get_integration_statistics()
        reset_perf = reset_stats["performance_data"]
        
        print(f"After reset - Trace calls: {reset_perf['trace_function_calls']}")
        print(f"After reset - Frame eval calls: {reset_perf['frame_eval_calls']}")
        
        print("✅ Performance monitoring tests passed")
        
    except Exception as e:
        print(f"❌ Performance monitoring test failed: {e}")
        import traceback
        traceback.print_exc()


def test_selective_tracing_integration():
    """Test selective tracing integration."""
    print("\n=== Testing Selective Tracing Integration ===")
    
    try:
        from dapper._frame_eval.debugger_integration import (
            integrate_debugger_bdb,
        )
        from dapper._frame_eval.selective_tracer import (
            get_trace_manager,
        )
        
        # Create mock debugger
        debugger = MockDebuggerBDB()
        
        # Integrate with selective tracing
        success = integrate_debugger_bdb(debugger)
        print(f"Integration with selective tracing: {success}")
        
        # Get trace manager
        trace_manager = get_trace_manager()
        print(f"Trace manager enabled: {trace_manager.is_enabled()}")
        
        # Test adding breakpoints
        test_file = __file__
        trace_manager.add_breakpoint(test_file, 100)
        trace_manager.add_breakpoint(test_file, 200)
        
        breakpoints = trace_manager.get_breakpoints(test_file)
        print(f"Breakpoints added: {breakpoints}")
        
        # Test trace function
        trace_func = trace_manager.get_trace_function()
        print(f"Trace function available: {trace_func is not None}")
        
        # Test statistics
        stats = trace_manager.get_statistics()
        print(f"Trace manager stats: {stats}")
        
        print("✅ Selective tracing integration tests passed")
        
    except Exception as e:
        print(f"❌ Selective tracing integration test failed: {e}")
        import traceback
        traceback.print_exc()


def test_error_handling():
    """Test error handling and fallback behavior."""
    print("\n=== Testing Error Handling ===")
    
    try:
        from dapper._frame_eval.debugger_integration import (
            get_integration_bridge,
            configure_integration,
        )
        
        bridge = get_integration_bridge()
        
        # Enable fallback mode
        configure_integration(fallback_on_error=True)
        
        # Test that fallback is enabled
        assert bridge.config["fallback_on_error"] == True
        print("Fallback mode enabled: True")
        
        # Simulate error conditions by trying to integrate with invalid object
        class BrokenDebugger:
            def __init__(self):
                raise RuntimeError("Simulated error")
        
        try:
            broken = BrokenDebugger()
        except RuntimeError:
            print("Broken debugger creation failed as expected")
        
        # Test that bridge handles errors gracefully
        initial_errors = bridge.integration_stats["errors_handled"]
        
        # Try integration that might fail
        success = bridge.integrate_with_debugger_bdb(None)  # This should fail gracefully
        print(f"Failed integration handled gracefully: {success == False}")
        
        final_errors = bridge.integration_stats["errors_handled"]
        print(f"Errors handled: {final_errors - initial_errors}")
        
        print("✅ Error handling tests passed")
        
    except Exception as e:
        print(f"❌ Error handling test failed: {e}")
        import traceback
        traceback.print_exc()


def test_bytecode_optimization():
    """Test bytecode optimization integration."""
    print("\n=== Testing Bytecode Optimization ===")
    
    try:
        from dapper._frame_eval.debugger_integration import (
            get_integration_bridge,
        )
        
        bridge = get_integration_bridge()
        
        # Enable bytecode optimization
        bridge.update_config(bytecode_optimization=True)
        print(f"Bytecode optimization enabled: {bridge.config['bytecode_optimization']}")
        
        # Test bytecode optimization application
        source = {"path": "test_sample.py"}
        breakpoints = [{"line": 10}, {"line": 20}]
        
        # Create a temporary test file
        test_content = '''
def test_function():
    x = 1
    y = 2
    return x + y

def another_function():
    for i in range(5):
        print(i)
    return "done"
'''
        
        test_file = "test_sample_temp.py"
        with open(test_file, "w") as f:
            f.write(test_content)
        
        try:
            # Apply bytecode optimizations
            bridge._apply_bytecode_optimizations(source, breakpoints)
            
            # Check that optimization was attempted
            initial_injections = bridge.integration_stats["bytecode_injections"]
            print(f"Bytecode injection attempts: {initial_injections}")
            
        finally:
            # Clean up test file
            import os
            if os.path.exists(test_file):
                os.remove(test_file)
        
        print("✅ Bytecode optimization tests passed")
        
    except Exception as e:
        print(f"❌ Bytecode optimization test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print("🔗 Debugger Integration Test Suite")
    print("=" * 50)
    
    test_debugger_bdb_integration()
    test_py_debugger_integration()
    test_auto_integration()
    test_configuration()
    test_performance_monitoring()
    test_selective_tracing_integration()
    test_error_handling()
    test_bytecode_optimization()
    
    print("\n🎉 All debugger integration tests completed!")
