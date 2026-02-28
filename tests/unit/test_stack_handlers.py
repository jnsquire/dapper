"""Tests for dapper/shared/stack_handlers.py."""

from __future__ import annotations

import threading
import types
from unittest.mock import MagicMock

from dapper.shared.stack_handlers import handle_scopes_impl
from dapper.shared.stack_handlers import handle_stack_trace_impl
from dapper.shared.stack_handlers import handle_threads_impl

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_safe_send() -> MagicMock:
    return MagicMock()


def _make_dbg_with_thread_tracker(frames_by_thread: dict | None = None) -> MagicMock:
    dbg = MagicMock()
    tt = MagicMock()
    tt.frames_by_thread = frames_by_thread or {}
    dbg.thread_tracker = tt
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
        send = _make_safe_send()
        result = handle_stack_trace_impl(
            None,
            {"threadId": 1},
            get_thread_ident=lambda: 1,
            safe_send_debug_message=send,
        )
        assert result == {"success": True, "body": {"stackFrames": []}}
        send.assert_called_once_with("stackTrace", threadId=1, stackFrames=[], totalFrames=0)

    def test_stack_with_dict_frames(self) -> None:
        """dict-format frames (from thread tracker or similar)."""
        send = _make_safe_send()
        dbg = MagicMock()
        dbg.thread_tracker = MagicMock(spec=[])  # no frames_by_thread
        dbg.stack = [
            {"name": "main", "file": "/app/main.py", "line": 42},
            {"name": "helper", "path": "/app/helper.py", "line": 7},
        ]

        result = handle_stack_trace_impl(
            dbg,
            {"threadId": 1},
            get_thread_ident=lambda: 1,  # matches thread_id
            safe_send_debug_message=send,
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
        send = _make_safe_send()
        dbg = MagicMock()
        dbg.thread_tracker = MagicMock(spec=[])  # no frames_by_thread attr
        frame = MagicMock()
        frame.f_code.co_name = "my_func"
        frame.f_code.co_filename = "/project/mod.py"
        dbg.stack = [(frame, 99)]

        result = handle_stack_trace_impl(
            dbg,
            {"threadId": 5},
            get_thread_ident=lambda: 5,
            safe_send_debug_message=send,
        )

        frames = result["body"]["stackFrames"]
        assert len(frames) == 1
        assert frames[0]["name"] == "my_func"
        assert frames[0]["line"] == 99
        assert frames[0]["source"]["path"] == "/project/mod.py"

    def test_stack_not_used_for_different_thread(self) -> None:
        """Stack is only used when thread_id matches get_thread_ident()."""
        send = _make_safe_send()
        dbg = MagicMock()
        dbg.thread_tracker = MagicMock(spec=[])
        frame = MagicMock()
        frame.f_code.co_name = "fn"
        frame.f_code.co_filename = "/x/y.py"
        dbg.stack = [(frame, 1)]

        result = handle_stack_trace_impl(
            dbg,
            {"threadId": 999},  # different from ident
            get_thread_ident=lambda: 1,
            safe_send_debug_message=send,
        )

        assert result["body"]["stackFrames"] == []

    def test_levels_truncates_frames(self) -> None:
        send = _make_safe_send()
        dbg = MagicMock()
        dbg.thread_tracker = MagicMock(spec=[])
        frames = [{"name": f"fn{i}", "file": "/x.py", "line": i} for i in range(5)]
        dbg.stack = frames

        result = handle_stack_trace_impl(
            dbg,
            {"threadId": 1, "startFrame": 0, "levels": 2},
            get_thread_ident=lambda: 1,
            safe_send_debug_message=send,
        )

        assert len(result["body"]["stackFrames"]) == 2

    def test_arguments_none_treated_as_empty(self) -> None:
        send = _make_safe_send()
        result = handle_stack_trace_impl(
            None,
            None,
            get_thread_ident=lambda: 1,
            safe_send_debug_message=send,
        )
        assert result["body"]["stackFrames"] == []


# ---------------------------------------------------------------------------
# handle_threads_impl
# ---------------------------------------------------------------------------


class TestHandleThreadsImpl:
    def test_no_dbg_returns_empty_threads(self) -> None:
        send = _make_safe_send()
        result = handle_threads_impl(None, None, send)
        assert result == {"success": True, "body": {"threads": []}}
        send.assert_called_once_with("threads", threads=[])

    def test_threads_from_thread_tracker_dict(self) -> None:
        send = _make_safe_send()
        dbg = MagicMock()
        dbg.thread_tracker.threads = {1: "MainThread", 2: "WorkerThread"}

        result = handle_threads_impl(dbg, {}, send)

        threads = result["body"]["threads"]
        ids = {t["id"] for t in threads}
        names = {t["name"] for t in threads}
        assert ids == {1, 2}
        # At least one of the names should match
        assert "MainThread" in names or "WorkerThread" in names

    def test_threads_live_name_takes_priority(self) -> None:
        """threading.enumerate() names override stored names."""
        send = _make_safe_send()
        real_thread = threading.current_thread()
        dbg = MagicMock()
        # Store a stale name
        dbg.thread_tracker.threads = {real_thread.ident: "StaleStoredName"}

        result = handle_threads_impl(dbg, {}, send)

        threads = {t["id"]: t["name"] for t in result["body"]["threads"]}
        # Live name from threading.enumerate() should be used
        assert threads[real_thread.ident] == real_thread.name

    def test_empty_thread_tracker(self) -> None:
        send = _make_safe_send()
        dbg = MagicMock()
        dbg.thread_tracker.threads = {}

        result = handle_threads_impl(dbg, {}, send)
        assert result["body"]["threads"] == []


# ---------------------------------------------------------------------------
# handle_scopes_impl
# ---------------------------------------------------------------------------


class TestHandleScopesImpl:
    VAR_REF_TUPLE_SIZE = 3

    def test_no_dbg_returns_empty_scopes(self) -> None:
        send = _make_safe_send()
        result = handle_scopes_impl(
            None,
            {"frameId": 0},
            safe_send_debug_message=send,
            var_ref_tuple_size=self.VAR_REF_TUPLE_SIZE,
        )
        assert result["body"]["scopes"] == []
        send.assert_called_once_with("scopes", scopes=[])

    def test_scopes_from_frame_id_to_frame(self) -> None:
        send = _make_safe_send()
        dbg = MagicMock()
        fake_frame = MagicMock()
        dbg.thread_tracker.frame_id_to_frame = {2: fake_frame}
        # allocate_scope_ref is now called; make it return sequential IDs
        _ref_counter = iter(range(100, 200))
        dbg.var_manager.allocate_scope_ref.side_effect = lambda _fid, _scope: next(_ref_counter)

        result = handle_scopes_impl(
            dbg,
            {"frameId": 2},
            safe_send_debug_message=send,
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
        send = _make_safe_send()
        dbg = MagicMock()
        dbg.thread_tracker = MagicMock(spec=[])  # no frame_id_to_frame
        fake_frame = MagicMock()
        dbg.stack = [(fake_frame, 10), (MagicMock(), 20)]  # index 0 = frame_id 0

        result = handle_scopes_impl(
            dbg,
            {"frameId": 0},
            safe_send_debug_message=send,
            var_ref_tuple_size=self.VAR_REF_TUPLE_SIZE,
        )

        scopes = result["body"]["scopes"]
        assert len(scopes) == 2

    def test_scopes_no_frame_id_returns_empty(self) -> None:
        send = _make_safe_send()
        dbg = MagicMock()
        dbg.thread_tracker.frame_id_to_frame = {}

        result = handle_scopes_impl(
            dbg,
            {},  # no frameId
            safe_send_debug_message=send,
            var_ref_tuple_size=self.VAR_REF_TUPLE_SIZE,
        )

        assert result["body"]["scopes"] == []

    def test_scopes_frame_not_found_returns_empty(self) -> None:
        send = _make_safe_send()
        dbg = MagicMock()
        dbg.thread_tracker.frame_id_to_frame = {}  # empty — frame_id not present

        result = handle_scopes_impl(
            dbg,
            {"frameId": 99},
            safe_send_debug_message=send,
            var_ref_tuple_size=self.VAR_REF_TUPLE_SIZE,
        )

        assert result["body"]["scopes"] == []

    def test_arguments_none_treated_as_empty(self) -> None:
        send = _make_safe_send()
        result = handle_scopes_impl(
            None,
            None,
            safe_send_debug_message=send,
            var_ref_tuple_size=self.VAR_REF_TUPLE_SIZE,
        )
        assert result["body"]["scopes"] == []
