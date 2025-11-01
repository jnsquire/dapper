"""
Frame tracing utilities for Dapper frame evaluation.

This module provides Python-level utilities for frame tracing, debugging,
and integration with Dapper's existing debugging infrastructure.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from types import CodeType
    from types import FrameType
    from typing import Callable

# Global state for frame tracing
_tracing_enabled = False
_breakpoint_wrapper_template = None
_trace_function_cache = {}


def create_pydev_trace_code_wrapper(line: int) -> str:
    """
    Create a code wrapper for debugging at a specific line.
    
    This generates Python code that can be inserted into bytecode
    to trigger debugging at specific line numbers.
    
    Args:
        line: The line number to create a wrapper for
        
    Returns:
        str: Python code string for the wrapper
    """
    global _breakpoint_wrapper_template
    
    if _breakpoint_wrapper_template is None:
        _breakpoint_wrapper_template = """
def _pydevd_frame_eval_wrapper():
    try:
        # Import the main debugger module
        import sys
        import os
        
        # Add the current directory to Python path if needed
        current_dir = os.path.dirname(os.path.abspath(__file__))
        if current_dir not in sys.path:
            sys.path.insert(0, current_dir)
        
        # Import Dapper debugging functions
        from dapper.debugger_bdb import DebuggerBDB
        
        # Get the current frame and check if we should stop
        frame = sys._getframe(1)
        thread_id = threading.get_ident()
        
        # Check if we have an active debugger
        if hasattr(sys, '_pydevd_frame_eval'):
            debugger_info = sys._pydevd_frame_eval
            if 'debugger' in debugger_info:
                debugger = debugger_info['debugger']
                
                # Check if this line has a breakpoint
                filename = frame.f_code.co_filename
                lineno = {line}
                
                if hasattr(debugger, '_check_breakpoint_at_line'):
                    should_stop = debugger._check_breakpoint_at_line(filename, lineno, frame)
                    if should_stop:
                        # Trigger the debugging stop
                        debugger.user_line(frame)
                        return
                        
        # Fallback to normal tracing if needed
        if hasattr(sys, 'trace_function'):
            trace_func = sys.trace_function
            if trace_func:
                trace_func(frame, 'line', None)
                
    except Exception:
        # Silently ignore errors in wrapper to avoid breaking execution
        pass

