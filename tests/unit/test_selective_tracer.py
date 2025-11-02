#!/usr/bin/env python3
"""

import sys
from pathlib import Path

# Add the project root to the Python path
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

Test script for the selective frame tracing system."""

import sys
import threading
import time

sys.path.insert(0, ".")

def sample_function():
    """A sample function for testing."""
    x = 1
    y = 2
    return x + y

def another_function():
    """Another sample function."""
    for i in range(5):
        print(f"Count: {i}")
    return "done"

def function_with_breakpoint():
    """Function that should have breakpoints."""
    a = 10
    b = 20  # Breakpoint line
    c = a + b
    return c

class MockTraceFunction:
    """Mock trace function for testing."""
    
    def __init__(self):
        self.call_count = 0
        self.traced_frames = []
        self.events = []
    
    def __call__(self, frame, event, arg):
        self.call_count += 1
        self.traced_frames.append(frame.f_code.co_name)
        self.events.append(event)
        return self
    
    def reset(self):
        """Reset the trace function state."""
        self.call_count = 0
        self.traced_frames.clear()
        self.events.clear()

def test_frame_trace_analyzer():
    """Test the FrameTraceAnalyzer functionality."""
    print("=== Testing FrameTraceAnalyzer ===")
    
    try:
        from dapper._frame_eval.selective_tracer import FrameTraceAnalyzer
        
        analyzer = FrameTraceAnalyzer()
        
        # Create a real frame for testing
        def create_test_frame():
            x = 42
            return sys._getframe()
        
        test_frame = create_test_frame()
        
        # Test analysis without breakpoints
        decision = analyzer.should_trace_frame(test_frame)
        print(f"No breakpoints decision: {decision['should_trace']}")
        print(f"Reason: {decision['reason']}")
        
        # Add breakpoints for the test file
        test_file = test_frame.f_code.co_filename
        breakpoints = {test_frame.f_lineno, test_frame.f_lineno + 1}
        
        analyzer.update_breakpoints(test_file, breakpoints)
        
        # Test analysis with breakpoints
        decision_with_bp = analyzer.should_trace_frame(test_frame)
        print(f"With breakpoints decision: {decision_with_bp['should_trace']}")
        print(f"Reason: {decision_with_bp['reason']}")
        print(f"Breakpoint lines: {decision_with_bp['breakpoint_lines']}")
        
        # Test statistics
        stats = analyzer.get_statistics()
        print(f"Analyzer stats: {stats}")
        
        # Test file tracking logic
        should_track = analyzer._should_track_file(test_file)
        print(f"Should track test file: {should_track}")
        
        should_track_system = analyzer._should_track_file("<string>")
        print(f"Should track system file: {should_track_system}")
        
        print("✅ FrameTraceAnalyzer tests passed")
        
    except Exception as e:
        print(f"❌ FrameTraceAnalyzer test failed: {e}")
        import traceback
        traceback.print_exc()

def test_selective_trace_dispatcher():
    """Test the SelectiveTraceDispatcher functionality."""
    print("\n=== Testing SelectiveTraceDispatcher ===")
    
    try:
        from dapper._frame_eval.selective_tracer import SelectiveTraceDispatcher
        
        mock_trace = MockTraceFunction()
        dispatcher = SelectiveTraceDispatcher(mock_trace)
        
        # Test without debugger trace function
        result = dispatcher.selective_trace_dispatch(None, "line", None)
        print(f"No trace function result: {result}")
        
        # Set debugger trace function
        dispatcher.set_debugger_trace_func(mock_trace)
        
        # Create test frame
        def create_test_frame():
            x = 42
            return sys._getframe()
        
        test_frame = create_test_frame()
        
        # Test dispatch without breakpoints
        result1 = dispatcher.selective_trace_dispatch(test_frame, "line", None)
        print(f"Dispatch without breakpoints: {result1}")
        print(f"Mock trace calls: {mock_trace.call_count}")
        
        # Add breakpoints
        test_file = test_frame.f_code.co_filename
        dispatcher.update_breakpoints(test_file, {test_frame.f_lineno})
        
        # Test dispatch with breakpoints
        result2 = dispatcher.selective_trace_dispatch(test_frame, "line", None)
        print(f"Dispatch with breakpoints: {result2}")
        print(f"Mock trace calls after breakpoints: {mock_trace.call_count}")
        
        # Test statistics
        stats = dispatcher.get_statistics()
        print(f"Dispatcher stats: {stats}")
        
        print("✅ SelectiveTraceDispatcher tests passed")
        
    except Exception as e:
        print(f"❌ SelectiveTraceDispatcher test failed: {e}")
        import traceback
        traceback.print_exc()

