"""
Cython wrapper module providing Python-accessible API for frame evaluation.

This module acts as an interface between the pure Python Dapper code
and the Cython frame evaluation implementation.
"""

# Import the core Cython implementation
from dapper._frame_eval._frame_evaluator cimport (
    frame_eval_func,
    stop_frame_eval,
    dummy_trace_dispatch,
    clear_thread_local_info,
    get_frame_eval_stats,
    mark_thread_as_pydevd,
    unmark_thread_as_pydevd,
    set_thread_skip_all,
    ThreadInfo,
    FuncCodeInfo,
    get_thread_info,
    get_func_code_info,
)

# Re-export functions for Python access
__all__ = [
    'frame_eval_func',
    'stop_frame_eval', 
    'dummy_trace_dispatch',
    'clear_thread_local_info',
    'get_frame_eval_stats',
    'mark_thread_as_pydevd',
    'unmark_thread_as_pydevd',
    'set_thread_skip_all',
    'ThreadInfo',
    'FuncCodeInfo',
    'get_thread_info',
    'get_func_code_info',
]
