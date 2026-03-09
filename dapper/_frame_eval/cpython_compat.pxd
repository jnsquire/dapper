from cpython.object cimport PyObject


# Centralize CPython minor-version compatibility for Cython consumers.
# Phase 1 extracts the code-extra API name differences. Later phases can add
# eval-frame hook and frame-access shims here without spreading version logic
# through _frame_evaluator.pyx.

cdef extern from "Python.h":
    ctypedef Py_ssize_t Py_ssize_t
    ctypedef struct PyInterpreterState:
        pass
    ctypedef struct PyThreadState:
        pass
    ctypedef struct PyCodeObject:
        pass
    ctypedef struct PyFrameObject:
        pass
    ctypedef void (*freefunc)(void *)


cdef extern from "internal/pycore_frame.h":
    ctypedef struct _PyInterpreterFrame:
        PyCodeObject *f_code
        _PyInterpreterFrame *previous
        PyObject *f_funcobj
        PyObject *f_globals
        PyObject *f_builtins
        PyObject *f_locals
        PyFrameObject *frame_obj


cdef extern from "Python.h":
    ctypedef PyObject *(*_PyFrameEvalFunction)(PyThreadState *, _PyInterpreterFrame *, int) noexcept
    PyObject *_PyEval_EvalFrameDefault(PyThreadState *tstate, _PyInterpreterFrame *frame, int exc)


cdef extern from *:
    """
    #define _dapper_GetInterpreterState() PyInterpreterState_Get()
    #define _dapper_GetEvalFrameFunc(interp) _PyInterpreterState_GetEvalFrameFunc(interp)
    #define _dapper_SetEvalFrameFunc(interp, func) _PyInterpreterState_SetEvalFrameFunc(interp, func)
    #define _dapper_InterpreterFrame_GetCode(frame) PyUnstable_InterpreterFrame_GetCode(frame)
    #define _dapper_InterpreterFrame_GetLine(frame) PyUnstable_InterpreterFrame_GetLine(frame)
    #define _dapper_InterpreterFrame_GetFrameObject(frame) ((frame)->frame_obj)

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
    PyInterpreterState *_dapper_GetInterpreterState_C "_dapper_GetInterpreterState"()
    _PyFrameEvalFunction _dapper_GetEvalFrameFunc_C "_dapper_GetEvalFrameFunc"(PyInterpreterState *interp)
    void _dapper_SetEvalFrameFunc_C "_dapper_SetEvalFrameFunc"(
        PyInterpreterState *interp,
        _PyFrameEvalFunction eval_frame,
    )
    object _dapper_InterpreterFrame_GetCode_C "_dapper_InterpreterFrame_GetCode"(_PyInterpreterFrame *frame)
    int _dapper_InterpreterFrame_GetLine_C "_dapper_InterpreterFrame_GetLine"(_PyInterpreterFrame *frame)
    PyFrameObject *_dapper_InterpreterFrame_GetFrameObject_C "_dapper_InterpreterFrame_GetFrameObject"(
        _PyInterpreterFrame *frame,
    )
    Py_ssize_t _dapper_RequestCodeExtraIndex_C "_dapper_RequestCodeExtraIndex"(freefunc)
    int _dapper_Code_SetExtra_C "_dapper_Code_SetExtra"(object code, Py_ssize_t index, void *extra)
    int _dapper_Code_GetExtra_C "_dapper_Code_GetExtra"(object code, Py_ssize_t index, void **extra)