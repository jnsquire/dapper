"""Simple test for frame evaluation functionality.

This module was originally a standalone script that enabled frame evaluation
at import time.  That caused pytest to hang during collection because the
low-level eval-frame hook would activate while pytest was importing test
modules, triggering deep recursion.  The code has been moved into a test
function so the hook is only enabled during an actual test run.
"""

import dapper._frame_eval
from dapper._frame_eval import disable_frame_eval
from dapper._frame_eval import enable_frame_eval
from dapper._frame_eval import is_frame_eval_available


def test_enable_frame_eval():
    """Ensure the frame-eval subsystem can be enabled when available.

    The test does **not** enable the hook at import time; doing so would
    interfere with pytest's own execution (see issue #...).
    """

    # sanity-check availability
    assert isinstance(dapper._frame_eval.CYTHON_AVAILABLE, bool)
    available = is_frame_eval_available()

    if available:
        success = enable_frame_eval()
        assert success is True
        # verify we can disable again to avoid leaving the hook active for the
        # remainder of the test suite
        assert disable_frame_eval() is True
    else:
        # on unsupported interpreters the call should simply be a no-op
        # (``enable_frame_eval`` returns False).
        assert enable_frame_eval() is False
