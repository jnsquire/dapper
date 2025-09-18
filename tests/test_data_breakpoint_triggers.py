from types import FrameType
from unittest.mock import MagicMock
from unittest.mock import patch

from dapper.debugger_bdb import DebuggerBDB


def make_frame(filename: str, lineno: int, locals_dict):
    frame = MagicMock(spec=FrameType)
    frame.f_code.co_filename = filename  # type: ignore[attr-defined]
    frame.f_lineno = lineno
    frame.f_locals = locals_dict
    frame.f_globals = {"__builtins__": __builtins__}
    return frame


@patch("dapper.debugger_bdb.send_debug_message")
def test_data_breakpoint_triggers_on_change(mock_send):
    dbg = DebuggerBDB()
    dbg.register_data_watches(["x"])  # watch variable x

    frame1 = make_frame("foo.py", 10, {"x": 1})
    dbg.botframe = frame1
    dbg.user_line(frame1)  # baseline snapshot only, no stop event expected yet

    # No stopped event yet
    reasons = [
        c.kwargs.get("reason")
        for c in mock_send.call_args_list
        if c.args and c.args[0] == "stopped"
    ]
    assert "data breakpoint" not in reasons

    frame2 = make_frame("foo.py", 11, {"x": 2})  # x changed
    dbg.user_line(frame2)

    reasons = [
        c.kwargs.get("reason")
        for c in mock_send.call_args_list
        if c.args and c.args[0] == "stopped"
    ]
    assert "data breakpoint" in reasons


@patch("dapper.debugger_bdb.send_debug_message")
def test_data_breakpoint_no_trigger_without_change(mock_send):
    dbg = DebuggerBDB()
    dbg.register_data_watches(["x"])  # watch variable x

    frame1 = make_frame("foo.py", 10, {"x": 5})
    dbg.botframe = frame1
    dbg.user_line(frame1)
    frame2 = make_frame("foo.py", 11, {"x": 5})  # same value
    dbg.user_line(frame2)

    # Should not have data breakpoint reason
    reasons = [
        c.kwargs.get("reason")
        for c in mock_send.call_args_list
        if c.args and c.args[0] == "stopped"
    ]
    assert "data breakpoint" not in reasons
