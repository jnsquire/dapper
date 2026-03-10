"""Thin Cython wrapper for CPython-specific frame-evaluator helpers.

Runtime bookkeeping lives in ``_frame_evaluator_shared.py`` so the Cython and
pure-Python backends do not duplicate the same state classes and helpers.
"""

from cpython.ref cimport Py_INCREF, Py_DECREF
from cpython.object cimport PyObject
from cpython.exc cimport PyErr_Fetch, PyErr_NormalizeException, PyErr_Restore

import contextvars
import os
import sys
import types
from typing import Any as TypingAny
from typing import cast

from dapper._frame_eval.cache_manager import get_breakpoints as _get_breakpoints
from dapper._frame_eval.telemetry import telemetry

# keep in sync with modify_bytecode.py
_BYTECODE_META_VERSION = 1


# Keep the backend itself free of Python-minor branching, but include the
# compatibility declarations via .pxi because the VS Code Cython extension does
# not reliably resolve local .pxd cimports in this repo even when the build
# does. The matching .pxd remains the shared declaration surface for future
# Cython consumers.
include "./cpython_compat.pxi"

cdef bint _should_trace_code_for_eval_frame_impl(
    ThreadInfo thread_info,
    code_obj,
    int lineno,
    object frame_obj,
    bint allow_current_eval_frame,
) except -1:
    cdef FuncCodeInfo func_code_info
    cdef object decision

    try:
        # ask the shared tracer for a decision; this call can raise if the
        # tracer module isn't available (e.g. during early startup), hence the
        # outer try/except.
        from dapper._frame_eval.selective_tracer import should_trace_code_location

        decision = should_trace_code_location(
            code_obj,
            lineno,
            cast(TypingAny, frame_obj),
            allow_current_eval_frame=bool(allow_current_eval_frame),
        )

        if bool(decision.get("path") == "breakpointed"):
            # lazy instrumentation: if we don't already have a modified variant,
            # try to produce one now.  This step is cheap when the cache hits.
            bp_lines = decision.get("breakpoint_lines") or set()
            if bp_lines:
                # attempt to retrieve existing code first
                existing = _get_modified_code_for_evaluation(code_obj)
                if existing is None:
                    try:
                        from dapper._frame_eval.modify_bytecode import inject_breakpoint_bytecode
                        from dapper._frame_eval.telemetry import telemetry

                        success, new_code = inject_breakpoint_bytecode(code_obj, bp_lines)
                        if success and new_code is not code_obj:
                            _store_modified_code_for_evaluation(code_obj, new_code, bp_lines)
                        else:
                            getattr(telemetry, "record_modified_code_unavailable")(
                                filename=getattr(code_obj, "co_filename", "unknown"),
                                name=getattr(code_obj, "co_name", "unknown"),
                                breakpoint_lines=sorted(bp_lines),
                                cause="no_modified_code_generated",
                                success=bool(success),
                            )
                    except Exception as exc:
                        from dapper._frame_eval.telemetry import telemetry

                        getattr(telemetry, "record_modified_code_unavailable")(
                            filename=getattr(code_obj, "co_filename", "unknown"),
                            name=getattr(code_obj, "co_name", "unknown"),
                            breakpoint_lines=sorted(bp_lines),
                            cause="inject_exception",
                            error_type=type(exc).__name__,
                        )
                        # swallow errors; we will simply fallback to tracing later
                        pass
            return <bint>True
        return <bint>False
    except Exception:
        pass

    if not allow_current_eval_frame and thread_info.inside_frame_eval > 0:
        return <bint>False
    if not thread_info.fully_initialized:
        return <bint>False
    if thread_info.is_debugger_internal_thread:
        return <bint>False
    if thread_info.skip_all_frames:
        return <bint>False

    func_code_info = get_func_code_info(None, code_obj)
    if lineno in func_code_info.breakpoint_lines:
        return <bint>True

    return <bint>(func_code_info.breakpoint_found and thread_info.step_mode)


