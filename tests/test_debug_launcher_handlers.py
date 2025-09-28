from __future__ import annotations

from queue import Queue
from typing import TYPE_CHECKING
from typing import Any

from dapper import debug_launcher
from dapper import debug_shared

if TYPE_CHECKING:
    from pathlib import Path


class DummyDebugger:
    def __init__(self):
        self.next_var_ref = 1000
        self.var_refs: dict[int, Any] = {}
        self.frames_by_thread: dict[int, list] = {}
        self.frame_id_to_frame: dict[int, Any] = {}
        self.threads: dict[int, Any] = {}
        self.data_breakpoints: list[dict[str, Any]] | None = []
        self.current_exception_info: dict[str, Any] = {}
        self.current_frame: Any | None = None
        self.stepping: bool = False
        self.cleared: list[str] = []
        self.breaks: dict[str, list[tuple[int, Any | None]]] = {}
        # Breakpoint bookkeeping
        self.function_breakpoints: list[str] = []
        self.function_breakpoint_meta: dict[str, dict[str, Any]] = {}
        self.breakpoint_meta: dict[tuple[str, int], dict[str, Any]] = {}
        self.exception_breakpoints_raised = False
        self.exception_breakpoints_uncaught = False
        self.stopped_thread_ids: set[int] = set()

    def set_break(
        self,
        filename: str,
        lineno: int,
        temporary: bool = False,
        cond: Any | None = None,
        funcname: str | None = None,
    ) -> Any | None:  # type: ignore[override]
        _ = temporary, funcname
        arr = self.breaks.get(filename)
        if arr is None:
            self.breaks[filename] = [(int(lineno), cond)]
        else:
            arr.append((int(lineno), cond))
        return None

    def record_breakpoint(
        self,
        path: str,
        line: int,
        *,
        condition: Any | None = None,
        hit_condition: Any | None = None,
        log_message: Any | None = None,
    ) -> None:
        self.breakpoint_meta[(path, line)] = {
            "condition": condition,
            "hit_condition": hit_condition,
            "log_message": log_message,
        }

    def clear_breaks_for_file(self, path: str) -> None:
        # No-op for the dummy
        pass

    def clear_break(self, filename: str, lineno: int) -> Any | None:
        _ = lineno, filename
        return None

    def clear_break_meta_for_file(self, path: str) -> None:
        to_del = [k for k in list(self.breakpoint_meta.keys()) if k[0] == path]
        for k in to_del:
            self.breakpoint_meta.pop(k, None)

    def clear_all_function_breakpoints(self) -> None:
        self.function_breakpoints = []
        self.function_breakpoint_meta.clear()

    def set_continue(self) -> None:
        _ = None

    def set_next(self, frame: Any) -> None:
        _ = frame

    def set_step(self) -> None:
        _ = None

    def set_return(self, frame: Any) -> None:
        _ = frame

    def run(self, cmd: Any, *args: Any, **kwargs: Any) -> Any:
        _ = cmd, args, kwargs
        return None

    def make_variable_object(
        self, name: Any, value: Any, frame: Any | None = None, *, max_string_length: int = 1000
    ) -> dict[str, Any]:
        # Delegate to debug_shared helper for consistent behavior in tests
        from dapper import debug_shared  # noqa: PLC0415

        return debug_shared.make_variable_object(
            name, value, self, frame, max_string_length=max_string_length
        )

    def create_variable_object(
        self, name: Any, value: Any, frame: Any | None = None, *, max_string_length: int = 1000
    ) -> dict[str, Any]:
        return self.make_variable_object(name, value, frame, max_string_length=max_string_length)


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