_pydevd_frame_eval_wrapper()
"""
    
    return _breakpoint_wrapper_template.format(line=line)


def update_globals_dict(globals_dict: dict[str, Any]) -> None:
    """
    Update the globals dictionary with debugging utilities.
    
    Args:
        globals_dict: The globals dictionary to update
    """
    # Add debugging utilities to globals
    globals_dict.update({
        "_pydevd_frame_eval_active": True,
        "_pydevd_frame_eval_line": None,
        "_pydevd_frame_eval_filename": None,
    })


def should_skip_frame(frame: FrameType) -> bool:
    """
    Determine if a frame should be skipped during frame evaluation.
    
    This implements the same logic as Dapper's existing frame filtering
    but optimized for C-level execution.
    
    Args:
        frame: The frame to check
        
    Returns:
        bool: True if the frame should be skipped
    """
    # Skip frames from the debugger itself
    filename = frame.f_code.co_filename
    
    # Skip internal debugger frames
    if any(path in filename for path in [
        "dapper/debugger_bdb.py",
        "dapper/server.py", 
        "dapper/debug_launcher.py",
        "dapper/_frame_eval/",
        "site-packages/",
        "python3.",
    ]):
        return True
    
    # Skip frames from standard library
    if any(path in filename for path in [
        "lib/python",
        "Python/Lib",
        "importlib",
        "threading.py",
        "asyncio/",
    ]):
        return True
    
    # Skip frames with no filename (like exec() or eval())
    if not filename or filename == "<string>":
        return True
    
    # Skip frames from generated code
    return bool(filename.startswith("<") and filename.endswith(">"))


def get_frame_filename(frame: FrameType) -> str:
    """
    Get the normalized filename for a frame.
    
    Args:
        frame: The frame to get the filename for
        
    Returns:
        str: Normalized filename
    """
    filename = frame.f_code.co_filename
    
    # Handle relative paths
    if not os.path.isabs(filename):
        try:
            filename = os.path.abspath(filename)
        except Exception:
            pass
    
    # Normalize path separators
    filename = os.path.normpath(filename)
    
    return filename


def is_debugger_frame(frame: FrameType) -> bool:
    """
    Check if a frame belongs to the debugger itself.
    
    Args:
        frame: The frame to check
        
    Returns:
        bool: True if the frame is from the debugger
    """
    filename = frame.f_code.co_filename
    function_name = frame.f_code.co_name
    
    # Check debugger module paths
    debugger_paths = [
        "dapper/debugger_bdb.py",
        "dapper/server.py",
        "dapper/debug_launcher.py",
        "dapper/_frame_eval/",
    ]
    
    if any(path in filename for path in debugger_paths):
        return True
    
    # Check debugger function names
    debugger_functions = [
        "user_line",
        "user_exception", 
        "user_call",
        "trace_dispatch",
        "_dispatch_line",
        "_dispatch_exception",
        "_dispatch_call",
    ]
    
    if function_name in debugger_functions:
        return True
    
    return False


def get_frame_info(frame: FrameType) -> Dict[str, Any]:
    """
    Extract relevant information from a frame for debugging.
    
    Args:
        frame: The frame to extract info from
        
    Returns:
        dict: Frame information dictionary
    """
    return {
        "filename": get_frame_filename(frame),
        "lineno": frame.f_lineno,
        "function": frame.f_code.co_name,
        "code_object": frame.f_code,
        "is_debugger_frame": is_debugger_frame(frame),
        "should_skip": should_skip_frame(frame),
    }


def create_trace_function_wrapper(original_trace: Callable) -> Callable:
    """
    Create a wrapper for trace functions that integrates with frame evaluation.
    
    Args:
        original_trace: The original trace function to wrap
        
    Returns:
        Callable: Wrapped trace function
    """
    def frame_eval_trace_wrapper(frame: FrameType, event: str, arg: Any) -> Any:
        # Skip frames that should be ignored
        if should_skip_frame(frame):
            return original_trace(frame, event, arg)
        
        # Handle frame evaluation specific logic
        if event == "line" and _tracing_enabled:
            # Check if we have frame evaluation active
            if hasattr(sys, "_pydevd_frame_eval_active"):
                frame_info = get_frame_info(frame)
                if not frame_info["should_skip"]:
                    # Let frame evaluation handle this
                    return None
        
        # Call original trace function
        return original_trace(frame, event, arg)
    
    return frame_eval_trace_wrapper


def invalidate_code_cache(code_obj: CodeType) -> None:
    """
    Invalidate cached information for a code object.
    
    This is called when breakpoints are changed or code is modified.
    
    Args:
        code_obj: The code object to invalidate cache for
    """
    # Clear any cached breakpoint information
    if hasattr(code_obj, "_frame_eval_cache"):
        delattr(code_obj, "_frame_eval_cache")
    
    # Clear from global cache
    global _trace_function_cache
    cache_key = (id(code_obj), code_obj.co_filename, code_obj.co_firstlineno)
    _trace_function_cache.pop(cache_key, None)


def get_breakpoint_lines_for_file(filename: str) -> Set[int]:
    """
    Get all breakpoint lines for a given file.
    
    Args:
        filename: The filename to get breakpoints for
        
    Returns:
        set: Set of line numbers with breakpoints
    """
    # This would integrate with Dapper's breakpoint storage
    # For now, return empty set - will be implemented in integration step
    return set()


def optimize_code_for_debugging(code_obj: CodeType) -> CodeType:
    """
    Optimize a code object for debugging with frame evaluation.
    
    Args:
        code_obj: The code object to optimize
        
    Returns:
        CodeType: Optimized code object
    """
    # For now, return the original code object
    # Optimization will be implemented in bytecode modification step
    return code_obj


def setup_frame_tracing(config: Dict[str, Any]) -> bool:
    """
    Set up frame tracing with the given configuration.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        bool: True if setup was successful
    """
    global _tracing_enabled
    
    try:
        _tracing_enabled = config.get("enabled", False)
        
        # Set up any additional configuration
        if _tracing_enabled:
            # Initialize any required state
            pass
        
        return True
    except Exception:
        return False


def cleanup_frame_tracing() -> None:
    """Clean up frame tracing state."""
    global _tracing_enabled, _trace_function_cache
    
    _tracing_enabled = False
    _trace_function_cache.clear()
