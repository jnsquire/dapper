from __future__ import annotations

import threading
from typing import Any
from typing import cast

from dapper.inprocess_debugger import InProcessDebugger
from tests.dummy_debugger import DummyDebugger


class FakeFrame:
    def __init__(self, locals_: dict | None = None, globals_: dict | None = None):
        self.f_locals = locals_ or {}
        self.f_globals = globals_ or {}


# Use the shared DummyDebugger in tests for a fully-featured debugger-like
# object. We subclass in tests when we need to tweak behavior (e.g. failing
# set_break).
class FakeDebugger(DummyDebugger):
    def __init__(self) -> None:
        super().__init__()
        # Use simple frame mapping like previous tests
        self.frames_by_thread = {}
        self.frame_id_to_frame = {}
        self.var_refs = {}


def test_event_emitters_exist_and_work():
    ip = InProcessDebugger()
    got = {}

    def on_output(cat, out):
        got["cat"] = cat
        got["out"] = out

    ip.on_output.add_listener(on_output)
    # emit directly via the EventEmitter
    ip.on_output.emit("stdout", "hello")
    assert got == {"cat": "stdout", "out": "hello"}


def test_set_breakpoints_delegates_to_debugger():
    ip = InProcessDebugger()
    fake = FakeDebugger()
    ip.debugger = cast("Any", fake)

    bps = ip.set_breakpoints("/tmp/foo.py", [{"line": 10}, {"line": 20, "condition": "x>0"}])
    # returned shape
    assert isinstance(bps, list)
    assert bps[0]["verified"] is True
    # underlying debugger saw the clear and sets (DummyDebugger uses
    # `cleared` and the `breaks` container)
    assert fake.cleared == ["/tmp/foo.py"]
    assert ("/tmp/foo.py", 10, None) in fake.breaks
    assert ("/tmp/foo.py", 20, "x>0") in fake.breaks


def test_set_breakpoints_handles_failed_install():
    ip = InProcessDebugger()

    class BadSetDebugger(FakeDebugger):
        def set_break(self, path: str, line: int, cond: object | None = None) -> bool:  # type: ignore[override]
            # Simulate failure for line 20 only
            super().set_break(path, line, cond=cond)
            return line != 20

    fake = BadSetDebugger()
    ip.debugger = cast("Any", fake)

    bps = ip.set_breakpoints("/tmp/foo.py", [{"line": 10}, {"line": 20}])
    assert isinstance(bps, list)
    # first should be verified, second not
    assert bps[0]["verified"] is True
    assert bps[1]["verified"] is False


def test_variables_and_stack_trace_and_evaluate_and_set_variable():
    ip = InProcessDebugger()
    fake = FakeDebugger()
    ip.debugger = cast("Any", fake)

    # prepare a frame and var refs
    frame = FakeFrame(locals_={"a": 123}, globals_={})
    fake.frame_id_to_frame[1] = frame
    fake.var_refs[42] = (1, "locals")

    # variables should call make_variable_object
    vars_resp = ip.variables(42)
    assert any(v["name"] == "a" for v in vars_resp["variables"])

    # stack_trace for a thread
    tid = threading.get_ident()
    fake.frames_by_thread[tid] = ["frame1", "frame2", "frame3"]
    st = ip.stack_trace(tid, start_frame=1, levels=1)
    assert st.get("totalFrames") == 3
    assert st.get("stackFrames") == ["frame2"]

    # evaluate with missing frame
    missing = ip.evaluate("1+1", frame_id=999)
    assert "not available" in missing.get("result", "")

    # evaluate with existing frame - use frame that has a global x
    frame2 = FakeFrame(locals_={}, globals_={"g": 7})
    fake.frame_id_to_frame[2] = frame2
    res = ip.evaluate("g+1", frame_id=2)
    assert res.get("result") == repr(8)

    # set_variable success
    frame3 = FakeFrame(locals_={}, globals_={})
    fake.frame_id_to_frame[3] = frame3
    fake.var_refs[99] = (3, "globals")
    set_resp = ip.set_variable(99, "new", "5")
    assert set_resp.get("value") == 5
    assert set_resp.get("type") == "int"

    # invalid var ref
    bad = ip.set_variable(1234, "x", "1")
    assert bad.get("success") is False


def test_continue_removes_thread_and_calls_set_continue():
    ip = InProcessDebugger()
    fake = FakeDebugger()
    ip.debugger = cast("Any", fake)

    tid = threading.get_ident()
    fake.stopped_thread_ids = {tid}
    resp = ip.continue_(tid)
    assert resp.get("allThreadsContinued") is True
    # stopped list should be emptied and set_continue called
    assert fake._continued is True


def test_stack_trace_empty_for_unknown_thread():
    ip = InProcessDebugger()
    fake = FakeDebugger()
    ip.debugger = cast("Any", fake)
    resp = ip.stack_trace(9999)
    assert resp.get("stackFrames") == []
    assert resp.get("totalFrames") == 0