cdef class ThreadInfo:
    def __cinit__(self):
        self.inside_frame_eval = <long>0
        self.fully_initialized = <bint>True
        self.is_debugger_internal_thread = <bint>False
        self.thread_trace_func = None
        self.additional_info = None
        self.recursion_depth = <long>0
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


def _collect_code_lines(code_obj):
    """Collect executable source lines for a code object."""
    try:
        return {
            line
            for _, _, line in code_obj.co_lines()
            if line is not None
        }
    except Exception:
        return {code_obj.co_firstlineno}


def _should_trace_code_for_eval_frame(code_obj, lineno: int) -> bool:
    """Return whether eval-frame should take the slow path for this code/line."""
    cdef ThreadInfo thread_info = <ThreadInfo>_state.get_thread_info()
    return bool(
        _should_trace_code_for_eval_frame_impl(
            thread_info,
            code_obj,
            lineno,
            None,
            <bint>False,
        )
    )


def _should_trace_code_for_eval_frame_with_frame(code_obj, lineno: int, frame_obj=None) -> bool:
    """Return whether eval-frame should take the slow path for this code/line."""
    cdef ThreadInfo thread_info = <ThreadInfo>_state.get_thread_info()
    return bool(
        _should_trace_code_for_eval_frame_impl(
            thread_info,
            code_obj,
            lineno,
            frame_obj,
            <bint>False,
        )
    )


def _set_thread_trace_func(trace_func) -> None:
    """Store the active trace callback for the current thread."""
    cdef ThreadInfo thread_info = <ThreadInfo>_state.get_thread_info()
    thread_info.thread_trace_func = trace_func


def _clear_thread_trace_func() -> None:
    """Clear the active trace callback for the current thread."""
    cdef ThreadInfo thread_info = <ThreadInfo>_state.get_thread_info()
    thread_info.thread_trace_func = None


def _make_eval_frame_trace_func(code_obj, root_trace_func):
    """Return a temporary global trace function scoped to one code object."""

    def wrap_trace_callback(trace_func):
        if trace_func is None:
            return None

        def wrapped_trace(frame, event, arg):
            cdef object next_trace

            if getattr(frame, "f_code", None) is not code_obj:
                return None
            if event == "return":
                _state.record_return_event()
            elif event == "exception":
                _state.record_exception_event()
            next_trace = trace_func(frame, event, arg)
            return wrap_trace_callback(next_trace)

        return wrapped_trace

    def eval_frame_trace(frame, event, arg):
        if getattr(frame, "f_code", None) is not code_obj:
            return None
        return wrap_trace_callback(root_trace_func(frame, event, arg))

    return eval_frame_trace


cdef bint _dispatch_trace_callback_impl(frame_obj, str event="line", arg=None) except -1:
    """Dispatch the active trace callback for *frame_obj*.

    Per-frame callbacks live on ``frame_obj.f_trace``. The thread-local
    ``thread_trace_func`` remains the root callback used when a frame has not
    installed its own local trace function yet.
    """
    cdef ThreadInfo thread_info = <ThreadInfo>_state.get_thread_info()
    cdef object trace_func = getattr(frame_obj, "f_trace", None)
    cdef object next_trace_func
    cdef bint was_debugger_internal

    if trace_func is None:
        trace_func = thread_info.thread_trace_func

    if trace_func is None:
        return <bint>False

    was_debugger_internal = thread_info.is_debugger_internal_thread
    thread_info.is_debugger_internal_thread = <bint>True
    try:
        next_trace_func = getattr(trace_func, "__call__")(frame_obj, event, arg)
    finally:
        thread_info.is_debugger_internal_thread = was_debugger_internal

    frame_obj.f_trace = next_trace_func
    return <bint>True


def _dispatch_trace_callback(frame_obj, str event="line", arg=None) -> bool:
    return bool(_dispatch_trace_callback_impl(frame_obj, event, arg))


