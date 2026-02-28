from typing import Any

from dapper.shared.command_handlers import _TRUNC_SUFFIX
from dapper.shared.command_handlers import MAX_VALUE_REPR_LEN
from dapper.shared.debug_shared import DebugSession
from dapper.shared.variable_handlers import handle_data_breakpoint_info_impl
from tests.mocks import FakeDebugger
from tests.mocks import make_real_frame


def make_frame(locals_map: dict[str, Any], filename: str = "foo.py", lineno: int = 10):
    # keep filename/lineno parameters for callers that expect them and
    # to ensure the returned frame has the right co_filename/f_lineno.
    return make_real_frame(locals_map, filename=filename, lineno=lineno)


def _make_session(dbg) -> DebugSession:
    session = DebugSession()
    session.debugger = dbg
    return session


def test_data_breakpoint_info_enriched_with_frame_locals():
    dbg = FakeDebugger()
    dbg.current_frame = make_frame({"x": 123})
    session = _make_session(dbg)

    res = handle_data_breakpoint_info_impl(
        session,
        {"name": "x", "frameId": 1},
        max_value_repr_len=MAX_VALUE_REPR_LEN,
        trunc_suffix=_TRUNC_SUFFIX,
    )
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
    session = _make_session(dbg)

    res = handle_data_breakpoint_info_impl(
        session,
        {"name": "x", "frameId": 1},
        max_value_repr_len=MAX_VALUE_REPR_LEN,
        trunc_suffix=_TRUNC_SUFFIX,
    )
    assert res["success"] is True
    body = res["body"]
    assert body["dataId"] == "x"
    assert "type" not in body
    assert "value" not in body
