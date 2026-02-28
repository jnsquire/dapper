from __future__ import annotations

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
    assert "supportsRestartRequest" in body


def test_handle_threads_empty(use_debug_session):
    s, _dbg = _session_with_debugger(use_debug_session, DebuggerBDB())
    # No threads
    res = stack_handlers.handle_threads_impl(s.debugger, {}, handlers._safe_send_debug_message)
    assert res["success"] is True
    assert res["body"]["threads"] == []


def test_handle_scopes_and_variables(use_debug_session):
    _s, dbg = _session_with_debugger(use_debug_session, DummyDebugger())

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
        dbg,
        {"frameId": 1},
        safe_send_debug_message=handlers._safe_send_debug_message,
        var_ref_tuple_size=handlers.VAR_REF_TUPLE_SIZE,
    )
    assert res["success"] is True
    scopes = res["body"]["scopes"]
    assert any(s.get("name") == "Locals" for s in scopes)
    # Now request variables for locals scope
    locals_ref = next(s.get("variablesReference") for s in scopes if s.get("name") == "Locals")

    vars_res = variable_handlers.handle_variables_impl(
        dbg,
        {"variablesReference": locals_ref},
        handlers._safe_send_debug_message,
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
                var_ref_tuple_size=handlers.VAR_REF_TUPLE_SIZE,
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
        lambda *_args, **_kwargs: True,
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
        lambda *_args, **_kwargs: True,
    )
    assert res["success"] is True
    assert "hello reference" in res["body"]["content"]


def test_set_data_breakpoints_and_info(use_debug_session):
    _s, dbg = _session_with_debugger(use_debug_session, DebuggerBDB())

    bps = [{"name": "x", "dataId": "d1"}, {"name": "y"}]
    res = variable_handlers.handle_set_data_breakpoints_impl(
        dbg,
        {"breakpoints": bps},
        handlers.logger,
    )
    assert res["success"] is True
    body = res["body"]
    assert "breakpoints" in body
    # dataBreakpointInfo
    info = variable_handlers.handle_data_breakpoint_info_impl(
        dbg,
        {"name": "x"},
        max_value_repr_len=handlers.MAX_VALUE_REPR_LEN,
        trunc_suffix=handlers._TRUNC_SUFFIX,
    )
    assert info["success"] is True
    assert info["body"]["dataId"] == "x"


# TODO: more tests for restart/terminate behavior would require process-level integration
