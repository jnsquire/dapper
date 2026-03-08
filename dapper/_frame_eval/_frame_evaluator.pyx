"""Thin Cython wrapper for CPython-specific frame-evaluator helpers.

Runtime bookkeeping lives in ``_frame_evaluator_shared.py`` so the Cython and
pure-Python backends do not duplicate the same state classes and helpers.
"""

from cpython.ref cimport Py_INCREF, Py_DECREF
from cpython.object cimport PyObject

import contextvars
import types


cdef class ThreadInfo:
    def __cinit__(self):
        self.inside_frame_eval = <Py_ssize_t>0
        self.fully_initialized = <bint>True
        self.is_debugger_internal_thread = <bint>False
        self.thread_trace_func = None
        self.additional_info = None
        self.recursion_depth = <Py_ssize_t>0
        self.skip_all_frames = <bint>False
        self.step_mode = <bint>False

    def enter_frame_eval(self):
        self.inside_frame_eval += 1
        self.recursion_depth += 1

    def exit_frame_eval(self):
        if self.inside_frame_eval > 0:
            self.inside_frame_eval -= 1
        if self.recursion_depth > 0:
            self.recursion_depth -= 1

    def should_skip_frame(self, frame_obj):
        del frame_obj
        return self.skip_all_frames


cdef class FuncCodeInfo:
    def __cinit__(self):
        self.co_filename = b""
        self.real_path = ""
        self.always_skip_code = <bint>False
        self.breakpoint_found = <bint>False
        self.new_code = None
        self.breakpoints_mtime = <double>0.0
        self.breakpoint_lines = set()
        self.last_check_time = <double>0.0
        self.is_valid = <bint>True

    def update_breakpoint_info(self, code_obj):
        self.co_filename = code_obj.co_filename.encode("utf-8", errors="ignore")
        self.real_path = code_obj.co_filename
        self.always_skip_code = <bint>(not bool(self.breakpoint_lines))


class _FrameEvalModuleState:
    def __init__(self) -> None:
        self.active = False
        self.hook_available = True
        self.hook_installed = False
        self.hook_error = None
        self._unset = object()
        self.thread_info_var = contextvars.ContextVar("thread_info", default=self._unset)

    def enable(self) -> None:
        self.active = True

    def disable(self) -> None:
        self.active = False

    def install_hook(self) -> bool:
        """Activate the low-level eval-frame hook controller.

        This slice only manages the lifecycle surface and status tracking.
        Actual CPython eval-frame registration will replace this controller in a
        later implementation step.
        """
        self.hook_error = None
        self.hook_installed = True
        return True

    def uninstall_hook(self) -> bool:
        """Deactivate the low-level eval-frame hook controller."""
        self.hook_error = None
        self.hook_installed = False
        return True

    def get_hook_status(self) -> dict[str, object]:
        return {
            "available": self.hook_available,
            "installed": self.hook_installed,
            "error": self.hook_error,
        }

    def get_thread_info(self) -> ThreadInfo:
        thread_info = self.thread_info_var.get()
        if thread_info is self._unset:
            thread_info = ThreadInfo()
            self.thread_info_var.set(thread_info)
        return <ThreadInfo>thread_info

    def clear_thread_local_info(self) -> None:
        self.thread_info_var.set(self._unset)

    def get_stats(self) -> dict[str, object]:
        return {
            "active": self.active,
            "has_breakpoint_manager": False,
            "frames_evaluated": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "evaluation_time": 0.0,
            "is_active": self.active,
            "hook_available": self.hook_available,
            "hook_installed": self.hook_installed,
            "hook_error": self.hook_error,
        }


_state = _FrameEvalModuleState()


def install_eval_frame_hook() -> bool:
    """Install the low-level eval-frame hook controller."""
    return _state.install_hook()


def uninstall_eval_frame_hook() -> bool:
    """Uninstall the low-level eval-frame hook controller."""
    return _state.uninstall_hook()


def get_eval_frame_hook_status() -> dict[str, object]:
    """Return low-level eval-frame hook status information."""
    return _state.get_hook_status()


cpdef FuncCodeInfo get_func_code_info(frame_obj, code_obj):
    del frame_obj
    cdef FuncCodeInfo info = FuncCodeInfo()
    info.update_breakpoint_info(code_obj)
    return info


cpdef dummy_trace_dispatch(frame, str event, arg):
    del frame, event, arg
    return None


cdef bint should_trace_frame(frame_obj) except -1:
    """
    Determine if a frame should be traced based on breakpoints.
    
    This function does the main decision making for whether frame evaluation
    should intervene for a specific frame.
    """
    cdef ThreadInfo thread_info
    cdef FuncCodeInfo func_code_info
    
    # Get thread info
    thread_info = <ThreadInfo>_state.get_thread_info()
    if thread_info.inside_frame_eval > 0:
        return <bint>False
    
    # Skip if thread is not fully initialized
    if not thread_info.fully_initialized:
        return <bint>False
    
    # Skip debugger-owned helper threads.
    if thread_info.is_debugger_internal_thread:
        return <bint>False
    
    # Check if frame should be skipped based on content
    if thread_info.should_skip_frame(frame_obj):
        return <bint>False
    
    # Get code info and check if we need debugging
    func_code_info = get_func_code_info(frame_obj, frame_obj.f_code)
    
    # Return True if we have breakpoints in this code
    return <bint>func_code_info.breakpoint_found


