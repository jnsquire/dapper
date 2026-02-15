from __future__ import annotations

from queue import Queue
from typing import TYPE_CHECKING

from dapper.shared import command_handlers as handlers
from dapper.shared import debug_shared
from dapper.shared import lifecycle_handlers
from dapper.shared import source_handlers
from dapper.shared import stack_handlers
from dapper.shared import variable_command_runtime
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
    res = lifecycle_handlers.handle_initialize_impl()
    assert isinstance(res, dict)
    assert res["success"] is True
    body = res["body"]
    assert body["supportsConfigurationDoneRequest"] is True
    assert "supportsRestartRequest" in body


def test_handle_threads_empty():
    s = debug_shared.state
    s.debugger = DummyDebugger()
    # No threads
    res = stack_handlers.handle_threads_impl(s.debugger, {}, handlers._safe_send_debug_message)
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
            variable_command_runtime.resolve_variables_for_reference_runtime(
                runtime_dbg,
                frame_info,
                resolve_variables_helper=handlers.command_handler_helpers.resolve_variables_for_reference,
                extract_variables_from_mapping_helper=handlers.command_handler_helpers.extract_variables_from_mapping,
                make_variable_fn=lambda helper_dbg, name, value, frame: (
                    variable_command_runtime.make_variable_runtime(
                        helper_dbg,
                        name,
                        value,
                        frame,
                        make_variable_helper=handlers.command_handler_helpers.make_variable,
                        fallback_make_variable=debug_shared.make_variable_object,
                        simple_fn_argcount=handlers.SIMPLE_FN_ARGCOUNT,
                    )
                ),
                var_ref_tuple_size=handlers.VAR_REF_TUPLE_SIZE,
            )
        ),
    )
    # handle_variables sends a message rather than returning a value; ensure no exception
    assert vars_res is None


def test_handle_source_reads_file(tmp_path: Path):
    # Create a temp file
    p = tmp_path / "sample.txt"
    p.write_text("hello world", encoding="utf-8")
    res = source_handlers.handle_legacy_source(
        {"path": str(p)},
        debug_shared.state,
        lambda *_args, **_kwargs: True,
    )
    assert res["success"] is True
    assert "hello world" in res["body"]["content"]


def test_handle_source_resolves_source_reference_from_state(tmp_path: Path):
    # Create a temp file and register it in the session state
    p = tmp_path / "sample_ref.txt"
    p.write_text("hello reference", encoding="utf-8")

    # Register a sourceReference for the path and ensure the legacy
    # source handler path honours it.
    ref = debug_shared.state.get_or_create_source_ref(str(p), p.name)

    res = source_handlers.handle_legacy_source(
        {"sourceReference": ref},
        debug_shared.state,
        lambda *_args, **_kwargs: True,
    )
    assert res["success"] is True
    assert "hello reference" in res["body"]["content"]


def test_set_data_breakpoints_and_info():
    s = debug_shared.state
    dbg = DummyDebugger()
    s.debugger = dbg

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
