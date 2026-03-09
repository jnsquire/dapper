"""Sanity check: ensure the frame-eval Cython extension is available in CI runs.

This test helps CI fail early and with a clear message when the compiled
frame-eval extension isn't present in the runtime environment.

The CI workflow will build/install the extension before running tests so
this assertion should pass on CI. When developers run tests locally without
compiling C-extensions it's OK for this to fail — the other tests guard
on availability — but in CI we want an explicit failure to remind us to
build the extension.
"""

import pytest

from tests._cython import assert_loaded_compiled_frame_evaluator
from tests._cython import compiled_frame_evaluator_expected


def test_frame_eval_extension_importable():
    """Assert that the loaded frame-eval module is the compiled extension."""
    if not compiled_frame_evaluator_expected():
        pytest.skip(
            "Compiled frame-eval extension is only built on the default 3.12 path or the experimental 3.11 validation path"
        )

    module = assert_loaded_compiled_frame_evaluator()
    origin = getattr(module, "__file__", None)

    assert origin is not None, "Imported _frame_evaluator but __file__ is missing"
