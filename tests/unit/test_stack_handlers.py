"""Tests for dapper/shared/stack_handlers.py."""

from __future__ import annotations

import threading
import types
from unittest.mock import MagicMock

from dapper.shared.debug_shared import DebugSession
from dapper.shared.stack_handlers import handle_scopes_impl
from dapper.shared.stack_handlers import handle_stack_trace_impl
from dapper.shared.stack_handlers import handle_threads_impl

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(dbg=None) -> DebugSession:
    """Create a DebugSession with a mock transport and optional debugger."""
    session = DebugSession()
    session.debugger = dbg
    session.transport.send = MagicMock()  # type: ignore[assignment]
    return session


def _make_thread_tracker(
    *,
    frames_by_thread: dict | None = None,
    frame_id_to_frame: dict | None = None,
    threads: dict | None = None,
    stopped_thread_ids: set | None = None,
) -> MagicMock:
    """Create a mock thread tracker conforming to ThreadTrackerLike."""
    tt = MagicMock()
    tt.frames_by_thread = frames_by_thread if frames_by_thread is not None else {}
    tt.frame_id_to_frame = frame_id_to_frame if frame_id_to_frame is not None else {}
    tt.threads = threads if threads is not None else {}
    tt.stopped_thread_ids = stopped_thread_ids if stopped_thread_ids is not None else set()
    return tt


def _make_dbg_with_thread_tracker(frames_by_thread: dict | None = None) -> MagicMock:
    dbg = MagicMock()
    dbg.thread_tracker = _make_thread_tracker(frames_by_thread=frames_by_thread)
    return dbg


def _make_frame_tuple(name: str = "func", filename: str = "/a/b.py", lineno: int = 10) -> tuple:
    """Create a (frame_obj, lineno) tuple like bdb uses."""
    code = types.CodeType(
        0,  # argcount
        0,  # posonlyargcount
        0,  # kwonlyargcount
        0,  # nlocals
        0,  # stacksize
        0,  # flags
        b"",  # codestring
        (),  # consts
        (),  # names
        (),  # varnames
        filename,  # filename
        name,  # name
        name,  # qualname (Python 3.11+)
        0,  # firstlineno
        b"",  # linetable / lnotab
        b"",  # exceptiontable (Python 3.11+)
        (),  # freevars
        (),  # cellvars
    )
    frame = MagicMock()
    frame.f_code = code
    return (frame, lineno)


# ---------------------------------------------------------------------------
# handle_stack_trace_impl
# ---------------------------------------------------------------------------


class TestHandleStackTraceImpl:
    def test_no_dbg_returns_empty_stack(self) -> None:
        session = _make_session()
        result = handle_stack_trace_impl(
            session,
            {"threadId": 1},
            get_thread_ident=lambda: 1,
        )
        assert result == {"success": True, "body": {"stackFrames": []}}
        session.transport.send.assert_called_once_with(
            "stackTrace", threadId=1, stackFrames=[], totalFrames=0
        )

    def test_stack_with_dict_frames(self) -> None:
        """dict-format frames (from thread tracker or similar)."""
        dbg = MagicMock()
        dbg.thread_tracker = _make_thread_tracker()  # empty tracker — falls through to stack
        dbg.stack = [
            {"name": "main", "file": "/app/main.py", "line": 42},
            {"name": "helper", "path": "/app/helper.py", "line": 7},
        ]
        session = _make_session(dbg)

        result = handle_stack_trace_impl(
            session,
            {"threadId": 1},
            get_thread_ident=lambda: 1,  # matches thread_id
        )

        body = result["body"]
        frames = body["stackFrames"]
        assert len(frames) == 2
        assert frames[0]["name"] == "main"
        assert frames[0]["line"] == 42
        assert frames[1]["name"] == "helper"
        assert frames[1]["line"] == 7

    def test_stack_tuple_frames(self) -> None:
        """(frame_obj, lineno) tuple format."""
        dbg = MagicMock()
        dbg.thread_tracker = _make_thread_tracker()  # empty tracker — falls through to stack
        frame = MagicMock()
        frame.f_code.co_name = "my_func"
        frame.f_code.co_filename = "/project/mod.py"
        dbg.stack = [(frame, 99)]
        session = _make_session(dbg)

        result = handle_stack_trace_impl(
            session,
            {"threadId": 5},
            get_thread_ident=lambda: 5,
        )

        frames = result["body"]["stackFrames"]
        assert len(frames) == 1
        assert frames[0]["name"] == "my_func"
        assert frames[0]["line"] == 99
        assert frames[0]["source"]["path"] == "/project/mod.py"

    def test_stack_not_used_for_different_thread(self) -> None:
        """Stack is only used when thread_id matches get_thread_ident()."""
        dbg = MagicMock()
        dbg.thread_tracker = _make_thread_tracker()
        frame = MagicMock()
        frame.f_code.co_name = "fn"
        frame.f_code.co_filename = "/x/y.py"
        dbg.stack = [(frame, 1)]
        session = _make_session(dbg)

        result = handle_stack_trace_impl(
            session,
            {"threadId": 999},  # different from ident
            get_thread_ident=lambda: 1,
        )

        assert result["body"]["stackFrames"] == []

    def test_levels_truncates_frames(self) -> None:
        dbg = MagicMock()
        dbg.thread_tracker = _make_thread_tracker()
        frames = [{"name": f"fn{i}", "file": "/x.py", "line": i} for i in range(5)]
        dbg.stack = frames
        session = _make_session(dbg)

        result = handle_stack_trace_impl(
            session,
            {"threadId": 1, "startFrame": 0, "levels": 2},
            get_thread_ident=lambda: 1,
        )

        assert len(result["body"]["stackFrames"]) == 2

    def test_arguments_none_treated_as_empty(self) -> None:
        session = _make_session()
        result = handle_stack_trace_impl(
            session,
            None,
            get_thread_ident=lambda: 1,
        )
        assert result["body"]["stackFrames"] == []


