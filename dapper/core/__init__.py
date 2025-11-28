"""
dapper.core - Core debugger implementation.

This module provides the core debugging functionality built on Python's bdb module.
"""

from dapper.core.breakpoint_resolver import BreakpointMeta
from dapper.core.breakpoint_resolver import BreakpointResolver
from dapper.core.breakpoint_resolver import ResolveAction
from dapper.core.breakpoint_resolver import ResolveResult
from dapper.core.breakpoint_resolver import get_resolver
from dapper.core.breakpoints_controller import BreakpointController
from dapper.core.breakpoints_controller import DataBreakpointSpec
from dapper.core.breakpoints_controller import FunctionBreakpointSpec
from dapper.core.breakpoints_controller import LineBreakpointSpec
from dapper.core.data_breakpoint_state import DataBreakpointState
from dapper.core.debugger_bdb import DebuggerBDB
from dapper.core.inprocess_debugger import InProcessDebugger
from dapper.core.thread_tracker import StackFrame
from dapper.core.thread_tracker import ThreadTracker
from dapper.core.variable_manager import VariableManager

__all__ = [
    # Breakpoint controller
    "BreakpointController",
    # Breakpoint resolver
    "BreakpointMeta",
    "BreakpointResolver",
    # Data breakpoint state
    "DataBreakpointSpec",
    "DataBreakpointState",
    # Debugger implementations
    "DebuggerBDB",
    "FunctionBreakpointSpec",
    "InProcessDebugger",
    "LineBreakpointSpec",
    "ResolveAction",
    "ResolveResult",
    # Thread/frame tracking
    "StackFrame",
    "ThreadTracker",
    # Variable management
    "VariableManager",
    "get_resolver",
]