cdef bint _dispatch_eval_frame_entry_trace_impl(frame_obj) except -1:
    """Dispatch synthetic entry events for an eval-frame materialized frame."""
    cdef object local_trace = getattr(frame_obj, "f_trace", None)

    if local_trace is None:
        if not _dispatch_trace_callback_impl(frame_obj, "call", None):
            return <bint>False
        if getattr(frame_obj, "f_trace", None) is None:
            return <bint>True

    return _dispatch_trace_callback_impl(frame_obj, "line", None)


def _dispatch_eval_frame_entry_trace(frame_obj) -> bool:
    return bool(_dispatch_eval_frame_entry_trace_impl(frame_obj))


cdef bint _dispatch_eval_frame_return_trace_impl(frame_obj, arg=None) except -1:
    """Dispatch a synthetic return event for an eval-frame materialized frame."""
    if getattr(frame_obj, "f_trace", None) is None:
        return <bint>False
    return _dispatch_trace_callback_impl(frame_obj, "return", arg)


def _dispatch_eval_frame_return_trace(frame_obj, arg=None) -> bool:
    return bool(_dispatch_eval_frame_return_trace_impl(frame_obj, arg))


class _FrameEvalModuleState:
    def __init__(self) -> None:
        self.active = False
        self.hook_available = False
        self.hook_capabilities = {}
        self.hook_installed = False
        self.hook_error = None
        self.hook_reason = None
        self._unset = object()
        self.thread_info_var = contextvars.ContextVar("thread_info", default=self._unset)
        self.slow_path_attempts = 0
        self.slow_path_activations = 0
        self.scoped_trace_installs = 0
        self.return_events = 0
        self.exception_events = 0

    def enable(self) -> None:
        self.active = True

    def disable(self) -> None:
        self.active = False

    def configure_hook_capabilities(self, capabilities) -> None:
        self.hook_capabilities = dict(capabilities)
        self.hook_available = bool(capabilities.get("supports_eval_frame_hook", False))
        reason = capabilities.get("reason")
        self.hook_reason = reason if isinstance(reason, str) and reason else None
        if not self.hook_available:
            self.hook_installed = False

    def install_hook(self) -> bool:
        """Activate the low-level eval-frame hook controller.

        This slice only manages the lifecycle surface and status tracking.
        Actual CPython eval-frame registration will replace this controller in a
        later implementation step.
        """
        if not self.hook_available:
            self.hook_error = self.hook_reason or "Eval-frame hook API not available in this runtime"
            self.hook_installed = False
            return False
        self.hook_error = None
        self.hook_installed = True
        return True

    def uninstall_hook(self) -> bool:
        """Deactivate the low-level eval-frame hook controller."""
        if not self.hook_available:
            self.hook_error = self.hook_reason or "Eval-frame hook API not available in this runtime"
            self.hook_installed = False
            return False
        self.hook_error = None
        self.hook_installed = False
        return True

    def get_hook_status(self) -> dict[str, object]:
        return {
            "available": self.hook_available,
            "capabilities": dict(self.hook_capabilities),
            "reason": self.hook_reason,
            "installed": self.hook_installed,
            "error": self.hook_error or self.hook_reason,
        }

    def get_thread_info(self) -> ThreadInfo:
        thread_info = self.thread_info_var.get()
        if thread_info is self._unset:
            thread_info = ThreadInfo()
            self.thread_info_var.set(thread_info)
        return <ThreadInfo>thread_info

    def clear_thread_local_info(self) -> None:
        self.thread_info_var.set(self._unset)

    def record_slow_path_attempt(self, activated: bool, scoped_trace_installed: bool) -> None:
        self.slow_path_attempts += 1
        if activated:
            self.slow_path_activations += 1
        if scoped_trace_installed:
            self.scoped_trace_installs += 1

    def record_return_event(self) -> None:
        self.return_events += 1

    def record_exception_event(self) -> None:
        self.exception_events += 1

    def get_stats(self) -> dict[str, object]:
        return {
            "active": self.active,
            "has_breakpoint_manager": False,
            "frames_evaluated": self.slow_path_activations,
            "cache_hits": 0,
            "cache_misses": 0,
            "evaluation_time": 0.0,
            "is_active": self.active,
            "hook_available": self.hook_available,
            "hook_installed": self.hook_installed,
            "hook_reason": self.hook_reason,
            "hook_error": self.hook_error,
            "slow_path_attempts": self.slow_path_attempts,
            "slow_path_activations": self.slow_path_activations,
            "scoped_trace_installs": self.scoped_trace_installs,
            "return_events": self.return_events,
            "exception_events": self.exception_events,
        }


