from typing import TYPE_CHECKING
from typing import cast
from unittest.mock import MagicMock

from dapper.core.debugger_bdb import DebuggerBDB
from dapper.shared import launcher_handlers
from tests.mocks import FakeDebugger
from tests.mocks import make_real_frame

if TYPE_CHECKING:
    from dapper.protocol.debugger_protocol import DebuggerLike


def test_launcher_handler_registers_and_calls_set():
    dbg = FakeDebugger()
    args = {"breakpoints": [{"dataId": "frame:1:var:x", "accessType": "write"}]}

    result = launcher_handlers.handle_set_data_breakpoints(cast("DebuggerLike", dbg), args)

    assert result["success"] is True
    assert len(result["body"]["breakpoints"]) == 1
    assert ("frame:1:var:x", "write") in dbg.set_calls
    assert len(dbg.register_calls) == 1
    names, metas = dbg.register_calls[0]
    assert names == ["x"]


def test_launcher_handler_with_real_debugger_triggers():
    mock_send = MagicMock()
    dbg = DebuggerBDB(send_message=mock_send)

    args = {"breakpoints": [{"dataId": "frame:500:var:z", "accessType": "write"}]}
    res = launcher_handlers.handle_set_data_breakpoints(cast("DebuggerLike", dbg), args)
    assert res["success"] is True

    frame1 = make_real_frame({"z": 1})

    dbg.botframe = frame1
    dbg.user_line(frame1)

    # no stop yet
    reasons = [c.kwargs.get("reason") for c in mock_send.call_args_list if c.args and c.args[0] == "stopped"]
    assert "data breakpoint" not in reasons

    frame2 = make_real_frame({"z": 2})

    dbg.user_line(frame2)

    reasons = [c.kwargs.get("reason") for c in mock_send.call_args_list if c.args and c.args[0] == "stopped"]
    assert "data breakpoint" in reasons
