import asyncio
import contextlib
from unittest.mock import patch

import pytest

from dapper.server import DebugAdapterServer
from dapper.server import PyDebugger as RealDebugger
from tests.mocks import MockConnection


@pytest.mark.asyncio
@patch("dapper.server.PyDebugger")
async def test_data_breakpoint_info_and_set(mock_debugger_class):
    mock_debugger = mock_debugger_class.return_value

    async def _noop_shutdown():
        return None

    mock_debugger.shutdown = _noop_shutdown  # type: ignore[assignment]

    async def dummy_eval(*_args, **_kwargs):
        return {"result": "0", "variablesReference": 0}

    mock_debugger.evaluate = dummy_eval  # type: ignore[assignment]

    # Use real implementations for our added helper methods by attaching attributes
    real_dbg = RealDebugger(None, asyncio.get_event_loop())
    mock_debugger.data_breakpoint_info = real_dbg.data_breakpoint_info  # type: ignore[assignment]
    mock_debugger.set_data_breakpoints = real_dbg.set_data_breakpoints  # type: ignore[assignment]

    conn = MockConnection()
    server = DebugAdapterServer(conn, asyncio.get_event_loop())
    server.debugger = mock_debugger

    # Initialize then request dataBreakpointInfo and setDataBreakpoints
    conn.add_request("initialize", seq=1)
    # Minimal launch to keep server expected flow simpler (program required by launch handler)
    conn.add_request("launch", {"program": "foo.py"}, seq=2)
    conn.add_request("configurationDone", seq=3)
    conn.add_request("dataBreakpointInfo", {"name": "x", "frameId": 42}, seq=4)
    # Use the dataId returned from info to set
    # We'll just guess expected pattern (frame:42:var:x) for simplicity
    conn.add_request("setDataBreakpoints", {"breakpoints": [{"dataId": "frame:42:var:x"}]}, seq=5)

    task = asyncio.create_task(server.start())
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(task, timeout=1.0)

    # Collect responses keyed by command
    responses = {m["command"]: m for m in conn.written_messages if m.get("type") == "response"}

    assert "initialize" in responses
    assert responses["initialize"]["success"] is True
    caps = responses["initialize"]["body"]
    assert caps.get("supportsDataBreakpoints") is True
    assert caps.get("supportsDataBreakpointInfo") is True

    assert "dataBreakpointInfo" in responses
    info_body = responses["dataBreakpointInfo"]["body"]
    assert info_body["dataId"].startswith("frame:42:var:x")
    assert info_body["accessTypes"] == ["write"]

    assert "setDataBreakpoints" in responses
    sdb_body = responses["setDataBreakpoints"]["body"]
    assert sdb_body["breakpoints"][0]["verified"] is True

    # Ensure the watch was registered in the debugger's internal mapping
    assert "frame:42:var:x" in real_dbg._data_watches  # type: ignore[attr-defined]