_state = _FrameEvalModuleState()

# store the previous eval_frame pointer so we can restore it on uninstall
cdef _PyFrameEvalFunction _old_eval_frame
cdef bint _eval_frame_hook_installed
cdef object _code_extra_index

# initialize pointer to NULL at module load
_old_eval_frame = NULL
_eval_frame_hook_installed = <bint>False
_code_extra_index = -2


def get_frame_eval_capabilities() -> dict[str, object]:
    """Report the low-level eval-frame capability surface for this runtime."""
    cdef tuple version_tuple = sys.version_info[:2]
    supports_eval_frame_hook = version_tuple in ((3, 11), (3, 12))
    supports_frame_code_access = version_tuple >= (3, 11)
    supports_frame_line_access = version_tuple >= (3, 11)
    supports_frame_object_extraction = version_tuple >= (3, 11)
    cdef object reason = None

    if not supports_eval_frame_hook:
        reason = (
            f"Eval-frame hook support is currently implemented only for CPython 3.11-3.12 "
            f"(running {sys.version_info.major}.{sys.version_info.minor})"
        )

    return {
        "supports_eval_frame_hook": bool(supports_eval_frame_hook),
        "supports_frame_code_access": bool(supports_frame_code_access),
        "supports_frame_line_access": bool(supports_frame_line_access),
        "supports_frame_object_extraction": bool(supports_frame_object_extraction),
        "reason": reason,
    }


cdef object _initial_hook_capabilities


def _initialize_hook_capabilities() -> dict[str, object]:
    capabilities = get_frame_eval_capabilities()
    cast(TypingAny, _state).configure_hook_capabilities(capabilities)
    return capabilities

_initial_hook_capabilities = _initialize_hook_capabilities()


def install_eval_frame_hook() -> bool:
    """Install the low-level eval-frame hook controller.

    This implementation actually registers ``get_bytecode_while_frame_eval``
    as the interpreter's frame evaluation function.  The previous value is
    saved in ``_old_eval_frame`` so that ``uninstall_eval_frame_hook`` can
    restore it later.  The hook function itself still returns ``NULL`` which
    causes default evaluation; bytecode-selection logic will be added in a
    later phase.
    """
    # attempt to register the real hook at the C level
    cdef PyInterpreterState *interp
    try:
        global _old_eval_frame, _eval_frame_hook_installed
        if _eval_frame_hook_installed:
            return _state.install_hook()
        interp = _dapper_GetInterpreterState_C()
        _old_eval_frame = _dapper_GetEvalFrameFunc_C(interp)
        _dapper_SetEvalFrameFunc_C(interp, get_bytecode_while_frame_eval)
        _eval_frame_hook_installed = <bint>True
    except Exception:
        # fall back to no-op controller
        pass
    return _state.install_hook()


def uninstall_eval_frame_hook() -> bool:
    """Uninstall the low-level eval-frame hook controller.

    The interpreter's original ``eval_frame`` function is restored if we
    previously saved it during install.  The state tracker is also notified
    so Python-level consumers see the updated status.
    """
    cdef PyInterpreterState *interp
    try:
        global _old_eval_frame, _eval_frame_hook_installed
        if _eval_frame_hook_installed:
            interp = _dapper_GetInterpreterState_C()
            _dapper_SetEvalFrameFunc_C(interp, _old_eval_frame)
            _old_eval_frame = NULL
            _eval_frame_hook_installed = <bint>False
    except Exception:
        pass
    return _state.uninstall_hook()


