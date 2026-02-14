from __future__ import annotations

import sys
import threading
from typing import TYPE_CHECKING
from typing import cast

if TYPE_CHECKING:
    from types import TracebackType

from dapper.core.debugger_bdb import DebuggerBDB


def _raiser(msg: str):
    raise RuntimeError(msg)


def _raise_and_capture() -> tuple[type[BaseException] | None, BaseException | None, object | None]:
    msg = "boom"
    try:
        _raiser(msg)
    except Exception:
        # sys.exc_info() returns a tuple of (type, value, tb) where none
        # is possible in pathological cases; return the full tuple.
        return sys.exc_info()
    # Fallback (shouldn't happen) - return explicit None-filled tuple to satisfy type checkers
    return (None, None, None)


def test_user_exception_populates_exception_info_shape():
    dbg = DebuggerBDB()
    # Force immediate break-on-exception behavior
    dbg.exception_handler.config.break_on_raised = True

    exc_type, exc_value, exc_tb = _raise_and_capture()
    assert exc_type is not None
    assert exc_value is not None
    assert exc_tb is not None
    # Cast to TracebackType for static checkers and access tb_frame
    tb = cast("TracebackType", exc_tb)
    # The traceback's frame points at the site where the exception was raised
    frame = tb.tb_frame

    # Sanity: no info yet for current thread
    tid = threading.get_ident()
    assert tid not in dbg.exception_handler.exception_info_by_thread

    # Call the handler as the runtime would
    # Pass a concrete exc_info tuple (non-optional) to satisfy the signature
    dbg.user_exception(frame, (exc_type, exc_value, tb))

    # After handling, structured info should be present for current thread
    assert tid in dbg.exception_handler.exception_info_by_thread
    info = dbg.exception_handler.exception_info_by_thread[tid]

    # Top-level keys
    assert isinstance(info, dict)
    for k in ("exceptionId", "description", "breakMode", "details"):
        assert k in info

    details = info["details"]
    assert isinstance(details, dict)
    for k in ("message", "typeName", "fullTypeName", "source", "stackTrace"):
        assert k in details

    # Basic type checks
    assert isinstance(details["message"], str)
    assert isinstance(details["typeName"], str)
    assert isinstance(details["fullTypeName"], str)
    assert isinstance(details["source"], str)
    assert isinstance(details["stackTrace"], list)
    assert all(isinstance(x, str) for x in details["stackTrace"])
