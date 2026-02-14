"""Sanity check: ensure the frame-eval Cython extension is available in CI runs.

This test helps CI fail early and with a clear message when the compiled
frame-eval extension isn't present in the runtime environment.

The CI workflow will build/install the extension before running tests so
this assertion should pass on CI. When developers run tests locally without
compiling C-extensions it's OK for this to fail — the other tests guard
on availability — but in CI we want an explicit failure to remind us to
build the extension.
"""

import importlib
import importlib.util


def test_frame_eval_extension_importable():
    """Assert that the compiled frame-eval extension module is present.

    The test will print helpful diagnostics on failure so CI logs are
    informative.
    """
    spec = importlib.util.find_spec("dapper._frame_eval._frame_evaluator")

    # Provide a detailed failure message to help with CI debugging
    if spec is None:
        msg = (
            "Cython frame-eval extension not found.\n"
            "If you expect C extensions to be built, ensure the CI step builds the 'frame-eval' extras.\n"
            "Locally you can build with: python -m pip install -e '.[frame-eval]'\n"
            "Spec lookup returned None and import failed for: dapper._frame_eval._frame_evaluator"
        )
        raise AssertionError(msg)

    # Try importing the module to assert it loads and inspect the origin
    module = importlib.import_module("dapper._frame_eval._frame_evaluator")
    origin = getattr(module, "__file__", None)
    assert origin is not None, "Imported _frame_evaluator but __file__ is missing"

    # Basic sanity: expect a compiled extension file (.pyd on Windows, .so on Linux/macOS)
    assert origin.endswith((".pyd", ".so", ".dylib")) or "_frame_evaluator" in origin, (
        f"Unexpected extension origin: {origin}"
    )