def get_eval_frame_hook_status() -> dict[str, object]:
    """Return low-level eval-frame hook status information."""
    return _state.get_hook_status()


cpdef unsigned long _get_current_eval_frame_address():
    """Return the raw pointer value currently stored as ``eval_frame``.

    This helper is intended for testing and diagnostics; it allows Python
    tests to verify that ``install_eval_frame_hook`` actually modified the
    interpreter state.  A return value of ``0`` means there is no function set
    or the state could not be determined.
    """
    cdef PyInterpreterState *interp
    cdef void *addr
    try:
        interp = _dapper_GetInterpreterState_C()
        addr = <void *>_dapper_GetEvalFrameFunc_C(interp)
        return <unsigned long>addr
    except Exception:
        return <unsigned long>0


cpdef FuncCodeInfo get_func_code_info(frame_obj, code_obj):
    del frame_obj
    cdef FuncCodeInfo info = FuncCodeInfo()
    cdef object file_breakpoints
    cdef object code_lines

    info.update_breakpoint_info(code_obj)
    if isinstance(code_obj, types.CodeType):
        info.new_code = _get_modified_code_for_evaluation(code_obj)
    file_breakpoints = _get_breakpoints(code_obj.co_filename)
    if file_breakpoints:
        code_lines = _collect_code_lines(code_obj)
        info.breakpoint_lines = set(file_breakpoints).intersection(code_lines)
        info.breakpoint_found = <bint>bool(info.breakpoint_lines)
        info.always_skip_code = <bint>(not info.breakpoint_found)
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


cdef PyObject *get_bytecode_while_frame_eval(
    PyThreadState *tstate,
    _PyInterpreterFrame *frame,
    int exc,
) noexcept:
    """
    Main frame evaluation hook.

    This function is called by Python's frame evaluation mechanism and
    currently delegates back to the previously installed evaluator. The
    breakpoint-aware interception logic will be added in a later phase.
    """
    cdef _PyFrameEvalFunction fallback_eval
    cdef ThreadInfo thread_info
    cdef object code_obj
    cdef object frame_obj = None
    cdef object result_value = None
    cdef object previous_trace = None
    cdef object exception_arg = None
    cdef object scoped_trace_func = None
    cdef PyObject *result_obj
    cdef PyObject *exc_type = NULL
    cdef PyObject *exc_value = NULL
    cdef PyObject *exc_tb = NULL
    cdef PyFrameObject *frame_obj_ptr = NULL
    cdef long return_events_before = <long>-1
    cdef int lineno
    cdef bint trace_installed = <bint>False
    cdef bint restore_exception = <bint>False

    fallback_eval = _old_eval_frame
    if fallback_eval is NULL:
        fallback_eval = _PyEval_EvalFrameDefault

    thread_info = <ThreadInfo>_state.get_thread_info()
    if thread_info.inside_frame_eval > 0:
        return fallback_eval(tstate, frame, exc)

    thread_info.enter_frame_eval()
    try:
        code_obj = _dapper_InterpreterFrame_GetCode_C(frame)
        lineno = _dapper_InterpreterFrame_GetLine_C(frame)

        frame_obj_ptr = _dapper_InterpreterFrame_GetFrameObject_C(frame)
        if frame_obj_ptr:
            frame_obj = <object>frame_obj_ptr

        if not _should_trace_code_for_eval_frame_impl(
            thread_info,
            code_obj,
            lineno,
            frame_obj,
            <bint>True,
        ):
            return fallback_eval(tstate, frame, exc)

        _state.record_slow_path_attempt(True, thread_info.thread_trace_func is not None)

        if thread_info.thread_trace_func is not None:
            previous_trace = sys.gettrace()
            scoped_trace_func = _make_eval_frame_trace_func(code_obj, thread_info.thread_trace_func)
            return_events_before = <long>_state.return_events
            sys.settrace(scoped_trace_func)
            trace_installed = <bint>True

        result_obj = _PyEval_EvalFrameDefault(tstate, frame, exc)
        if not result_obj:
            PyErr_Fetch(&exc_type, &exc_value, &exc_tb)
            PyErr_NormalizeException(&exc_type, &exc_value, &exc_tb)
            restore_exception = <bint>True

            if trace_installed:
                frame_obj_ptr = _dapper_InterpreterFrame_GetFrameObject_C(frame)
                if frame_obj_ptr:
                    frame_obj = <object>frame_obj_ptr
            if frame_obj is not None and getattr(frame_obj, "f_trace", None) is not None:
                exception_arg = (
                    <object>exc_type if exc_type else None,
                    <object>exc_value if exc_value else None,
                    <object>exc_tb if exc_tb else None,
                )
                _dispatch_trace_callback_impl(frame_obj, "exception", exception_arg)
            return result_obj

        if trace_installed:
            frame_obj_ptr = _dapper_InterpreterFrame_GetFrameObject_C(frame)
            if frame_obj_ptr:
                frame_obj = <object>frame_obj_ptr
        if frame_obj is not None and result_obj:
            result_value = <object>result_obj
            if (
                getattr(frame_obj, "f_trace", None) is not None
                and (not trace_installed or <long>_state.return_events == return_events_before)
            ):
                _dispatch_eval_frame_return_trace_impl(frame_obj, result_value)

        return result_obj
    except Exception:
        return fallback_eval(tstate, frame, exc)
    finally:
        if trace_installed:
            sys.settrace(previous_trace)
        thread_info.exit_frame_eval()
        if restore_exception:
            PyErr_Restore(exc_type, exc_value, exc_tb)


