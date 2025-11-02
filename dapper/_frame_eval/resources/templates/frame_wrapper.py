def _pydevd_frame_eval_wrapper():
    try:
        # Import the main debugger module
        import sys
        import threading
        from pathlib import Path
        
        # Add the current directory to Python path if needed
        current_dir = str(Path(__file__).resolve().parent)
        if current_dir not in sys.path:
            sys.path.insert(0, current_dir)
        
        # Import Dapper debugging functions
        
        # Get the current frame and check if we should stop
        frame = sys._getframe(1)
        thread_id = threading.get_ident()
        
        # Check if we have an active debugger
        if hasattr(sys, "_pydevd_frame_eval"):
            debugger_info = sys._pydevd_frame_eval
            if "debugger" in debugger_info:
                debugger = debugger_info["debugger"]
                
                # Check if this line has a breakpoint
                filename = frame.f_code.co_filename
                lineno = {line}
                
                if hasattr(debugger, "_check_breakpoint_at_line"):
                    if debugger._check_breakpoint_at_line(thread_id, filename, lineno):
                        # If there's a breakpoint, call the trace function
                        debugger.trace_dispatch(frame, "line", None)
                        
    except Exception:
        # Make sure we don't break the application if there's an error in the debugger
        import traceback
        traceback.print_exc()
    
    # Always return the frame's trace function to maintain the call stack
    return frame.f_trace
