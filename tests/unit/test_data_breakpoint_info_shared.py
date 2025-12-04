from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from dapper.shared.command_handlers import _handle_data_breakpoint_info_impl
from tests.mocks import FakeDebugger
from tests.mocks import make_real_frame

if TYPE_CHECKING:
    from dapper.protocol.debugger_protocol import DebuggerLike


def make_frame(locals_map: dict[str, Any], filename: str = "foo.py", lineno: int = 10):
    # keep filename/lineno parameters for callers that expect them and
    # to ensure the returned frame has the right co_filename/f_lineno.
    return make_real_frame(locals_map, filename=filename, lineno=lineno)


def test_data_breakpoint_info_enriched_with_frame_locals():
    dbg = FakeDebugger()
    dbg.current_frame = make_frame({"x": 123})

    res = _handle_data_breakpoint_info_impl(cast("DebuggerLike", dbg), {"name": "x", "frameId": 1})
    assert res["success"] is True
    body = res["body"]
    assert body["dataId"] == "x"
    assert "type" in body
    assert body["type"] == "int"
    assert "value" in body
    assert "123" in body["value"]


def test_data_breakpoint_info_no_local():
    dbg = FakeDebugger()
    dbg.current_frame = make_frame({"y": 1})

    res = _handle_data_breakpoint_info_impl(cast("DebuggerLike", dbg), {"name": "x", "frameId": 1})
    assert res["success"] is True
    body = res["body"]
    assert body["dataId"] == "x"
    assert "type" not in body
    assert "value" not in body
