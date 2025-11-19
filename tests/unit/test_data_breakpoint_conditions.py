from types import FrameType
from unittest.mock import MagicMock
from unittest.mock import patch

from dapper.core.debugger_bdb import DebuggerBDB


def make_frame(filename: str, lineno: int, locals_dict):
    frame = MagicMock(spec=FrameType)
    frame.f_code.co_filename = filename  # type: ignore[attr-defined]
    frame.f_lineno = lineno
    frame.f_locals = locals_dict
    frame.f_globals = {"__builtins__": __builtins__}
    return frame


@patch("dapper.core.debugger_bdb.send_debug_message")
def test_data_breakpoint_hit_condition_every_other_change(mock_send):
    dbg = DebuggerBDB()
    meta = {"condition": None, "hitCondition": "% 2", "hit": 0}
    dbg.register_data_watches(["x"], [("x", meta)])

    # baseline
    frame1 = make_frame("foo.py", 10, {"x": 1})
    # ensure bdb has a bottom frame reference before invoking user_line
    dbg.botframe = frame1
    dbg.user_line(frame1)
    # first change (hit=1) should NOT trigger because % 2 condition requires hit_count % 2 == 0
    frame2 = make_frame("foo.py", 11, {"x": 2})
    dbg.user_line(frame2)

    # second change (hit=2) should trigger
    frame3 = make_frame("foo.py", 12, {"x": 3})
    dbg.user_line(frame3)

    reasons = [
        c.kwargs.get("reason")
        for c in mock_send.call_args_list
        if c.args and c.args[0] == "stopped"
    ]
    assert reasons.count("data breakpoint") == 1


@patch("dapper.core.debugger_bdb.send_debug_message")
def test_data_breakpoint_with_condition_expression(mock_send):
    dbg = DebuggerBDB()
    meta = {"condition": "x > 3", "hitCondition": None, "hit": 0}
    dbg.register_data_watches(["x"], [("x", meta)])

    # baseline
    frame1 = make_frame("foo.py", 10, {"x": 1})
    dbg.botframe = frame1
    dbg.user_line(frame1)
    # change but condition false (x=2)
    dbg.user_line(make_frame("foo.py", 11, {"x": 2}))
    # change and condition still false (x=3)
    dbg.user_line(make_frame("foo.py", 12, {"x": 3}))
    # change and condition true now (x=4) -> should stop
    dbg.user_line(make_frame("foo.py", 13, {"x": 4}))

    reasons = [
        c.kwargs.get("reason")
        for c in mock_send.call_args_list
        if c.args and c.args[0] == "stopped"
    ]
    assert reasons.count("data breakpoint") == 1
