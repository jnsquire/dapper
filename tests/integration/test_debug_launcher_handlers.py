from __future__ import annotations

from queue import Queue
from typing import TYPE_CHECKING

from dapper import debug_launcher
from dapper import debug_shared
from tests.dummy_debugger import DummyDebugger

if TYPE_CHECKING:
    from pathlib import Path


# Create a realistic mock frame object with a code object and line info
class MockCode:
    def __init__(self, name="test_func", filename="<test>", firstlineno=1):
        self.co_name = name
        self.co_filename = filename
        self.co_firstlineno = firstlineno


class MockFrame:
    def __init__(
        self,
        _locals: dict | None = None,
        _globals: dict | None = None,
        name="test_func",
        filename="<test>",
        lineno=1,
    ):
        self.f_locals = dict(_locals or {})
        self.f_globals = dict(_globals or {})
        self.f_code = MockCode(name=name, filename=filename, firstlineno=lineno)
        self.f_lineno = lineno
        self.f_back = None

    def __repr__(self):
        return f"<MockFrame {self.f_code.co_name} at {self.f_code.co_filename}:{self.f_lineno}>"


def setup_function(_func):
    # Reset singleton session state for each test
    s = debug_shared.state
    s.debugger = None
    s.is_terminated = False
    s.ipc_enabled = False
    s.ipc_rfile = None
    s.ipc_wfile = None
    s.command_queue = Queue()


def test_handle_initialize_minimal():
    # pass a dummy debugger instance as the first parameter
    res = debug_launcher.handle_initialize(DummyDebugger(), {})
    assert isinstance(res, dict)
    assert res["success"] is True
    body = res["body"]
    assert body["supportsConfigurationDoneRequest"] is True
    assert "supportsRestartRequest" in body


def test_handle_threads_empty():
    s = debug_shared.state
    s.debugger = DummyDebugger()
    # No threads
    res = debug_launcher.handle_threads(s.debugger, {})
    assert res["success"] is True
    assert res["body"]["threads"] == []


def test_handle_scopes_and_variables():
    s = debug_shared.state
    dbg = DummyDebugger()

    frame = MockFrame(
        _locals={"a": 1, "b": [1, 2, 3]},
        _globals={"g": "x"},
        name="test_func",
        filename="sample.py",
        lineno=10,
    )

    # Register frame
    dbg.frame_id_to_frame[1] = frame
    s.debugger = dbg

    # Request scopes for frame id 1
    res = debug_launcher.handle_scopes(dbg, {"frameId": 1})
    assert res["success"] is True
    scopes = res["body"]["scopes"]
    assert any(s.get("name") == "Locals" for s in scopes)
    # Now request variables for locals scope
    locals_ref = next(s.get("variablesReference") for s in scopes if s.get("name") == "Locals")

    vars_res = debug_launcher.handle_variables(dbg, {"variablesReference": locals_ref})
    # handle_variables sends a message rather than returning a value; ensure no exception
    assert vars_res is None


def test_handle_source_reads_file(tmp_path: Path):
    # Create a temp file
    p = tmp_path / "sample.txt"
    p.write_text("hello world", encoding="utf-8")
    # source handler doesn't use the debugger but still expects it as first arg
    res = debug_launcher.handle_source(DummyDebugger(), {"path": str(p)})
    assert res["success"] is True
    assert "hello world" in res["body"]["content"]


def test_set_data_breakpoints_and_info():
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

    bps = [{"name": "x", "dataId": "d1"}, {"name": "y"}]
    res = debug_launcher.handle_set_data_breakpoints(dbg, {"breakpoints": bps})
    assert res["success"] is True
    body = res["body"]
    assert "breakpoints" in body
    # dataBreakpointInfo
    info = debug_launcher.handle_data_breakpoint_info(dbg, {"name": "x"})
    assert info["success"] is True
    assert info["body"]["dataId"] == "x"


# TODO: more tests for restart/terminate behavior would require process-level integration
