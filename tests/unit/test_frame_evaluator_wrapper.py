"""Unit tests for the small C API wrappers exported by the Cython frame evaluator.

These tests only run when the Cython module is available in the test env.
"""

from types import CodeType

import pytest

from tests._cython import assert_loaded_compiled_frame_evaluator
from tests._cython import has_loaded_compiled_frame_evaluator

CYTHON_AVAILABLE = has_loaded_compiled_frame_evaluator()


@pytest.mark.skipif(not CYTHON_AVAILABLE, reason="Cython module not available")
def test_pycodesetextra_raises_on_non_code():
    """Ensure the Cython _PyCode_SetExtra wrapper raises a TypeError for non-code objects.

    This gives a clear, Python-level error for callers that accidentally pass
    a non-code object instead of allowing the underlying C API to raise a
    confusing SystemError.
    """
    m = assert_loaded_compiled_frame_evaluator()
    if not hasattr(m, "_PyCode_SetExtra"):
        pytest.skip("_PyCode_SetExtra not exported by compiled Cython module in this build")

    _pycode_setextra = m._PyCode_SetExtra

    with pytest.raises(TypeError):
        _pycode_setextra("not_a_code_object", 0, None)


@pytest.mark.skipif(not CYTHON_AVAILABLE, reason="Cython module not available")
def test_code_extra_metadata_round_trip_for_modified_code() -> None:
    """Modified-code metadata should round-trip through the compiled wrapper helpers."""
    m = assert_loaded_compiled_frame_evaluator()
    required = (
        "_store_modified_code_for_evaluation",
        "_get_code_extra_metadata",
        "_get_modified_code_for_evaluation",
        "_clear_code_extra_metadata",
    )
    for name in required:
        if not hasattr(m, name):
            pytest.skip(f"{name} not exported by compiled Cython module in this build")

    source = "def original():\n    return 1\n"
    compiled = compile(source, "<code-extra-round-trip>", "exec")
    original_code = next(
        const
        for const in compiled.co_consts
        if isinstance(const, CodeType) and const.co_name == "original"
    )

    modified_source = "def original():\n    value = 1\n    return value\n"
    modified_compiled = compile(modified_source, "<code-extra-round-trip>", "exec")
    modified_code = next(
        const
        for const in modified_compiled.co_consts
        if isinstance(const, CodeType) and const.co_name == "original"
    )

    assert m._store_modified_code_for_evaluation(original_code, modified_code, {2, 3}) is True
    metadata = m._get_code_extra_metadata(original_code)
    assert isinstance(metadata, dict)
    assert metadata["breakpoint_lines"] == {2, 3}
    assert m._get_modified_code_for_evaluation(original_code) is modified_code
    assert m._clear_code_extra_metadata(original_code) is True
    assert m._get_code_extra_metadata(original_code) is None
