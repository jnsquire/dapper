from unittest.mock import MagicMock

from dapper.core.debugger_bdb import DebuggerBDB
from tests.mocks import make_real_frame


def make_frame(_filename: str, _lineno: int, locals_dict):
    return make_real_frame(locals_dict)


def test_data_breakpoint_triggers_on_change():
    mock_send = MagicMock()
    dbg = DebuggerBDB(send_message=mock_send)
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


def test_data_breakpoint_no_trigger_without_change():
    mock_send = MagicMock()
    dbg = DebuggerBDB(send_message=mock_send)
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
