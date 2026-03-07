from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from dapper.core.debugger_bdb import DebuggerBDB
from dapper.shared import command_handler_helpers
from dapper.shared import command_handlers as handlers
from dapper.shared import debug_shared
from dapper.shared import lifecycle_handlers
from dapper.shared import source_handlers
from dapper.shared import stack_handlers
from dapper.shared import variable_handlers
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


@pytest.fixture(autouse=True)
def use_debug_session():
    session = debug_shared.DebugSession()
    with debug_shared.use_session(session):
        yield session


def _session_with_debugger(session: debug_shared.DebugSession, dbg):
    session.debugger = dbg
    return session, dbg


def test_handle_initialize_minimal():
    res = lifecycle_handlers.handle_initialize_impl()
    assert isinstance(res, dict)
    assert res["success"] is True
    body = res["body"]
    assert body["supportsConfigurationDoneRequest"] is True


def test_handle_threads_empty(use_debug_session):
    s, _dbg = _session_with_debugger(use_debug_session, DebuggerBDB())
    s.transport.send = lambda *_a, **_kw: None  # type: ignore[assignment]
    # No threads
    res = stack_handlers.handle_threads_impl(s, {})
    assert res["success"] is True
    assert res["body"]["threads"] == []


def test_handle_scopes_and_variables(use_debug_session):
    s, dbg = _session_with_debugger(use_debug_session, DummyDebugger())
    s.transport.send = lambda *_a, **_kw: None  # type: ignore[assignment]

    frame = MockFrame(
        _locals={"a": 1, "b": [1, 2, 3]},
        _globals={"g": "x"},
        name="test_func",
        filename="sample.py",
        lineno=10,
    )

    # Register frame
    dbg.frame_id_to_frame[1] = frame

    # Request scopes for frame id 1
    res = stack_handlers.handle_scopes_impl(
        s,
        {"frameId": 1},
    )
    assert res["success"] is True
    scopes = res["body"]["scopes"]
    assert any(s.get("name") == "Locals" for s in scopes)
    # Now request variables for locals scope
    locals_ref = next(s.get("variablesReference") for s in scopes if s.get("name") == "Locals")

    vars_res = variable_handlers.handle_variables_impl(
        use_debug_session,
        {"variablesReference": locals_ref},
        lambda runtime_dbg, frame_info: (
            handlers.command_handler_helpers.resolve_variables_for_reference(
                runtime_dbg,
                frame_info,
                make_variable_fn=command_handler_helpers.make_variable,
                extract_variables_from_mapping_fn=lambda helper_dbg, mapping, frame: (
                    command_handler_helpers.extract_variables_from_mapping(
                        helper_dbg,
                        mapping,
                        frame,
                        make_variable_fn=command_handler_helpers.make_variable,
                    )
                ),
            )
        ),
    )
    # handle_variables now returns a result dict with the variables data
    assert vars_res is not None
    assert vars_res["success"] is True
    assert "variables" in vars_res["body"]


def test_handle_source_reads_file(tmp_path: Path, use_debug_session):
    # Create a temp file
    p = tmp_path / "sample.txt"
    p.write_text("hello world", encoding="utf-8")
    res = source_handlers.handle_legacy_source(
        {"path": str(p)},
        use_debug_session,
    )
    assert res["success"] is True
    assert "hello world" in res["body"]["content"]


def test_handle_source_resolves_source_reference_from_state(tmp_path: Path, use_debug_session):
    # Create a temp file and register it in the session state
    p = tmp_path / "sample_ref.txt"
    p.write_text("hello reference", encoding="utf-8")

    # Register a sourceReference for the path and ensure the legacy
    # source handler path honours it.
    ref = use_debug_session.get_or_create_source_ref(str(p), p.name)

    res = source_handlers.handle_legacy_source(
        {"sourceReference": ref},
        use_debug_session,
    )
    assert res["success"] is True
    assert "hello reference" in res["body"]["content"]


def test_set_data_breakpoints_and_info(use_debug_session):
    s, _dbg = _session_with_debugger(use_debug_session, DebuggerBDB())

    bps = [{"name": "x", "dataId": "d1"}, {"name": "y"}]
    res = variable_handlers.handle_set_data_breakpoints_impl(
        s,
        {"breakpoints": bps},
        handlers.logger,
    )
    assert res["success"] is True
    body = res["body"]
    assert "breakpoints" in body
    # dataBreakpointInfo
    info = variable_handlers.handle_data_breakpoint_info_impl(
        s,
        {"name": "x"},
        max_value_repr_len=handlers.MAX_VALUE_REPR_LEN,
        trunc_suffix=handlers._TRUNC_SUFFIX,
    )
    assert info["success"] is True
    assert info["body"]["dataId"] == "x"


