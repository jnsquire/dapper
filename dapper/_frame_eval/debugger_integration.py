"""
Integration layer for frame evaluation with Dapper debugger classes.

This module provides seamless integration between the high-performance frame
evaluation system and the existing PyDebugger and DebuggerBDB classes,
enabling automatic optimization while maintaining full compatibility.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set

if TYPE_CHECKING:
    from types import FrameType
    from typing_extensions import TypedDict
else:
    try:
        from typing_extensions import TypedDict
    except ImportError:
        from typing import TypedDict

# Import our frame evaluation components
from .cache_manager import (
    get_thread_info,
    set_func_code_info,
    get_func_code_info,
    clear_all_caches,
    get_cache_statistics,
)
from .selective_tracer import (
    get_trace_manager,
    enable_selective_tracing,
    disable_selective_tracing,
    get_selective_trace_function,
    update_breakpoints,
)
from .modify_bytecode import (
    BytecodeModifier,
    inject_breakpoint_bytecode,
    remove_breakpoint_bytecode,
)


class FrameEvalConfig(TypedDict):
    """Configuration for frame evaluation integration."""
    enabled: bool
    selective_tracing: bool
    bytecode_optimization: bool
    cache_enabled: bool
    performance_monitoring: bool
    fallback_on_error: bool


class IntegrationStatistics(TypedDict):
    """Statistics for frame evaluation integration."""
    config: FrameEvalConfig
    integration_stats: Dict[str, int]
    performance_data: Dict[str, Any]
    trace_manager_stats: Dict[str, Any]
    cache_stats: Dict[str, Any]


class DebuggerFrameEvalBridge:
    """
    Bridge between frame evaluation system and debugger classes.
    
    Provides automatic integration hooks that enhance debugger performance
    without requiring changes to existing debugger logic.
    """
    
    def __init__(self):
        self.config: FrameEvalConfig = {
            "enabled": True,
            "selective_tracing": True,
            "bytecode_optimization": True,
            "cache_enabled": True,
            "performance_monitoring": True,
            "fallback_on_error": True,
        }
        
        self.bytecode_modifier = BytecodeModifier()
        self.original_trace_functions = {}
        self.integration_stats = {
            "integrations_enabled": 0,
            "breakpoints_optimized": 0,
            "trace_calls_saved": 0,
            "bytecode_injections": 0,
            "errors_handled": 0,
        }
        self._lock = threading.RLock()
        
        # Performance monitoring
        self._performance_data = {
            "start_time": time.time(),
            "trace_function_calls": 0,
            "frame_eval_calls": 0,
            "cache_hits": 0,
            "cache_misses": 0,
        }
    
    def integrate_with_debugger_bdb(self, debugger_instance) -> bool:
        """
        Integrate frame evaluation with a DebuggerBDB instance.
        
        Args:
            debugger_instance: The DebuggerBDB instance to enhance
            
        Returns:
            True if integration was successful, False otherwise
        """
        if debugger_instance is None:
            return False
            
        # If user_line doesn't exist, provide a default no-op implementation
        if not hasattr(debugger_instance, "user_line") or not callable(debugger_instance.user_line):
            debugger_instance.user_line = lambda frame: None
            
        debugger_id = id(debugger_instance)
        
        # If we already have this debugger integrated, return True
        if debugger_id in self.original_trace_functions:
            return True
        
        # Store the original function first in case we need to restore it
        original_user_line = debugger_instance.user_line
        
        # Store a reference to the original user_line in the closure
        original_user_line_func = original_user_line
        
        # Store the original _mock_user_line method if it exists
        original_mock_user_line = getattr(debugger_instance, '_mock_user_line', None)
        print(f"[DEBUG] original_mock_user_line: {original_mock_user_line}")
        
        # Define the enhanced user_line function
        def enhanced_user_line(frame):
            print(f"[DEBUG] enhanced_user_line called with frame: {frame}")
            print(f"[DEBUG] selective_tracing: {self.config['selective_tracing']}")
            
            # Check if we should trace this frame
            if self.config["selective_tracing"]:
                print("[DEBUG] selective_tracing is enabled")
                try:
                    print("[DEBUG] Getting trace manager...")
                    trace_manager = get_trace_manager()
                    print(f"[DEBUG] Got trace_manager: {trace_manager}")
                    if trace_manager.is_enabled():
                        print("[DEBUG] trace_manager is enabled")
                        # Let the selective tracer handle the decision
                        try:
                            print("[DEBUG] Calling should_trace_frame...")
                            decision = trace_manager.dispatcher.analyzer.should_trace_frame(frame)
                            print(f"[DEBUG] Got decision: {decision}")
                            if not decision["should_trace"]:
                                # Skip the expensive debugger processing
                                print("[DEBUG] Skipping debugger processing")
                                self.integration_stats["trace_calls_saved"] += 1
                                return None
                        except Exception as e:
                            # If selective tracing fails, continue with normal execution
                            print(f"[DEBUG] Error in should_trace_frame: {e}")
                            self.integration_stats["errors_handled"] += 1
                            if self.config["fallback_on_error"] and original_user_line_func:
                                print("[DEBUG] Falling back to original user_line")
                                # Call the original _mock_user_line directly to update user_line_calls
                                if hasattr(debugger_instance, '_mock_user_line'):
                                    print("[DEBUG] Calling _mock_user_line directly")
                                    return debugger_instance._mock_user_line(frame)
                                print("[DEBUG] Calling original_user_line_func")
                                return original_user_line_func(frame)
                            return None
                except Exception as e:
                    # If we can't even get the trace manager, log and continue
                    print(f"[DEBUG] Error getting trace manager: {e}")
                    self.integration_stats["errors_handled"] += 1
                    if self.config["fallback_on_error"] and original_user_line_func:
                        print("[DEBUG] Falling back to original user_line (outer)")
                        # Call the original _mock_user_line directly to update user_line_calls
                        if hasattr(debugger_instance, '_mock_user_line'):
                            print("[DEBUG] Calling _mock_user_line directly (outer)")
                            return debugger_instance._mock_user_line(frame)
                        print("[DEBUG] Calling original_user_line_func (outer)")
                        return original_user_line_func(frame)
                    return None
            
            # Call original debugger logic
            if original_user_line_func:
                try:
                    print("[DEBUG] Calling original_user_line_func")
                    return original_user_line_func(frame)
                except Exception as e:
                    # Increment error count and re-raise if fallback is disabled
                    print(f"[DEBUG] Error in original_user_line_func: {e}")
                    self.integration_stats["errors_handled"] += 1
                    if not self.config["fallback_on_error"]:
                        raise
            print("[DEBUG] No original_user_line_func or selective_tracing is disabled")
            return None
        
        try:
            with self._lock:
                if not self.config["enabled"]:
                    return False
                
                # Store the original function in our tracking
                self.original_trace_functions[debugger_id] = original_user_line
                
                # Replace the user_line method
                debugger_instance.user_line = enhanced_user_line
                
                # Enable selective tracing with the original trace function
                if self.config["selective_tracing"]:
                    trace_func = lambda frame, event, arg: enhanced_user_line(frame) if event == "line" else None
                    enable_selective_tracing(trace_func)
                
                self.integration_stats["integrations_enabled"] += 1
                return True
                
        except Exception as e:
            # Clean up if an error occurs during integration
            if debugger_id in self.original_trace_functions:
                del self.original_trace_functions[debugger_id]
            
            if self.config["fallback_on_error"]:
                self.integration_stats["errors_handled"] += 1
                # Restore original user_line if we can
                if hasattr(debugger_instance, "user_line") and debugger_instance.user_line == enhanced_user_line:
                    debugger_instance.user_line = original_user_line
                return False
            
            raise
    
    def integrate_with_py_debugger(self, debugger_instance) -> bool:
        """
        Integrate frame evaluation with a PyDebugger instance.
        
        Args:
            debugger_instance: The PyDebugger instance to enhance
            
        Returns:
            True if integration was successful
        """
        try:
            with self._lock:
                if not self.config["enabled"]:
                    return False
                
                # Hook into breakpoint setting
                original_set_breakpoints = getattr(debugger_instance, "set_breakpoints", None)
                
                def enhanced_set_breakpoints(source, breakpoints, **kwargs):
                    """Enhanced breakpoint setting with frame evaluation optimizations."""
                    try:
                        # Call original breakpoint setting
                        result = original_set_breakpoints(source, breakpoints, **kwargs) if original_set_breakpoints else None
                        
                        # Update frame evaluation system with new breakpoints
                        if self.config["selective_tracing"]:
                            filepath = source.get("path", "")
                            if filepath:
                                breakpoint_lines = {bp.get("line", 0) for bp in breakpoints if bp.get("line")}
                                update_breakpoints(filepath, breakpoint_lines)
                                self.integration_stats["breakpoints_optimized"] += len(breakpoint_lines)
                        
                        # Apply bytecode optimizations if enabled
                        if self.config["bytecode_optimization"] and breakpoints:
                            self._apply_bytecode_optimizations(source, breakpoints)
                        
                        return result
                        
                    except Exception as e:
                        if self.config["fallback_on_error"]:
                            self.integration_stats["errors_handled"] += 1
                            return original_set_breakpoints(source, breakpoints, **kwargs) if original_set_breakpoints else None
                        raise
                
                # Replace the set_breakpoints method
                debugger_instance.set_breakpoints = enhanced_set_breakpoints
                
                # Hook into trace function setting
                original_set_trace = getattr(debugger_instance, "_set_trace_function", None)
                
                def enhanced_set_trace():
                    """Enhanced trace function setting with selective tracing."""
                    try:
                        if self.config["selective_tracing"]:
                            # Use selective tracing instead of direct sys.settrace
                            selective_trace = get_selective_trace_function()
                            if selective_trace:
                                sys.settrace(selective_trace)
                                return
                        
                        # Fallback to original behavior
                        if original_set_trace:
                            original_set_trace()
                            
                    except Exception as e:
                        if self.config["fallback_on_error"]:
                            self.integration_stats["errors_handled"] += 1
                            if original_set_trace:
                                original_set_trace()
                        else:
                            raise
                
                # Replace the trace function setter
                debugger_instance._set_trace_function = enhanced_set_trace
                
                self.integration_stats["integrations_enabled"] += 1
                return True
                
        except Exception as e:
            if self.config["fallback_on_error"]:
                self.integration_stats["errors_handled"] += 1
                return False
            raise
    
    def _apply_bytecode_optimizations(self, source: Dict[str, Any], breakpoints: List[Dict[str, Any]]) -> None:
        """Apply bytecode optimizations for breakpoints."""
        if not self.config["bytecode_optimization"]:
            return
        
        try:
            filepath = source.get("path", "")
            if not filepath or not filepath.endswith(".py"):
                return
            
            breakpoint_lines = {bp.get("line", 0) for bp in breakpoints if bp.get("line")}
            if not breakpoint_lines:
                return
            
            # Read the source file and compile it
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    source_code = f.read()
                
                # Compile the source code
                code_obj = compile(source_code, filepath, "exec")
                
                # Apply bytecode modifications
                modified_code = inject_breakpoint_bytecode(code_obj, breakpoint_lines)
                if modified_code:
                    self.integration_stats["bytecode_injections"] += 1
                    # Store the modified code object for future use
                    set_func_code_info(code_obj, {"modified_code": modified_code, "breakpoints": breakpoint_lines})
                
            except Exception:
                # If we can't read/compile the file, skip bytecode optimization
                pass
                
        except Exception:
            # Silently fail if bytecode optimization fails
            pass
    
    def remove_integration(self, debugger_instance) -> bool:
        """
        Remove frame evaluation integration from a debugger instance.
        
        Args:
            debugger_instance: The debugger instance to restore
            
        Returns:
            bool: True if removal was successful, False if debugger was not found
        """
        if debugger_instance is None:
            return False
            
        try:
            with self._lock:
                debugger_id = id(debugger_instance)
                
                # Check if debugger is in our tracking
                if debugger_id not in self.original_trace_functions:
                    return False
                    
                # Restore original user_line function for DebuggerBDB
                original_func = self.original_trace_functions[debugger_id]
                if hasattr(debugger_instance, "user_line"):
                    debugger_instance.user_line = original_func
                del self.original_trace_functions[debugger_id]
                
                # Disable selective tracing if no more integrations
                if not self.original_trace_functions:
                    disable_selective_tracing()
                
                return True
                
        except Exception:
            # If anything goes wrong during removal, consider it a failure
            return False
    
    def update_config(self, **kwargs) -> None:
        """Update integration configuration."""
        with self._lock:
            for key, value in kwargs.items():
                if key in self.config:
                    self.config[key] = value
            
            # Apply configuration changes
            if not self.config["cache_enabled"]:
                clear_all_caches()
            
            if not self.config["enabled"]:
                # Disable all integrations
                disable_selective_tracing()
    
    def get_integration_statistics(self) -> IntegrationStatistics:
        """Get comprehensive integration statistics."""
        with self._lock:
            # Get frame evaluation statistics
            trace_stats = get_trace_manager().get_statistics()
            cache_stats = get_cache_statistics()
            
            # Calculate performance metrics
            uptime = time.time() - self._performance_data["start_time"]
            
            return {
                "config": self.config.copy(),
                "integration_stats": self.integration_stats.copy(),
                "performance_data": {
                    **self._performance_data,
                    "uptime_seconds": uptime,
                    "avg_trace_calls_per_second": self._performance_data["trace_function_calls"] / max(uptime, 1),
                },
                "trace_manager_stats": trace_stats,
                "cache_stats": cache_stats,
            }
    
    def reset_statistics(self) -> None:
        """Reset all integration statistics."""
        with self._lock:
            self.integration_stats = {
                "integrations_enabled": 0,
                "breakpoints_optimized": 0,
                "trace_calls_saved": 0,
                "bytecode_injections": 0,
                "errors_handled": 0,
            }
            self._performance_data = {
                "start_time": time.time(),
                "trace_function_calls": 0,
                "frame_eval_calls": 0,
                "cache_hits": 0,
                "cache_misses": 0,
            }
    
    def enable_performance_monitoring(self, enabled: bool = True) -> None:
        """Enable or disable performance monitoring."""
        with self._lock:
            self.config["performance_monitoring"] = enabled
    
    def _monitor_trace_call(self) -> None:
        """Monitor a trace function call (for performance tracking)."""
        if self.config["performance_monitoring"]:
            self._performance_data["trace_function_calls"] += 1
    
    def _monitor_frame_eval_call(self) -> None:
        """Monitor a frame evaluation call (for performance tracking)."""
        if self.config["performance_monitoring"]:
            self._performance_data["frame_eval_calls"] += 1


# Global bridge instance
_integration_bridge = DebuggerFrameEvalBridge()


def get_integration_bridge() -> DebuggerFrameEvalBridge:
    """Get the global integration bridge instance."""
    return _integration_bridge


def integrate_debugger_bdb(debugger_instance) -> bool:
    """Integrate frame evaluation with a DebuggerBDB instance."""
    return _integration_bridge.integrate_with_debugger_bdb(debugger_instance)


def integrate_py_debugger(debugger_instance) -> bool:
    """Integrate frame evaluation with a PyDebugger instance."""
    return _integration_bridge.integrate_with_py_debugger(debugger_instance)


def remove_integration(debugger_instance) -> bool:
    """Remove frame evaluation integration from a debugger instance."""
    return _integration_bridge.remove_integration(debugger_instance)


def configure_integration(**kwargs) -> None:
    """Configure frame evaluation integration."""
    _integration_bridge.update_config(**kwargs)


def get_integration_statistics() -> IntegrationStatistics:
    """Get integration statistics."""
    return _integration_bridge.get_integration_statistics()


def auto_integrate_debugger(debugger_instance) -> bool:
    """
    Automatically detect debugger type and integrate frame evaluation.
    
    Args:
        debugger_instance: The debugger instance to enhance
        
    Returns:
        True if integration was successful, False otherwise
    """
    try:
        # Check if it's a DebuggerBDB instance
        if hasattr(debugger_instance, "breakpoints"):
            return _integration_bridge.integrate_with_debugger_bdb(debugger_instance)
        
        # Check if it's a PyDebugger instance
        elif hasattr(debugger_instance, "set_breakpoints") and hasattr(debugger_instance, "threads"):
            return _integration_bridge.integrate_with_py_debugger(debugger_instance)
        
        # Unknown debugger type
        return False
            
    except Exception:
        return False


# Monkey patch functions for automatic integration
def patch_debugger_bdb_module() -> None:
    """Monkey patch the debugger_bdb module for automatic integration."""
    try:
        import dapper.debugger_bdb
        
        original_init = dapper.debugger_bdb.DebuggerBDB.__init__
        
        def enhanced_init(self, *args, **kwargs):
            # Call original init
            original_init(self, *args, **kwargs)
            # Auto-integrate frame evaluation
            integrate_debugger_bdb(self)
        
        dapper.debugger_bdb.DebuggerBDB.__init__ = enhanced_init
        
    except Exception:
        # Silently fail if module not available
        pass


def patch_py_debugger_module() -> None:
    """Monkey patch the PyDebugger class for automatic integration."""
    try:
        import dapper.server
        
        original_init = dapper.server.PyDebugger.__init__
        
        def enhanced_init(self, *args, **kwargs):
            # Call original init
            original_init(self, *args, **kwargs)
            # Auto-integrate frame evaluation
            integrate_py_debugger(self)
        
        dapper.server.PyDebugger.__init__ = enhanced_init
        
    except Exception:
        # Silently fail if module not available
        pass


def enable_auto_integration() -> None:
    """Enable automatic integration with debugger classes."""
    patch_debugger_bdb_module()
    patch_py_debugger_module()


def disable_auto_integration() -> None:
    """Disable automatic integration (requires restart to take effect)."""
    # This would require unpatching, which is complex
    # For now, just disable the bridge
    configure_integration(enabled=False)
