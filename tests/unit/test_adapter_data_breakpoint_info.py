import asyncio

from dapper.adapter.server import DebugAdapterServer
from tests.mocks import MockConnection
from tests.mocks import make_real_frame


def test_server_data_breakpoint_info_includes_type_value():
    # create a fresh event loop for the PyDebugger instance (avoids get_event_loop() issues in test env)
    loop = asyncio.new_event_loop()
    # Create a DebugAdapterServer which constructs a PyDebugger internally
    server = DebugAdapterServer(MockConnection(), loop)
    dbg = server.debugger
    # PyDebugger doesn't statically declare 'current_frame' — use Any to avoid mypy/pyright
    # assign a test frame — cast to FrameLike so static typing accepts it
    dbg.current_frame = make_real_frame({"z": 42})

    out = dbg.data_breakpoint_info(name="z", frame_id=500)
    assert out.get("dataId") == "frame:500:var:z"
    assert out.get("description")
    assert out.get("accessTypes") == ["write"]
    # enriched fields
    assert out.get("type") == "int"
    assert "42" in out.get("value", "")
