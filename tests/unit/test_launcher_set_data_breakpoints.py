import logging
from typing import TYPE_CHECKING
from typing import cast
from unittest.mock import MagicMock

from dapper.core.debugger_bdb import DebuggerBDB
from dapper.shared.variable_handlers import handle_set_data_breakpoints_impl
from tests.mocks import FakeDebugger
from tests.mocks import make_real_frame

if TYPE_CHECKING:
    from dapper.protocol.debugger_protocol import DebuggerLike


def test_set_data_breakpoints_registers_watches_and_calls_set():
    dbg = FakeDebugger()
    args = {
        "breakpoints": [
            {"dataId": "frame:1:var:x", "accessType": "write"},
            {"dataId": "frame:2:var:y", "accessType": "write", "condition": "x > 1"},
            {"dataId": "frame:3:expr:x + y", "accessType": "write"},
        ],
    }

    result = handle_set_data_breakpoints_impl(
        cast("DebuggerLike", dbg),
        args,
        logging.getLogger(__name__),
    )

    # handler returns success and body.breakpoint values
    assert result["success"] is True
    assert len(result["body"]["breakpoints"]) == 3

    # set_data_breakpoint called for both
    assert ("frame:1:var:x", "write") in dbg.set_calls
    assert ("frame:2:var:y", "write") in dbg.set_calls
    assert ("frame:3:expr:x + y", "write") in dbg.set_calls

    # register_data_watches called once with names and metas
    assert len(dbg.register_calls) == 1
    names, metas = dbg.register_calls[0]
    assert set(names) == {"x", "y"}
    # verify that metadata contains dataId and accessType keys
    assert any(m["dataId"].endswith(":var:x") for (_, m) in metas)
    assert "x + y" in dbg.data_bp_state.watch_expressions


def test_set_data_breakpoints_when_set_raises_still_registers():
    dbg = FakeDebugger(raise_on_set=True)
    args = {
        "breakpoints": [
            {"dataId": "frame:10:var:a", "accessType": "write"},
        ],
    }

    result = handle_set_data_breakpoints_impl(
        cast("DebuggerLike", dbg),
        args,
        logging.getLogger(__name__),
    )

    # set_data_breakpoint attempted and raised, but register still called
    assert ("frame:10:var:a", "write") in dbg.set_calls
    assert len(dbg.register_calls) == 1
    names, _metas = dbg.register_calls[0]
    assert names == ["a"]
    assert isinstance(result, dict)
    assert result["success"] is True
    assert len(result["body"]["breakpoints"]) == 1
    assert result["body"]["breakpoints"][0]["verified"] is False


def test_handler_with_real_debugger_triggers_on_change():
    # Simulate launcher mode: handler registers watches on a real DebuggerBDB

    mock_send = MagicMock()
    dbg = DebuggerBDB(send_message=mock_send)

    args = {"breakpoints": [{"dataId": "frame:100:var:x", "accessType": "write"}]}

    res = handle_set_data_breakpoints_impl(
        cast("DebuggerLike", dbg),
        args,
        logging.getLogger(__name__),
    )
    assert res["success"] is True

    # simulate first line (baseline) then changed value
    frame1 = make_real_frame({"x": 1})

    dbg.botframe = frame1
    dbg.user_line(frame1)

    # no stopped event yet
    reasons = [
        c.kwargs.get("reason")
        for c in mock_send.call_args_list
        if c.args and c.args[0] == "stopped"
    ]
    assert "data breakpoint" not in reasons

    frame2 = make_real_frame({"x": 2})

    dbg.user_line(frame2)

    reasons = [
        c.kwargs.get("reason")
        for c in mock_send.call_args_list
        if c.args and c.args[0] == "stopped"
    ]
    assert "data breakpoint" in reasons
