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
    cdef public bint is_pydevd_thread
    cdef public object thread_trace_func
    cdef public object additional_info
    cdef public Py_ssize_t recursion_depth
    cdef public bint skip_all_frames
    
    cdef void enter_frame_eval(self)
    cdef void exit_frame_eval(self)
    cdef bint should_skip_frame(self, frame_obj)

cdef class FuncCodeInfo:
    cdef public bytes co_filename
    cdef public str real_path
    cdef public bint always_skip_code
    cdef public bint breakpoint_found
    cdef public object new_code
    cdef public Py_ssize_t breakpoints_mtime
    cdef public set breakpoint_lines
    cdef public Py_ssize_t last_check_time
    cdef public bint is_valid
    
    cdef void update_breakpoint_info(self, code_obj)

# Function declarations
cpdef ThreadInfo get_thread_info()
cpdef FuncCodeInfo get_func_code_info(frame_obj, code_obj)
cpdef frame_eval_func()
cpdef stop_frame_eval()
cpdef dummy_trace_dispatch(frame, str event, arg)
cpdef clear_thread_local_info()
cpdef get_frame_eval_stats()
cpdef mark_thread_as_pydevd()
cpdef unmark_thread_as_pydevd()
cpdef set_thread_skip_all(bint skip)