# ---------------------------------------------------------------------------
# handle_threads_impl
# ---------------------------------------------------------------------------


class TestHandleThreadsImpl:
    def test_no_dbg_returns_empty_threads(self) -> None:
        session = _make_session()
        result = handle_threads_impl(session, None)
        assert result == {"success": True, "body": {"threads": []}}
        session.transport.send.assert_called_once_with("threads", threads=[])

    def test_threads_from_thread_tracker_dict(self) -> None:
        dbg = MagicMock()
        dbg.thread_tracker.threads = {1: "MainThread", 2: "WorkerThread"}
        session = _make_session(dbg)

        result = handle_threads_impl(session, {})

        threads = result["body"]["threads"]
        ids = {t["id"] for t in threads}
        names = {t["name"] for t in threads}
        assert ids == {1, 2}
        # At least one of the names should match
        assert "MainThread" in names or "WorkerThread" in names

    def test_threads_live_name_takes_priority(self) -> None:
        """threading.enumerate() names override stored names."""
        real_thread = threading.current_thread()
        dbg = MagicMock()
        # Store a stale name
        dbg.thread_tracker.threads = {real_thread.ident: "StaleStoredName"}
        session = _make_session(dbg)

        result = handle_threads_impl(session, {})

        threads = {t["id"]: t["name"] for t in result["body"]["threads"]}
        # Live name from threading.enumerate() should be used
        assert threads[real_thread.ident] == real_thread.name

    def test_empty_thread_tracker(self) -> None:
        dbg = MagicMock()
        dbg.thread_tracker.threads = {}
        session = _make_session(dbg)

        result = handle_threads_impl(session, {})
        assert result["body"]["threads"] == []


# ---------------------------------------------------------------------------
# handle_scopes_impl
# ---------------------------------------------------------------------------


class TestHandleScopesImpl:
    VAR_REF_TUPLE_SIZE = 3

    def test_no_dbg_returns_empty_scopes(self) -> None:
        session = _make_session()
        result = handle_scopes_impl(
            session,
            {"frameId": 0},
            var_ref_tuple_size=self.VAR_REF_TUPLE_SIZE,
        )
        assert result["body"]["scopes"] == []
        session.transport.send.assert_called_once_with("scopes", scopes=[])

    def test_scopes_from_frame_id_to_frame(self) -> None:
        dbg = MagicMock()
        fake_frame = MagicMock()
        dbg.thread_tracker.frame_id_to_frame = {2: fake_frame}
        # allocate_scope_ref is now called; make it return sequential IDs
        _ref_counter = iter(range(100, 200))
        dbg.var_manager.allocate_scope_ref.side_effect = lambda _fid, _scope: next(_ref_counter)
        session = _make_session(dbg)

        result = handle_scopes_impl(
            session,
            {"frameId": 2},
            var_ref_tuple_size=self.VAR_REF_TUPLE_SIZE,
        )

        scopes = result["body"]["scopes"]
        assert len(scopes) == 2
        scope_names = {s["name"] for s in scopes}
        assert "Locals" in scope_names
        assert "Globals" in scope_names
        # allocate_scope_ref returns the sequential IDs
        locals_scope = next(s for s in scopes if s["name"] == "Locals")
        assert locals_scope["variablesReference"] == 100
        globals_scope = next(s for s in scopes if s["name"] == "Globals")
        assert globals_scope["variablesReference"] == 101

    def test_scopes_fallback_to_stack(self) -> None:
        dbg = MagicMock()
        dbg.thread_tracker = _make_thread_tracker()  # empty tracker — falls through to stack
        fake_frame = MagicMock()
        dbg.stack = [(fake_frame, 10), (MagicMock(), 20)]  # index 0 = frame_id 0
        session = _make_session(dbg)

        result = handle_scopes_impl(
            session,
            {"frameId": 0},
            var_ref_tuple_size=self.VAR_REF_TUPLE_SIZE,
        )

        scopes = result["body"]["scopes"]
        assert len(scopes) == 2

    def test_scopes_no_frame_id_returns_empty(self) -> None:
        dbg = MagicMock()
        dbg.thread_tracker.frame_id_to_frame = {}
        session = _make_session(dbg)

        result = handle_scopes_impl(
            session,
            {},  # no frameId
            var_ref_tuple_size=self.VAR_REF_TUPLE_SIZE,
        )

        assert result["body"]["scopes"] == []

    def test_scopes_frame_not_found_returns_empty(self) -> None:
        dbg = MagicMock()
        dbg.thread_tracker.frame_id_to_frame = {}  # empty — frame_id not present
        session = _make_session(dbg)

        result = handle_scopes_impl(
            session,
            {"frameId": 99},
            var_ref_tuple_size=self.VAR_REF_TUPLE_SIZE,
        )

        assert result["body"]["scopes"] == []

    def test_arguments_none_treated_as_empty(self) -> None:
        session = _make_session()
        result = handle_scopes_impl(
            session,
            None,
            var_ref_tuple_size=self.VAR_REF_TUPLE_SIZE,
        )
        assert result["body"]["scopes"] == []
