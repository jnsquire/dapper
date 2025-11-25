"""Unit tests for the small C API wrappers exported by the Cython frame evaluator.

These tests only run when the Cython module is available in the test env.
"""

import importlib
import importlib.util

import pytest

CYTHON_AVAILABLE = importlib.util.find_spec("dapper._frame_eval._frame_evaluator") is not None


@pytest.mark.skipif(not CYTHON_AVAILABLE, reason="Cython module not available")
def test_pycodesetextra_raises_on_non_code():
    """Ensure the Cython _PyCode_SetExtra wrapper raises a TypeError for non-code objects.

    This gives a clear, Python-level error for callers that accidentally pass
    a non-code object instead of allowing the underlying C API to raise a
    confusing SystemError.
    """
    m = importlib.import_module("dapper._frame_eval._frame_evaluator")
    if not hasattr(m, "_PyCode_SetExtra"):
        pytest.skip("_PyCode_SetExtra not exported by compiled Cython module in this build")

    _pycode_setextra = m._PyCode_SetExtra

    with pytest.raises(TypeError):
        _pycode_setextra("not_a_code_object", 0, None)
