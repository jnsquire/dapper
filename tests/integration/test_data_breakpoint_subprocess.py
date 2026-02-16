from typing import TYPE_CHECKING
from typing import cast
from unittest.mock import MagicMock

from dapper.core.debugger_bdb import DebuggerBDB
from dapper.shared import command_handlers
from dapper.shared import debug_shared
from tests.mocks import make_real_frame

if TYPE_CHECKING:
    from dapper.protocol.debugger_protocol import DebuggerLike


def _active_session_with_debugger(
    dbg: DebuggerBDB,
) -> tuple[debug_shared.DebugSession, DebuggerBDB]:
    session = debug_shared.DebugSession()
    session.debugger = cast("DebuggerLike", dbg)
    return session, dbg


def test_set_data_breakpoints_command_registers_and_triggers():
    # Arrange - put a real DebuggerBDB into an explicit debug session
    mock_send = MagicMock()
    session, dbg = _active_session_with_debugger(DebuggerBDB(send_message=mock_send))

    with debug_shared.use_session(session):
        # Act - send the setDataBreakpoints command via standard command dispatcher
        cmd = {
            "command": "setDataBreakpoints",
            "arguments": {"breakpoints": [{"dataId": "frame:999:var:q", "accessType": "write"}]},
        }
        command_handlers.handle_debug_command(cmd)

        # Simulate program running with change
        frame1 = make_real_frame({"q": 1})

        dbg.botframe = frame1
        dbg.user_line(frame1)

        # no stopped event yet
        reasons = [
            c.kwargs.get("reason")
            for c in mock_send.call_args_list
            if c.args and c.args[0] == "stopped"
        ]
        assert "data breakpoint" not in reasons

        frame2 = make_real_frame({"q": 2})

        dbg.user_line(frame2)

        reasons = [
            c.kwargs.get("reason")
            for c in mock_send.call_args_list
            if c.args and c.args[0] == "stopped"
        ]
        assert "data breakpoint" in reasons
