"""Tests for user_exception Just My Code integration.

Covers the rule added in dapper/core/debugger_bdb.py:
  When ``just_my_code=True``, ``user_exception`` must silently skip exceptions
  raised inside non-user frames (frozen importlib internals, stdlib, etc.) even
  if the "raised" exception breakpoint filter is active.

The canonical real-world trigger is Python's import machinery using ``KeyError``
as internal control flow inside ``<frozen importlib._bootstrap>``.
"""

from __future__ import annotations

import sys
import sysconfig
from types import FrameType
from types import SimpleNamespace
from typing import cast

import pytest

from dapper.core.debugger_bdb import DebuggerBDB
from dapper.core.exception_handler import ExceptionBreakpointConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dbg(just_my_code: bool = True, break_on_raised: bool = True) -> tuple[DebuggerBDB, list]:
    """Return a (dbg, messages) pair ready for user_exception tests."""
    messages: list[tuple[str, dict]] = []
    dbg = DebuggerBDB(
        send_message=lambda event, **kw: messages.append((event, kw)),
        process_commands=lambda: None,
        just_my_code=just_my_code,
    )
    dbg.exception_handler.config = ExceptionBreakpointConfig(
        break_on_raised=break_on_raised,
    )
    return dbg, messages


def _make_frame(filename: str, lineno: int = 1) -> FrameType:
    code = SimpleNamespace(co_filename=filename, co_name="<module>", co_firstlineno=1)
    return cast(
        "FrameType",
        SimpleNamespace(
            f_code=code,
            f_lineno=lineno,
            f_locals={},
            f_globals={},
            f_back=None,
        ),
    )


def _exc_info(exc: BaseException) -> tuple:
    try:
        raise exc
    except type(exc):
        return sys.exc_info()


# ---------------------------------------------------------------------------
# Frozen / importlib frames (the motivating bug)
# ---------------------------------------------------------------------------


class TestFrozenFrameSkipped:
    """Exceptions from <frozen importlib._bootstrap> must be silently ignored
    when just_my_code=True, regardless of the raised-exception filter."""

    def test_keyerror_in_frozen_importlib_is_skipped(self):
        """Mirrors the real KeyError('hn.fetch') inside importlib at startup."""
        dbg, messages = _make_dbg(just_my_code=True, break_on_raised=True)
        frame = _make_frame("<frozen importlib._bootstrap>", lineno=435)

        dbg.user_exception(frame, _exc_info(KeyError("hn.fetch")))

        assert messages == [], "stopped event must not be emitted for frozen importlib frame"

    def test_stopiteration_in_frozen_frame_is_skipped(self):
        dbg, messages = _make_dbg(just_my_code=True, break_on_raised=True)
        frame = _make_frame("<frozen importlib._bootstrap_external>")

        dbg.user_exception(frame, _exc_info(StopIteration()))

        assert messages == []

    def test_generic_frozen_frame_is_skipped(self):
        dbg, messages = _make_dbg(just_my_code=True, break_on_raised=True)
        frame = _make_frame("<frozen something>")

        dbg.user_exception(frame, _exc_info(RuntimeError("internal")))

        assert messages == []


# ---------------------------------------------------------------------------
# User frames still stop
# ---------------------------------------------------------------------------


class TestUserFrameStops:
    """Exceptions from user code must still trigger a stopped event."""

    def test_exception_in_user_file_stops(self, tmp_path):
        user_file = str(tmp_path / "myapp" / "main.py")
        dbg, messages = _make_dbg(just_my_code=True, break_on_raised=True)
        frame = _make_frame(user_file, lineno=42)

        dbg.user_exception(frame, _exc_info(ValueError("oops")))

        stopped = [m for m in messages if m[0] == "stopped"]
        assert stopped, "stopped event expected for user frame"
        assert stopped[0][1]["reason"] == "exception"

    def test_exception_in_user_file_without_just_my_code_stops(self):
        """just_my_code=False: non-user frames must also stop."""
        dbg, messages = _make_dbg(just_my_code=False, break_on_raised=True)
        frame = _make_frame("<frozen importlib._bootstrap>")

        dbg.user_exception(frame, _exc_info(KeyError("whatever")))

        stopped = [m for m in messages if m[0] == "stopped"]
        assert stopped, "stopped event expected when just_my_code=False"

    def test_exception_breakpoints_disabled_never_stops(self, tmp_path):
        """No stopped event when break_on_raised=False, regardless of frame."""
        user_file = str(tmp_path / "app.py")
        dbg, messages = _make_dbg(just_my_code=True, break_on_raised=False)
        frame = _make_frame(user_file)

        dbg.user_exception(frame, _exc_info(RuntimeError("ignored")))

        assert messages == []


# ---------------------------------------------------------------------------
# stdlib / site-packages frames
# ---------------------------------------------------------------------------


class TestLibraryFrameSkipped:
    """Non-user frames other than <frozen> are also skipped."""

    def test_site_packages_frame_is_skipped(self):
        dbg, messages = _make_dbg(just_my_code=True, break_on_raised=True)
        frame = _make_frame("/usr/lib/python3.12/site-packages/requests/adapters.py")

        dbg.user_exception(frame, _exc_info(ValueError("lib error")))

        assert messages == []

    def test_stdlib_frame_is_skipped(self):
        # Construct a path that lives inside the stdlib prefix so is_user_path
        # classifies it as non-user regardless of the local machine layout.
        stdlib_dir = sysconfig.get_path("stdlib")
        if stdlib_dir is None:
            pytest.skip("cannot determine stdlib path on this interpreter")
        stdlib_file = stdlib_dir + "/email/message.py"
        dbg, messages = _make_dbg(just_my_code=True, break_on_raised=True)
        frame = _make_frame(stdlib_file)

        dbg.user_exception(frame, _exc_info(KeyError("missing")))

        assert messages == []


# ---------------------------------------------------------------------------
# Stopped event shape
# ---------------------------------------------------------------------------


class TestStoppedEventShape:
    """The stopped event must carry expected DAP fields."""

    def test_stopped_event_fields(self, tmp_path):
        user_file = str(tmp_path / "app.py")
        dbg, messages = _make_dbg(just_my_code=True, break_on_raised=True)
        frame = _make_frame(user_file)

        dbg.user_exception(frame, _exc_info(TypeError("bad type")))

        stopped = [m for m in messages if m[0] == "stopped"]
        assert stopped
        payload = stopped[0][1]
        assert payload["reason"] == "exception"
        assert payload["allThreadsStopped"] is True
        assert "threadId" in payload
