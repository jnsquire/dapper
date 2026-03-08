"""
Cython definition file for frame evaluator.

This file declares the public API that can be imported from other Cython modules.
"""

# Standard Cython types
cdef extern from *:
    ctypedef struct PyFrameObject:
        pass
    ctypedef struct PyCodeObject:
        pass

# Class declarations
cdef class ThreadInfo:
    cdef public Py_ssize_t inside_frame_eval
    cdef public bint fully_initialized
    cdef public bint is_debugger_internal_thread
    cdef public object thread_trace_func
    cdef public object additional_info
    cdef public Py_ssize_t recursion_depth
    cdef public bint skip_all_frames
    cdef public bint step_mode

cdef class FuncCodeInfo:
    cdef public bytes co_filename
    cdef public str real_path
    cdef public bint always_skip_code
    cdef public bint breakpoint_found
    cdef public object new_code
    cdef public double breakpoints_mtime
    cdef public set breakpoint_lines
    cdef public double last_check_time
    cdef public bint is_valid

# Function declarations

cpdef FuncCodeInfo get_func_code_info(frame_obj, code_obj)
cpdef dummy_trace_dispatch(frame, str event, arg)