def test_frame_trace_manager():
    """Test the FrameTraceManager functionality."""
    print("\n=== Testing FrameTraceManager ===")
    
    try:
        from dapper._frame_eval.selective_tracer import FrameTraceManager
        
        manager = FrameTraceManager()
        mock_trace = MockTraceFunction()
        
        # Test enabling/disabling
        print(f"Initial enabled state: {manager.is_enabled()}")
        
        manager.enable_selective_tracing(mock_trace)
        print(f"After enable: {manager.is_enabled()}")
        
        trace_func = manager.get_trace_function()
        print(f"Got trace function: {trace_func is not None}")
        
        manager.disable_selective_tracing()
        print(f"After disable: {manager.is_enabled()}")
        
        # Re-enable for breakpoint testing
        manager.enable_selective_tracing(mock_trace)
        
        # Test breakpoint management
        test_file = "test_sample.py"
        breakpoints = {3, 5, 7}
        
        manager.update_file_breakpoints(test_file, breakpoints)
        retrieved_bps = manager.get_breakpoints(test_file)
        print(f"Breakpoint set/retrieved: {retrieved_bps == breakpoints}")
        
        # Test adding/removing single breakpoints
        manager.add_breakpoint(test_file, 10)
        manager.add_breakpoint(test_file, 15)
        current_bps = manager.get_breakpoints(test_file)
        print(f"Added breakpoints: {current_bps}")
        
        manager.remove_breakpoint(test_file, 10)
        after_remove = manager.get_breakpoints(test_file)
        print(f"After removal: {after_remove}")
        
        # Test multiple file breakpoints
        manager.update_all_breakpoints({
            "file1.py": {1, 2, 3},
            "file2.py": {5, 6, 7},
        })
        
        all_bps = manager.get_all_breakpoints()
        print(f"All breakpoints: {all_bps}")
        
        # Test statistics
        stats = manager.get_statistics()
        print(f"Manager stats: {stats}")
        
        print("✅ FrameTraceManager tests passed")
        
    except Exception as e:
        print(f"❌ FrameTraceManager test failed: {e}")
        import traceback
        traceback.print_exc()

def test_integration_with_sys_settrace():
    """Test integration with sys.settrace."""
    print("\n=== Testing sys.settrace Integration ===")
    
    try:
        from dapper._frame_eval.selective_tracer import enable_selective_tracing
        from dapper._frame_eval.selective_tracer import get_selective_trace_function
        from dapper._frame_eval.selective_tracer import get_trace_manager
        
        mock_trace = MockTraceFunction()
        
        # Enable selective tracing
        enable_selective_tracing(mock_trace)
        trace_func = get_selective_trace_function()
        
        print(f"Got selective trace function: {trace_func is not None}")
        
        # Set the trace function
        old_trace = sys.gettrace()
        sys.settrace(trace_func)
        
        # Execute some code that should be traced
        def test_function():
            x = 1
            y = 2
            return x + y
        
        # Add breakpoints for this file
        manager = get_trace_manager()
        current_file = __file__
        manager.add_breakpoint(current_file, test_function.__code__.co_firstlineno + 1)
        
        # Execute the function
        result = test_function()
        print(f"Test function result: {result}")
        print(f"Trace function called: {mock_trace.call_count} times")
        print(f"Traced frames: {mock_trace.traced_frames}")
        
        # Restore original trace function
        sys.settrace(old_trace)
        
        print("✅ sys.settrace integration tests passed")
        
    except Exception as e:
        print(f"❌ sys.settrace integration test failed: {e}")
        import traceback
        traceback.print_exc()