def test_handle_terminate_marks_session_and_emits_exit_event(use_debug_session):
    s, _dbg = _session_with_debugger(use_debug_session, DummyDebugger())

    sent_messages: list[tuple[str, dict[str, object]]] = []

    def record_send(message_type: str, **payload: object) -> None:
        sent_messages.append((message_type, payload))

    s.transport.send = record_send  # type: ignore[assignment]
    s.ipc_enabled = True
    s.ipc_wfile = object()

    result = lifecycle_handlers.handle_terminate_impl(state=s)

    assert result == {"success": True}
    assert s.is_terminated is True
    assert sent_messages == [("exited", {"exitCode": 0})]


def test_handle_restart_cleans_up_resources_and_execs(use_debug_session):
    s, _dbg = _session_with_debugger(use_debug_session, DummyDebugger())

    sent_messages: list[tuple[str, dict[str, object]]] = []
    exec_calls: list[tuple[str, list[str]]] = []

    def record_send(message_type: str, **payload: object) -> None:
        sent_messages.append((message_type, payload))

    class Closable:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class JoinableThread:
        def __init__(self) -> None:
            self.join_calls: list[float] = []

        def is_alive(self) -> bool:
            return True

        def join(self, timeout: float | None = None) -> None:
            self.join_calls.append(timeout if timeout is not None else -1.0)

    ipc_pipe_conn = Closable()
    ipc_wfile = Closable()
    ipc_rfile = Closable()
    command_thread = JoinableThread()

    def fake_exec(path: str, args: list[str]) -> None:
        exec_calls.append((path, args))

    s.transport.send = record_send  # type: ignore[assignment]
    s.ipc_enabled = True
    s.ipc_pipe_conn = ipc_pipe_conn
    s.ipc_wfile = ipc_wfile
    s.ipc_rfile = ipc_rfile
    s.command_thread = command_thread  # type: ignore[assignment]
    s.set_exec_func(fake_exec)

    original_argv = sys.argv[:]
    sys.argv[:] = ["launcher.py", "--program", "sample.py", "--ipc", "tcp"]
    try:
        result = lifecycle_handlers.handle_restart_impl(state=s, logger=handlers.logger)
    finally:
        sys.argv[:] = original_argv

    assert result == {"success": True}
    assert s.is_terminated is True
    assert sent_messages == [("exited", {"exitCode": 0})]
    assert ipc_pipe_conn.closed is True
    assert ipc_wfile.closed is True
    assert ipc_rfile.closed is True
    assert s.ipc_pipe_conn is None
    assert s.ipc_wfile is None
    assert s.ipc_rfile is None
    assert s.ipc_enabled is False
    assert command_thread.join_calls == [0.1]
    assert s.command_thread is None
    assert exec_calls == [
        (
            sys.executable,
            [sys.executable, "--program", "sample.py", "--ipc", "tcp"],
        )
    ]


def test_handle_restart_ignores_non_alive_command_thread(use_debug_session):
    s, _dbg = _session_with_debugger(use_debug_session, DummyDebugger())

    exec_calls: list[tuple[str, list[str]]] = []

    class NotAliveThread:
        def __init__(self) -> None:
            self.join_called = False

        def is_alive(self) -> bool:
            return False

        def join(self, _timeout: float | None = None) -> None:
            self.join_called = True

    command_thread = NotAliveThread()

    def fake_exec(path: str, args: list[str]) -> None:
        exec_calls.append((path, args))

    s.transport.send = lambda *_a, **_kw: None  # type: ignore[assignment]
    s.ipc_enabled = True
    s.ipc_wfile = object()
    s.command_thread = command_thread  # type: ignore[assignment]
    s.set_exec_func(fake_exec)

    original_argv = sys.argv[:]
    sys.argv[:] = ["launcher.py"]
    try:
        result = lifecycle_handlers.handle_restart_impl(state=s, logger=handlers.logger)
    finally:
        sys.argv[:] = original_argv

    assert result == {"success": True}
    assert command_thread.join_called is False
    assert s.command_thread is None
    assert exec_calls == [(sys.executable, [sys.executable])]
