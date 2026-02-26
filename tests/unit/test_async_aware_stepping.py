"""Tests for async-aware stepping (skip event-loop internals).

Covers:
- _frame_is_coroutine helper
- _is_event_loop_frame helper
- SteppingController.async_step_over flag + set_async_step_over()
- handle_next_impl sets the flag when stopped in a coroutine frame
- handle_step_in_impl sets the flag when stopped in a coroutine frame
- DebuggerBDB.user_line skips asyncio frames when flag is set
- user_line clears the flag when it arrives at user code
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dapper.core.debugger_bdb import DebuggerBDB
from dapper.core.debugger_bdb import _is_event_loop_frame
from dapper.core.stepping_controller import SteppingController
from dapper.shared.stepping_handlers import _frame_is_coroutine
from dapper.shared.stepping_handlers import handle_next_impl
from dapper.shared.stepping_handlers import handle_step_in_impl

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_frame(filename: str, flags: int = 0) -> SimpleNamespace:
    """Minimal frame-like object with f_code.co_filename and co_flags."""
    code = SimpleNamespace(co_filename=filename, co_flags=flags)
    return SimpleNamespace(f_code=code)


def _coroutine_flags() -> int:
    return inspect.CO_COROUTINE


def _async_gen_flags() -> int:
    return inspect.CO_ASYNC_GENERATOR


def _plain_flags() -> int:
    return 0  # no coroutine-related flags


# ---------------------------------------------------------------------------
# _frame_is_coroutine
# ---------------------------------------------------------------------------


def test_frame_is_coroutine_regular_function() -> None:
    frame = _make_frame("app.py", _plain_flags())
    assert _frame_is_coroutine(frame) is False


def test_frame_is_coroutine_coroutine_function() -> None:
    frame = _make_frame("app.py", _coroutine_flags())
    assert _frame_is_coroutine(frame) is True


def test_frame_is_coroutine_async_generator() -> None:
    frame = _make_frame("app.py", _async_gen_flags())
    assert _frame_is_coroutine(frame) is True


def test_frame_is_coroutine_missing_f_code() -> None:
    assert _frame_is_coroutine(SimpleNamespace()) is False


# ---------------------------------------------------------------------------
# _is_event_loop_frame
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    [
        "/usr/lib/python3.11/asyncio/base_events.py",
        "/usr/lib/python3.11/asyncio/tasks.py",
        "C:\\Python311\\Lib\\asyncio\\events.py",
        "/usr/lib/python3.11/concurrent/futures/_base.py",
        "C:\\Python311\\Lib\\concurrent\\futures\\_base.py",
    ],
)
def test_is_event_loop_frame_asyncio_paths(filename: str) -> None:
    frame = _make_frame(filename)
    assert _is_event_loop_frame(frame) is True  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "filename",
    [
        "/home/user/project/myapp.py",
        "/home/user/project/tasks.py",  # user file named tasks.py
        "/home/user/project/my_asyncio_wrapper.py",
        "C:\\Users\\dev\\project\\app.py",
    ],
)
def test_is_event_loop_frame_user_paths(filename: str) -> None:
    frame = _make_frame(filename)
    assert _is_event_loop_frame(frame) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# SteppingController.async_step_over
# ---------------------------------------------------------------------------


def test_stepping_controller_default_async_step_over() -> None:
    controller = SteppingController()
    assert controller.async_step_over is False


def test_stepping_controller_set_async_step_over() -> None:
    controller = SteppingController()
    controller.set_async_step_over()
    assert controller.async_step_over is True


def test_stepping_controller_set_async_step_over_false() -> None:
    controller = SteppingController()
    controller.set_async_step_over(True)
    controller.set_async_step_over(False)
    assert controller.async_step_over is False


def test_stepping_controller_clear_resets_async_step_over() -> None:
    controller = SteppingController()
    controller.set_async_step_over()
    controller.clear()
    assert controller.async_step_over is False


# ---------------------------------------------------------------------------
# handle_next_impl sets async_step_over when frame is a coroutine
# ---------------------------------------------------------------------------


def _make_dbg_with_frame(frame: SimpleNamespace) -> MagicMock:
    dbg = MagicMock()
    dbg.stepping_controller = SteppingController()
    dbg.stepping_controller.current_frame = frame  # type: ignore[assignment]
    return dbg


def test_handle_next_impl_sets_async_step_over_for_coroutine_frame() -> None:
    frame = _make_frame("app.py", _coroutine_flags())
    dbg = _make_dbg_with_frame(frame)
    thread_id = 1

    handle_next_impl(
        dbg,
        {"threadId": thread_id},
        get_thread_ident=lambda: thread_id,
        set_dbg_stepping_flag=lambda _d: None,
    )

    assert dbg.stepping_controller.async_step_over is True
    dbg.set_next.assert_called_once_with(frame)


def test_handle_next_impl_no_async_flag_for_regular_frame() -> None:
    frame = _make_frame("app.py", _plain_flags())
    dbg = _make_dbg_with_frame(frame)
    thread_id = 1

    handle_next_impl(
        dbg,
        {"threadId": thread_id},
        get_thread_ident=lambda: thread_id,
        set_dbg_stepping_flag=lambda _d: None,
    )

    assert dbg.stepping_controller.async_step_over is False
    dbg.set_next.assert_called_once_with(frame)


def test_handle_next_impl_no_frame_does_not_set_async_flag() -> None:
    dbg = MagicMock()
    dbg.stepping_controller = SteppingController()
    dbg.stepping_controller.current_frame = None
    thread_id = 1

    handle_next_impl(
        dbg,
        {"threadId": thread_id},
        get_thread_ident=lambda: thread_id,
        set_dbg_stepping_flag=lambda _d: None,
    )

    assert dbg.stepping_controller.async_step_over is False


# ---------------------------------------------------------------------------
# handle_step_in_impl sets async_step_over when frame is a coroutine
# ---------------------------------------------------------------------------


def test_handle_step_in_impl_sets_async_step_over_for_coroutine_frame() -> None:
    frame = _make_frame("app.py", _coroutine_flags())
    dbg = _make_dbg_with_frame(frame)
    thread_id = 1

    handle_step_in_impl(
        dbg,
        {"threadId": thread_id},
        get_thread_ident=lambda: thread_id,
        set_dbg_stepping_flag=lambda _d: None,
    )

    assert dbg.stepping_controller.async_step_over is True
    dbg.set_step.assert_called_once()


def test_handle_step_in_impl_no_async_flag_for_regular_frame() -> None:
    frame = _make_frame("app.py", _plain_flags())
    dbg = _make_dbg_with_frame(frame)
    thread_id = 1

    handle_step_in_impl(
        dbg,
        {"threadId": thread_id},
        get_thread_ident=lambda: thread_id,
        set_dbg_stepping_flag=lambda _d: None,
    )

    assert dbg.stepping_controller.async_step_over is False
    dbg.set_step.assert_called_once()


# ---------------------------------------------------------------------------
# DebuggerBDB.user_line skips / clears async_step_over
# ---------------------------------------------------------------------------


def _make_real_frame_obj(filename: str, flags: int = 0) -> MagicMock:
    """Create a real types.FrameType-like mock acceptable to DebuggerBDB."""
    code = MagicMock()
    code.co_filename = filename
    code.co_flags = flags
    frame = MagicMock()
    frame.f_code = code
    frame.f_lineno = 1
    frame.f_locals = {}
    return frame


def test_user_line_skips_asyncio_frame_when_async_step_over_set() -> None:
    dbg = DebuggerBDB()
    dbg.stepping_controller.async_step_over = True

    asyncio_frame = _make_real_frame_obj("/usr/lib/python3.11/asyncio/tasks.py")
    continued = []
    dbg.set_continue = lambda: continued.append(True)  # type: ignore[method-assign]
    # Patch away data-watch and other side effects
    dbg._check_data_watch_changes = lambda _f: []  # type: ignore[method-assign]

    dbg.user_line(asyncio_frame)  # type: ignore[arg-type]

    assert continued, "set_continue should have been called for asyncio frame"
    # Flag should still be True because we haven't reached user code yet
    assert dbg.stepping_controller.async_step_over is True


def test_user_line_clears_async_step_over_for_user_frame() -> None:
    dbg = DebuggerBDB()
    dbg.stepping_controller.async_step_over = True

    user_frame = _make_real_frame_obj("/home/user/project/app.py")
    user_frame.f_back = None  # terminate the stack walk
    # Wire just enough so user_line can run without crashing
    dbg._check_data_watch_changes = lambda _f: []  # type: ignore[method-assign]
    dbg._update_watch_snapshots = lambda _f: None  # type: ignore[method-assign]
    dbg._handle_regular_breakpoint = lambda _fn, _ln, _fr: False  # type: ignore[method-assign]
    stopped_events: list[str] = []
    dbg.send_message = lambda *_a, **kw: stopped_events.append(kw.get("reason", ""))  # type: ignore[method-assign]
    dbg.process_commands = lambda: None  # type: ignore[method-assign]
    dbg.set_continue = lambda: None  # type: ignore[method-assign]

    dbg.user_line(user_frame)  # type: ignore[arg-type]

    assert dbg.stepping_controller.async_step_over is False


def test_user_line_normal_behavior_unaffected_when_flag_false() -> None:
    """When async_step_over is False, asyncio frames should not be skipped."""
    # Disable just_my_code so the asyncio stdlib path doesn't get filtered out
    # before we can observe whether async_step_over affected anything.
    dbg = DebuggerBDB(just_my_code=False)
    assert dbg.stepping_controller.async_step_over is False

    asyncio_frame = _make_real_frame_obj("/usr/lib/python3.11/asyncio/tasks.py")
    asyncio_frame.f_back = None  # terminate the stack walk
    dbg._check_data_watch_changes = lambda _f: []  # type: ignore[method-assign]
    dbg._update_watch_snapshots = lambda _f: None  # type: ignore[method-assign]
    dbg._handle_regular_breakpoint = lambda _fn, _ln, _fr: False  # type: ignore[method-assign]
    stopped_events: list[str] = []
    dbg.send_message = lambda *_a, **kw: stopped_events.append(kw.get("reason", ""))  # type: ignore[method-assign]
    dbg.process_commands = lambda: None  # type: ignore[method-assign]
    dbg.set_continue = lambda: None  # type: ignore[method-assign]

    dbg.user_line(asyncio_frame)  # type: ignore[arg-type]

    # Flag untouched, user_line ran normally (stopped event emitted)
    assert dbg.stepping_controller.async_step_over is False
    assert stopped_events, "should have emitted stopped event"