# _PyEval_RequestCodeExtraIndex, _PyCode_SetExtra, and _PyCode_GetExtra were all
# deprecated in Python 3.12 in favour of PyUnstable_Eval_RequestCodeExtraIndex,
# PyUnstable_Code_SetExtra, and PyUnstable_Code_GetExtra respectively. Keep the
# version-dependent symbol mapping in cpython_compat.pxd so the rest of this
# module can stay focused on eval-frame behavior.

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
        return _dapper_Code_SetExtra_C(code, index, <void*>extra)
    else:
        return _dapper_Code_SetExtra_C(code, index, <void*>NULL)

def _PyCode_GetExtra(object code, Py_ssize_t index):
    """Get extra data from code object."""
    # Validate code object input to provide a clear error when misused
    if not isinstance(code, types.CodeType):
        raise TypeError("code argument must be a code object")

    cdef void *extra = NULL
    cdef int res
    
    res = _dapper_Code_GetExtra_C(code, index, &extra)
    
    if res < 0 or not extra:
        return None
        
    # The C API provides a borrowed pointer to the stored object. To return
    # a safe Python-level object we must increment its refcount so the
    # caller receives an owned reference and the object can't be freed
    # unexpectedly (which could lead to use-after-free / segfaults).
    py_obj = <object>extra
    Py_INCREF(py_obj)
    return py_obj


cdef bint _ensure_code_extra_index() except -1:
    global _code_extra_index
    cdef int code_extra_index

    code_extra_index = int(cast(TypingAny, _code_extra_index))
    if code_extra_index >= -1:
        return <bint>(code_extra_index >= 0)

    try:
        _code_extra_index = _dapper_RequestCodeExtraIndex_C(_cleanup_code_extra)
    except Exception:
        _code_extra_index = -1

    return <bint>(int(cast(TypingAny, _code_extra_index)) >= 0)


def _get_code_extra_metadata(object code):
    """Get eval-frame metadata stored directly on a code object."""
    cdef Py_ssize_t code_extra_index

    if not isinstance(code, types.CodeType):
        raise TypeError("code argument must be a code object")
    if not _ensure_code_extra_index():
        return None
    code_extra_index = <Py_ssize_t>_code_extra_index
    return _PyCode_GetExtra(code, code_extra_index)


