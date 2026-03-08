"""Sanity check: ensure the frame-eval Cython extension is available in CI runs.

This test helps CI fail early and with a clear message when the compiled
frame-eval extension isn't present in the runtime environment.

The CI workflow will build/install the extension before running tests so
this assertion should pass on CI. When developers run tests locally without
compiling C-extensions it's OK for this to fail — the other tests guard
on availability — but in CI we want an explicit failure to remind us to
build the extension.
"""

from tests._cython import assert_loaded_compiled_frame_evaluator


def test_frame_eval_extension_importable():
    """Assert that the loaded frame-eval module is the compiled extension."""
    module = assert_loaded_compiled_frame_evaluator()
    origin = getattr(module, "__file__", None)

    assert origin is not None, "Imported _frame_evaluator but __file__ is missing"