cdef PyObject *get_bytecode_while_frame_eval(frame_obj, int exc):
    """
    Main frame evaluation hook.
    
    This function is called by Python's frame evaluation mechanism and
    determines whether to use the default evaluation or inject debugging logic.
    """
    cdef ThreadInfo thread_info
    cdef FuncCodeInfo func_code_info
    cdef PyObject *result
    
    # Get thread info
    thread_info = <ThreadInfo>_state.get_thread_info()
    thread_info.enter_frame_eval()
    
    try:
        # Check if we should trace this frame
        if not should_trace_frame(frame_obj):
            # Use default evaluation for frames without breakpoints
            # For now, return NULL to use default evaluation
            result = NULL
            return result
        
        # Get code info
        func_code_info = get_func_code_info(frame_obj, frame_obj.f_code)
        
        # Use default evaluation (with potentially modified code)
        # For now, return NULL to use default evaluation
        result = NULL
        return result
        
    except:
        # On any exception, fall back to default evaluation
        result = NULL
        return result
    finally:
        # Always exit frame evaluation context
        thread_info.exit_frame_eval()


# _PyEval_RequestCodeExtraIndex, _PyCode_SetExtra, and _PyCode_GetExtra were all
# deprecated in Python 3.12 in favour of PyUnstable_Eval_RequestCodeExtraIndex,
# PyUnstable_Code_SetExtra, and PyUnstable_Code_GetExtra respectively.  Use the
# new names on 3.12+ so the build is warning-free; fall back to the old names on
# earlier versions.
cdef extern from "Python.h":
    ctypedef void (*freefunc)(void *)

cdef extern from *:
    """
    #if PY_VERSION_HEX >= 0x030c0000
    #  define _dapper_RequestCodeExtraIndex PyUnstable_Eval_RequestCodeExtraIndex
    #  define _dapper_Code_GetExtra         PyUnstable_Code_GetExtra
    #  define _dapper_Code_SetExtra         PyUnstable_Code_SetExtra
    #else
    #  define _dapper_RequestCodeExtraIndex _PyEval_RequestCodeExtraIndex
    #  define _dapper_Code_GetExtra         _PyCode_GetExtra
    #  define _dapper_Code_SetExtra         _PyCode_SetExtra
    #endif
    """
    Py_ssize_t _dapper_RequestCodeExtraIndex_C "_dapper_RequestCodeExtraIndex"(freefunc)
    int _PyCode_SetExtra_C "_dapper_Code_SetExtra"(object code, Py_ssize_t index, void *extra)
    int _PyCode_GetExtra_C "_dapper_Code_GetExtra"(object code, Py_ssize_t index, void **extra)

# Cleanup function for code extra data
cdef void _cleanup_code_extra(void *obj) noexcept:
    if obj:
        Py_DECREF(<object>obj)

def _PyEval_RequestCodeExtraIndex():
    """Request a new code extra index with our cleanup function."""
    return _dapper_RequestCodeExtraIndex_C(_cleanup_code_extra)

def _PyCode_SetExtra(object code, Py_ssize_t index, object extra):
    """Set extra data on code object.

    Raise TypeError if the provided `code` is not a Python code object. This
    provides a clearer error for incorrect usage instead of allowing the
    underlying C API to raise a SystemError or other low-level exception.
    """
    if not isinstance(code, types.CodeType):
        raise TypeError("code argument must be a code object")

    if extra is not None:
        # Ensure the passed object has its refcount incremented so the code
        # object takes ownership of a new reference. This prevents the value
        # from being collected unexpectedly and avoids use-after-free.
        Py_INCREF(extra)
        return _PyCode_SetExtra_C(code, index, <void*>extra)
    else:
        return _PyCode_SetExtra_C(code, index, <void*>NULL)

def _PyCode_GetExtra(object code, Py_ssize_t index):
    """Get extra data from code object."""
    # Validate code object input to provide a clear error when misused
    if not isinstance(code, types.CodeType):
        raise TypeError("code argument must be a code object")

    cdef void *extra = NULL
    cdef int res
    
    res = _PyCode_GetExtra_C(code, index, &extra)
    
    if res < 0 or not extra:
        return None
        
    # The C API provides a borrowed pointer to the stored object. To return
    # a safe Python-level object we must increment its refcount so the
    # caller receives an owned reference and the object can't be freed
    # unexpectedly (which could lead to use-after-free / segfaults).
    py_obj = <object>extra
    Py_INCREF(py_obj)
    return py_obj


__all__ = [
    "FuncCodeInfo",
    "ThreadInfo",
    "_FrameEvalModuleState",
    "_PyCode_GetExtra",
    "_PyCode_SetExtra",
    "_PyEval_RequestCodeExtraIndex",
    "_state",
    "dummy_trace_dispatch",
    "get_eval_frame_hook_status",
    "get_func_code_info",
    "install_eval_frame_hook",
    "uninstall_eval_frame_hook",
]