def _store_code_extra_metadata(object code, object metadata) -> bool:
    """Store eval-frame metadata directly on a code object."""
    cdef Py_ssize_t code_extra_index

    if not isinstance(code, types.CodeType):
        raise TypeError("code argument must be a code object")
    if not _ensure_code_extra_index():
        return False
    code_extra_index = <Py_ssize_t>_code_extra_index
    return _PyCode_SetExtra(code, code_extra_index, metadata) == 0


def _clear_code_extra_metadata(object code) -> bool:
    """Remove eval-frame metadata from a code object."""
    cdef Py_ssize_t code_extra_index

    if not isinstance(code, types.CodeType):
        raise TypeError("code argument must be a code object")
    if not _ensure_code_extra_index():
        return False
    code_extra_index = <Py_ssize_t>_code_extra_index
    return _PyCode_SetExtra(code, code_extra_index, None) == 0


def _store_modified_code_for_evaluation(
    object original_code,
    object modified_code,
    object breakpoint_lines=None,
) -> bool:
    """Persist modified-code metadata for eval-frame lookup."""
    cdef object metadata

    if not isinstance(modified_code, types.CodeType):
        raise TypeError("modified_code argument must be a code object")

    # compute fingerprint so we can cheaply detect stale entries later
    cdef int fp = 0
    if breakpoint_lines is not None:
        try:
            fp = hash(tuple(sorted(cast(TypingAny, breakpoint_lines))))
        except Exception:
            fp = 0

    metadata = {
        "modified_code": modified_code,
        "breakpoint_lines": set(cast(TypingAny, breakpoint_lines or ())),
        "breakpoint_fp": fp,
        "version": _BYTECODE_META_VERSION,
    }

    from dapper._frame_eval.cache_manager import CacheManager

    CacheManager._set_cached_code(cast(TypingAny, original_code), modified_code)
    return _store_code_extra_metadata(original_code, metadata)


def _get_modified_code_for_evaluation(object code_obj):
    """Return the modified code object associated with *code_obj*, if any."""
    cdef object metadata = _get_code_extra_metadata(code_obj)
    cdef object modified_code = None
    cdef object cached_code = None
    cdef object filename = getattr(code_obj, "co_filename", None)

    if isinstance(metadata, dict):
        # verify metadata version and fingerprint
        if metadata.get("version") != _BYTECODE_META_VERSION:
            telemetry.record_bytecode_cache_key_mismatch(filename=filename)
        else:
            modified_code = metadata.get("modified_code")
            if isinstance(modified_code, types.CodeType):
                telemetry.record_cache_hit(source="code_extra", filename=filename)
                return modified_code

    from dapper._frame_eval.cache_manager import CacheManager

    cached_code = CacheManager._get_cached_code(cast(TypingAny, code_obj))
    if isinstance(cached_code, types.CodeType):
        telemetry.record_cache_hit(source="cache_manager", filename=filename)
        return cached_code

    telemetry.record_cache_miss(filename=filename)
    return None


__all__ = [
    "FuncCodeInfo",
    "ThreadInfo",
    "_FrameEvalModuleState",
    "_PyCode_GetExtra",
    "_PyCode_SetExtra",
    "_PyEval_RequestCodeExtraIndex",
    "_clear_code_extra_metadata",
    "_state",
    "dummy_trace_dispatch",
    "get_frame_eval_capabilities",
    "get_eval_frame_hook_status",
    "get_func_code_info",
    "install_eval_frame_hook",
    "_collect_code_lines",
    "_clear_thread_trace_func",
    "_get_code_extra_metadata",
    "_dispatch_trace_callback",
    "_get_modified_code_for_evaluation",
    "uninstall_eval_frame_hook",
    "_get_current_eval_frame_address",
    "_set_thread_trace_func",
    "_store_code_extra_metadata",
    "_store_modified_code_for_evaluation",
    "_should_trace_code_for_eval_frame",
    "_should_trace_code_for_eval_frame_with_frame",
]