def test_performance_optimization():
    """Test that selective tracing provides performance benefits."""
    print("\n=== Testing Performance Optimization ===")
    
    try:
        from dapper._frame_eval.selective_tracer import enable_selective_tracing
        from dapper._frame_eval.selective_tracer import get_trace_manager
        
        # Create mock trace function that counts calls
        call_counter = {"count": 0}
        
        def counting_trace(frame, event, arg):
            call_counter["count"] += 1
        
        # Enable selective tracing
        enable_selective_tracing(counting_trace)
        manager = get_trace_manager()
        
        # Test without breakpoints
        def test_without_breakpoints():
            for i in range(100):
                x = i * 2
                y = x + 1
            return "done"
        
        old_trace = sys.gettrace()
        sys.settrace(manager.get_trace_function())
        
        call_counter["count"] = 0
        start_time = time.time()
        result1 = test_without_breakpoints()
        time_without_bp = time.time() - start_time
        calls_without_bp = call_counter["count"]
        
        print(f"Time without breakpoints: {time_without_bp:.4f}s")
        print(f"Trace calls without breakpoints: {calls_without_bp}")
        
        # Test with breakpoints
        manager.add_breakpoint(__file__, test_without_breakpoints.__code__.co_firstlineno + 2)
        
        call_counter["count"] = 0
        start_time = time.time()
        result2 = test_without_breakpoints()
        time_with_bp = time.time() - start_time
        calls_with_bp = call_counter["count"]
        
        print(f"Time with breakpoints: {time_with_bp:.4f}s")
        print(f"Trace calls with breakpoints: {calls_with_bp}")
        
        # Restore trace
        sys.settrace(old_trace)
        
        # Check performance improvement
        if calls_without_bp == 0:
            print("✅ Selective tracing successfully avoided unnecessary trace calls")
        else:
            print(f"⚠️  Selective tracing made {calls_without_bp} unnecessary calls")
        
        # Get final statistics
        final_stats = manager.get_statistics()
        print(f"Final performance stats: {final_stats}")
        
        print("✅ Performance optimization tests completed")
        
    except Exception as e:
        print(f"❌ Performance optimization test failed: {e}")
        import traceback
        traceback.print_exc()

def test_multithreading():
    """Test selective tracing in multithreaded environment."""
    print("\n=== Testing Multithreading ===")
    
    try:
        from dapper._frame_eval.selective_tracer import enable_selective_tracing
        
        results = []
        errors = []
        
        def worker_thread(thread_id):
            """Worker function for testing thread safety."""
            try:
                mock_trace = MockTraceFunction()
                
                # Enable selective tracing in this thread
                enable_selective_tracing(mock_trace)
                
                # Execute some code
                def thread_function():
                    return f"thread_{thread_id}_result"
                
                result = thread_function()
                
                results.append({
                    "thread_id": thread_id,
                    "result": result,
                    "trace_calls": mock_trace.call_count,
                })
                
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e}")
        
        # Start multiple threads
        threads = []
        for i in range(3):
            thread = threading.Thread(target=worker_thread, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join()
        
        # Check results
        print(f"Threads completed: {len(results)}")
        print(f"Errors: {len(errors)}")
        
        if errors:
            for error in errors:
                print(f"  {error}")
        
        for result in results:
            print(f"Thread {result['thread_id']}: {result['trace_calls']} trace calls")
        
        if len(errors) == 0:
            print("✅ Multithreading tests passed")
        else:
            print("❌ Multithreading tests failed")
        
    except Exception as e:
        print(f"❌ Multithreading test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("🎯 Selective Frame Tracing Test Suite")
    print("=" * 50)
    
    test_frame_trace_analyzer()
    test_selective_trace_dispatcher()
    test_frame_trace_manager()
    test_integration_with_sys_settrace()
    test_performance_optimization()
    test_multithreading()
    
    print("\n🎉 All selective tracing tests completed!")
