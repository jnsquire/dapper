from __future__ import annotations

import linecache
from pathlib import Path
import sys
import tempfile
import threading
import types
from types import SimpleNamespace
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

import pytest

from dapper.core.debugger_bdb import DebuggerBDB
from dapper.shared import breakpoint_handlers
from dapper.shared import command_handler_helpers
from dapper.shared import command_handlers as dch
from dapper.shared import debug_shared
from dapper.shared import lifecycle_handlers
from dapper.shared import source_handlers
from dapper.shared import stepping_handlers
from dapper.shared import variable_handlers
from dapper.shared.value_conversion import convert_value_with_context
from tests.dummy_debugger import DummyDebugger

if TYPE_CHECKING:
    from dapper.protocol.debugger_protocol import Variable
    from dapper.protocol.requests import ExceptionInfoArguments

    # DAP argument shapes used by handlers (only for type-checking)
    from dapper.protocol.requests import SetBreakpointsArguments
    from dapper.protocol.requests import SetExceptionBreakpointsArguments
    from dapper.protocol.requests import SetFunctionBreakpointsArguments


_CONVERSION_FAILED = object()


@pytest.fixture(autouse=True)
def _isolated_active_session():
    """Run each test with an isolated explicit DebugSession."""
    session = debug_shared.DebugSession()
    with debug_shared.use_session(session):
        yield session


def _active_session_with_debugger(dbg: Any) -> tuple[debug_shared.DebugSession, Any]:
    session = dch._active_session()
    session.debugger = dbg
    return session, dbg


def _try_test_convert(
    value_str: str,
    frame: Any | None = None,
    parent_obj: Any | None = None,
) -> Any:
    try:
        return convert_value_with_context(value_str, frame, parent_obj)
    except (AttributeError, NameError, SyntaxError, TypeError, ValueError):
        return _CONVERSION_FAILED


def _make_variable_for_tests(dbg: Any, name: str, value: Any, frame: Any | None) -> dict[str, Any]:
    return command_handler_helpers.make_variable(
        dbg,
        name,
        value,
        frame,
    )


def _resolve_variables_for_reference_for_tests(dbg: Any, frame_info: Any) -> list[dict[str, Any]]:
    def _extract_from_mapping(
        helper_dbg: Any,
        mapping: dict[str, Any],
        frame: Any,
    ) -> list[dict[str, Any]]:
        return command_handler_helpers.extract_variables_from_mapping(
            helper_dbg,
            mapping,
            frame,
            make_variable_fn=_make_variable_for_tests,
        )

    return command_handler_helpers.resolve_variables_for_reference(
        dbg,
        frame_info,
        make_variable_fn=_make_variable_for_tests,
        extract_variables_from_mapping_fn=_extract_from_mapping,
        var_ref_tuple_size=dch.VAR_REF_TUPLE_SIZE,
    )


def _invoke_set_variable_via_domain(session: Any, arguments: dict[str, Any]) -> None:
    _obj_deps = command_handler_helpers.ObjectMemberDependencies(
        try_custom_convert=_try_test_convert,
        conversion_failed_sentinel=_CONVERSION_FAILED,
        convert_value_with_context_fn=convert_value_with_context,
        assign_to_parent_member_fn=command_handler_helpers.assign_to_parent_member,
        error_response_fn=dch._error_response,
        conversion_error_message=dch._CONVERSION_ERROR_MESSAGE,
        get_state_debugger=dch._active_debugger,
        make_variable_fn=_make_variable_for_tests,
        logger=dch.logger,
    )
    _scope_deps = command_handler_helpers.ScopeVariableDependencies(
        try_custom_convert=_try_test_convert,
        conversion_failed_sentinel=_CONVERSION_FAILED,
        convert_value_with_context_fn=convert_value_with_context,
        evaluate_with_policy_fn=dch.evaluate_with_policy,
        error_response_fn=dch._error_response,
        conversion_error_message=dch._CONVERSION_ERROR_MESSAGE,
        get_state_debugger=dch._active_debugger,
        make_variable_fn=_make_variable_for_tests,
        logger=dch.logger,
    )

    result = variable_handlers.handle_set_variable_impl(
        session,
        arguments,
        object_member_deps=_obj_deps,
        scope_variable_deps=_scope_deps,
        var_ref_tuple_size=dch.VAR_REF_TUPLE_SIZE,
    )
    if result:
        session.safe_send("setVariable", **result)


def test_convert_value_with_context_literal_and_bool_and_none():
    assert convert_value_with_context("None") is None
    assert convert_value_with_context("true") is True
    assert convert_value_with_context("False") is False
    assert convert_value_with_context("123") == 123


def test_convert_value_with_context_eval_with_frame():
    frame = SimpleNamespace(f_globals={"x": 5}, f_locals={})
    assert convert_value_with_context("x + 1", frame) == 6


def test_set_object_member_dict_list_tuple_and_attribute():
    _obj_deps = command_handler_helpers.ObjectMemberDependencies(
        try_custom_convert=_try_test_convert,
        conversion_failed_sentinel=_CONVERSION_FAILED,
        convert_value_with_context_fn=convert_value_with_context,
        assign_to_parent_member_fn=command_handler_helpers.assign_to_parent_member,
        error_response_fn=dch._error_response,
        conversion_error_message=dch._CONVERSION_ERROR_MESSAGE,
        get_state_debugger=dch._active_debugger,
        make_variable_fn=_make_variable_for_tests,
        logger=dch.logger,
    )

    def _set_object_member_direct(parent_obj: Any, name: str, value: str) -> dict[str, Any]:
        return command_handler_helpers.set_object_member_with_dependencies(
            parent_obj,
            name,
            value,
            deps=_obj_deps,
        )

    # dict
    d = {"a": 1}
    res = _set_object_member_direct(d, "a", "2")
    assert res["success"] is True
    assert d["a"] == 2

    # list
    lst = [1, 2, 3]
    res = _set_object_member_direct(lst, "1", "5")
    assert res["success"] is True
    assert lst[1] == 5

    # list invalid index
    res = _set_object_member_direct(lst, "x", "5")
    assert res["success"] is False

    # tuple immutability
    tpl = (1, 2)
    res = _set_object_member_direct(tpl, "0", "9")
    assert res["success"] is False

    # attribute on object
    class DummyObj:
        z: Any

    o = DummyObj()
    res = _set_object_member_direct(o, "z", "7")
    assert res["success"] is True
    assert o.z == 7


def test_set_scope_variable_locals_and_globals():
    _scope_deps = command_handler_helpers.ScopeVariableDependencies(
        try_custom_convert=_try_test_convert,
        conversion_failed_sentinel=_CONVERSION_FAILED,
        convert_value_with_context_fn=convert_value_with_context,
        evaluate_with_policy_fn=dch.evaluate_with_policy,
        error_response_fn=dch._error_response,
        conversion_error_message=dch._CONVERSION_ERROR_MESSAGE,
        get_state_debugger=dch._active_debugger,
        make_variable_fn=_make_variable_for_tests,
        logger=dch.logger,
    )

    def _set_scope_variable_direct(
        frame: Any,
        scope: str,
        name: str,
        value: str,
    ) -> dict[str, Any]:
        return command_handler_helpers.set_scope_variable_with_dependencies(
            frame,
            scope,
            name,
            value,
            deps=_scope_deps,
        )

    frame = SimpleNamespace(f_locals={}, f_globals={})
    r = _set_scope_variable_direct(frame, "locals", "n", "10")
    assert r["success"] is True
    assert frame.f_locals["n"] == 10

    r = _set_scope_variable_direct(frame, "globals", "g", "20")
    assert r["success"] is True
    assert frame.f_globals["g"] == 20

    r = _set_scope_variable_direct(frame, "weird", "x", "1")
    assert r["success"] is False


def test_handle_set_breakpoints_and_set_function_and_exception(monkeypatch):
    session, dbg = _active_session_with_debugger(DummyDebugger())

    # capture send_debug_message calls
    calls = []

    def fake_send_debug_message(kind, **kwargs):
        calls.append((kind, kwargs))

    session.transport.send = fake_send_debug_message  # type: ignore[assignment]

    # setBreakpoints
    args = {"source": {"path": "file.py"}, "breakpoints": [{"line": 10}]}
    breakpoint_handlers.handle_set_breakpoints_impl(
        session,
        cast("SetBreakpointsArguments", args),
        dch.logger,
    )
    assert ("file.py", 10, None) in dbg.breaks

    # setFunctionBreakpoints
    args = {"breakpoints": [{"name": "foo", "condition": "c", "hitCondition": 1}]}
    breakpoint_handlers.handle_set_function_breakpoints_impl(
        session,
        cast("SetFunctionBreakpointsArguments", args),
    )
    assert "foo" in dbg.function_breakpoints
    assert dbg.function_breakpoint_meta.get("foo", {}).get("condition") == "c"

    # setExceptionBreakpoints
    args = {"filters": ["raised", "uncaught"]}
    breakpoint_handlers.handle_set_exception_breakpoints_impl(
        session,
        cast("SetExceptionBreakpointsArguments", args),
    )
    assert dbg.exception_breakpoints_raised is True
    assert dbg.exception_breakpoints_uncaught is True


def test_handle_set_breakpoints_with_real_debugger_bdb(monkeypatch):
    session, dbg = _active_session_with_debugger(DebuggerBDB())

    calls = []

    def fake_send_debug_message(kind, **kwargs):
        calls.append((kind, kwargs))

    session.transport.send = fake_send_debug_message  # type: ignore[assignment]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as handle:
        handle.write("\n".join(f"x_{line} = {line}" for line in range(1, 31)) + "\n")
        source_path = handle.name

    try:
        cleared_lines: list[int] = []
        monkeypatch.setattr(
            dbg,
            "clear_break",
            lambda _path, line: cleared_lines.append(int(line)),
        )
        dbg.breaks = {source_path: [7]}  # type: ignore[attr-defined]

        args = {
            "source": {"path": source_path},
            "breakpoints": [{"line": 10}, {"line": 20, "condition": "x > 1"}],
        }
        breakpoint_handlers.handle_set_breakpoints_impl(
            session,
            cast("SetBreakpointsArguments", args),
            dch.logger,
        )

        assert cleared_lines == [7]
        assert dbg.get_break(source_path, 10)
        assert dbg.get_break(source_path, 20)
        assert any(kind == "breakpoints" for kind, _ in calls)
    finally:
        Path(source_path).unlink(missing_ok=True)


def test_continue_next_step_out(monkeypatch):
    session, dbg = _active_session_with_debugger(DummyDebugger())
    tid = threading.get_ident()
    dbg.stopped_thread_ids.add(tid)
    dbg.current_frame = object()
    # capture

    def _no_op(*_args, **_kwargs):
        return None

    session.transport.send = _no_op  # type: ignore[assignment]

    stepping_handlers.handle_continue_impl(session, {"threadId": tid})
    assert tid not in dbg.stopped_thread_ids
    assert dbg._continued is True

    stepping_handlers.handle_next_impl(
        session,
        {"threadId": tid},
        dch._get_thread_ident,
        dch._set_dbg_stepping_flag,
    )
    assert dbg.stepping is True

    stepping_handlers.handle_step_in_impl(
        session,
        {"threadId": tid},
        dch._get_thread_ident,
        dch._set_dbg_stepping_flag,
    )
    assert getattr(dbg, "_step", True) is True

    stepping_handlers.handle_step_out_impl(
        session,
        {"threadId": tid},
        dch._get_thread_ident,
        dch._set_dbg_stepping_flag,
    )
    assert getattr(dbg, "_return", None) is not None


def test_handle_pause_emits_stopped_and_marks_thread(monkeypatch):
    session, dbg = _active_session_with_debugger(DummyDebugger())
    tid = 12345

    calls = []

    def recorder(kind, **kwargs):
        calls.append((kind, kwargs))

    session.transport.send = recorder  # type: ignore[assignment]

    # Call the handler
    stepping_handlers.handle_pause_impl(
        session,
        {"threadId": tid},
        dch._get_thread_ident,
        dch.logger,
    )

    # Thread should be marked stopped and a stopped event emitted
    assert tid in dbg.stopped_thread_ids
    assert calls
    assert calls[-1][0] == "stopped"
    assert calls[-1][1].get("threadId") == tid
    assert calls[-1][1].get("reason") == "pause"


def test_variables_and_set_variable(monkeypatch):
    session, dbg = _active_session_with_debugger(DummyDebugger())
    frame = SimpleNamespace(f_locals={"a": 1}, f_globals={"b": 2})
    dbg.frame_id_to_frame[1] = frame
    dbg.var_refs[7] = (1, "locals")

    # stub variable factory to predictable output
    def fake_make_variable(_dbg, _name, value, _frame):
        return cast(
            "Variable",
            {"value": str(value), "type": type(value).__name__, "variablesReference": 0},
        )

    def _resolve_with_fake_make_variable(
        runtime_dbg: Any,
        frame_info: Any,
    ) -> list[dict[str, Any]]:
        return command_handler_helpers.resolve_variables_for_reference(
            runtime_dbg,
            frame_info,
            make_variable_fn=fake_make_variable,
            extract_variables_from_mapping_fn=lambda helper_dbg, mapping, frame: (
                command_handler_helpers.extract_variables_from_mapping(
                    helper_dbg,
                    mapping,
                    frame,
                    make_variable_fn=fake_make_variable,
                )
            ),
            var_ref_tuple_size=dch.VAR_REF_TUPLE_SIZE,
        )

    calls = []

    def recorder(kind, **kwargs):
        calls.append((kind, kwargs))

    session.transport.send = recorder  # type: ignore[assignment]

    variable_handlers.handle_variables_impl(
        session,
        {"variablesReference": 7},
        _resolve_with_fake_make_variable,
    )
    assert calls
    assert calls[-1][0] == "variables"

    # setVariable invalid ref
    calls.clear()
    _invoke_set_variable_via_domain(
        session, {"variablesReference": 999, "name": "x", "value": "1"}
    )
    assert calls
    assert calls[-1][0] == "setVariable"


def test_set_variable_bad_args_failure_payload(monkeypatch):
    session, _dbg = _active_session_with_debugger(DummyDebugger())

    calls = []

    def recorder(kind, **kwargs):
        calls.append((kind, kwargs))

    session.transport.send = recorder  # type: ignore[assignment]

    _invoke_set_variable_via_domain(
        session, {"variablesReference": "bad", "name": "x", "value": "1"}
    )

    assert calls
    event, payload = calls[-1]
    assert event == "setVariable"
    assert payload["success"] is False
    assert payload["message"] == "Invalid arguments"


def test_set_variable_missing_frame_failure_payload(monkeypatch):
    session, dbg = _active_session_with_debugger(DummyDebugger())
    dbg.var_refs[10] = (999, "locals")

    calls = []

    def recorder(kind, **kwargs):
        calls.append((kind, kwargs))

    session.transport.send = recorder  # type: ignore[assignment]

    _invoke_set_variable_via_domain(session, {"variablesReference": 10, "name": "x", "value": "1"})

    assert calls
    event, payload = calls[-1]
    assert event == "setVariable"
    assert payload["success"] is False
    assert payload["message"] == "Invalid variable reference: 10"


def test_set_variable_conversion_failure_payload(monkeypatch):
    session, dbg = _active_session_with_debugger(DummyDebugger())
    dbg.var_refs[11] = ("object", {"x": 1})

    calls = []

    def recorder(kind, **kwargs):
        calls.append((kind, kwargs))

    session.transport.send = recorder  # type: ignore[assignment]

    _invoke_set_variable_via_domain(
        session,
        {"variablesReference": 11, "name": "x", "value": object()},
    )

    assert calls
    event, payload = calls[-1]
    assert event == "setVariable"
    assert payload["success"] is False
    assert payload["message"] == "Conversion failed"


def test_collect_module_and_linecache_and_handle_source(monkeypatch, tmp_path):
    # create a fake module file and inject into sys.modules
    p = tmp_path / "mymod.py"
    p.write_text("# sample\n")
    m = types.ModuleType("__test_mymod__")
    m.__file__ = str(p)
    m.__package__ = "mymodpkg"
    sys.modules["__test_mymod__"] = m

    seen = set()
    sources = source_handlers._collect_module_sources(seen)
    assert any(s.get("path") and s.get("origin") for s in sources)

    # linecache: ensure cache has the file name
    linecache.cache[str(p)] = (1, None, [], str(p))
    seen2 = set()
    line_sources = source_handlers._collect_linecache_sources(seen2)
    assert any(s.get("path") for s in line_sources)

    # handle_source by path
    def get_source_content_by_path(_path):
        return "print(1)"

    monkeypatch.setattr(
        dch._active_session(),
        "get_source_content_by_path",
        get_source_content_by_path,
    )
    calls = []

    def recorder2(kind, **kwargs):
        calls.append((kind, kwargs))

    dch._active_session().transport.send = recorder2  # type: ignore[assignment]
    source_handlers.handle_source(
        {"path": str(p)},
        dch._active_session(),
    )
    assert calls
    assert calls[-1][0] == "response"


def test_handle_evaluate_and_create_variable_object(monkeypatch):
    session, dbg = _active_session_with_debugger(DummyDebugger())
    frame = SimpleNamespace(f_globals={"y": 2}, f_locals={})
    dbg.frame_id_to_frame[1] = frame

    calls = []

    def recorder3(kind, **kwargs):
        calls.append((kind, kwargs))

    session.transport.send = recorder3  # type: ignore[assignment]

    # successful eval
    variable_handlers.handle_evaluate_impl(
        session,
        {"expression": "y + 3", "frameId": 1},
        evaluate_with_policy=dch.evaluate_with_policy,
        format_evaluation_error=variable_handlers.format_evaluation_error,
        logger=dch.logger,
    )
    assert calls
    assert calls[-1][0] == "evaluate"

    # eval error
    variable_handlers.handle_evaluate_impl(
        session,
        {"expression": "unknown_var", "frameId": 1},
        evaluate_with_policy=dch.evaluate_with_policy,
        format_evaluation_error=variable_handlers.format_evaluation_error,
        logger=dch.logger,
    )
    assert calls
    assert calls[-1][0] == "evaluate"


def test_handle_evaluate_blocks_hostile_expression(monkeypatch):
    session, dbg = _active_session_with_debugger(DummyDebugger())
    frame = SimpleNamespace(f_globals={"x": 2}, f_locals={})
    dbg.current_frame = frame

    calls = []

    def recorder(kind, **kwargs):
        calls.append((kind, kwargs))

    session.transport.send = recorder  # type: ignore[assignment]

    variable_handlers.handle_evaluate_impl(
        session,
        {"expression": "__import__('os').system('id')", "frameId": 1},
        evaluate_with_policy=dch.evaluate_with_policy,
        format_evaluation_error=variable_handlers.format_evaluation_error,
        logger=dch.logger,
    )
    assert calls
    event, payload = calls[-1]
    assert event == "evaluate"
    assert payload["result"] == "<error: Evaluation blocked by policy>"


def test_handle_exception_info_variants(monkeypatch):
    calls = []

    def recorder4(kind, **kwargs):
        calls.append((kind, kwargs))

    dch._active_session().transport.send = recorder4  # type: ignore[assignment]

    # missing threadId
    lifecycle_handlers.cmd_exception_info(
        cast("ExceptionInfoArguments", {}),
        state=dch._active_session(),
    )
    assert calls
    assert calls[-1][0] == "error"

    # debugger not initialized
    monkeypatch.setattr(dch._active_session(), "debugger", None)
    calls.clear()
    lifecycle_handlers.cmd_exception_info(
        cast("ExceptionInfoArguments", {"threadId": 1}),
        state=dch._active_session(),
    )
    assert calls
    assert calls[-1][0] == "error"

    # debugger with no info for thread
    dbg = DummyDebugger()
    monkeypatch.setattr(dch._active_session(), "debugger", dbg)
    calls.clear()
    lifecycle_handlers.cmd_exception_info(
        cast("ExceptionInfoArguments", {"threadId": 2}),
        state=dch._active_session(),
    )
    assert calls
    assert calls[-1][0] == "error"

    # with exception info
    dbg.current_exception_info[3] = {
        "exceptionId": "E",
        "description": "d",
        "breakMode": "mode",
        "details": {},
    }
    calls.clear()
    lifecycle_handlers.cmd_exception_info(
        cast("ExceptionInfoArguments", {"threadId": 3}),
        state=dch._active_session(),
    )
    assert calls
    assert calls[-1][0] == "exceptionInfo"


def test_create_variable_object_debugger_override_and_fallback(monkeypatch):
    # override returns dict
    class DbgWithMake(DummyDebugger):
        def make_variable_object(
            self,
            name: Any,
            value: Any,
            frame: Any | None = None,
            *,
            max_string_length: int = 1000,
        ):
            # reference parameters to satisfy linters and preserve protocol shape
            _ = (name, frame, max_string_length)
            return cast(
                "Variable",
                {"value": f"dbg:{value}", "type": "int", "variablesReference": 0},
            )

    _session, dbg = _active_session_with_debugger(DbgWithMake())
    res = debug_shared.make_variable_object("n", 5, dbg)
    assert isinstance(res, dict)
    assert res["value"].startswith("dbg:")

    # make_variable_object raises -> fallback to module helper
    class DbgBad(DummyDebugger):
        def make_variable_object(
            self,
            name: Any,
            value: Any,
            frame: Any | None = None,
            *,
            max_string_length: int = 1000,
        ):
            # reference parameters to satisfy linters and preserve protocol shape
            _ = (name, value, frame, max_string_length)
            msg = "fail"
            raise RuntimeError(msg)

    monkeypatch.setattr(dch._active_session(), "debugger", DbgBad())
    res2 = debug_shared.make_variable_object("n", 6, dbg)
    assert isinstance(res2, dict)


def test_loaded_sources_and_modules_paging(monkeypatch, tmp_path):
    # prepare two fake module files
    p1 = tmp_path / "a1.py"
    p1.write_text("# a1")
    p2 = tmp_path / "b2.py"
    p2.write_text("# b2")

    # register real module objects to avoid typing complaints

    m1 = types.ModuleType("m_a1")
    m1.__file__ = str(p1)
    m1.__package__ = "m_a1"
    m2 = types.ModuleType("m_b2")
    m2.__file__ = str(p2)
    m2.__package__ = "m_b2"
    sys.modules["m_a1"] = m1
    sys.modules["m_b2"] = m2

    # state handling for refs
    monkeypatch.setattr(dch._active_session(), "get_ref_for_path", lambda _p: None)

    def get_or_create_source_ref(_p, _n=None):
        return 123

    monkeypatch.setattr(
        dch._active_session(),
        "get_or_create_source_ref",
        get_or_create_source_ref,
    )

    def get_source_meta(ref):
        return {"path": str(p1)} if ref == 123 else None

    monkeypatch.setattr(dch._active_session(), "get_source_meta", get_source_meta)

    def get_source_content_by_ref(ref):
        return "print(1)" if ref == 123 else None

    monkeypatch.setattr(
        dch._active_session(),
        "get_source_content_by_ref",
        get_source_content_by_ref,
    )

    calls = []

    def recorder5(kind, **kwargs):
        calls.append((kind, kwargs))

    dch._active_session().transport.send = recorder5  # type: ignore[assignment]
    source_handlers.handle_loaded_sources(dch._active_session())
    assert calls
    assert calls[-1][0] == "response"

    # modules with paging
    calls.clear()
    source_handlers.handle_modules(
        {"startModule": 0, "moduleCount": 1},
        dch._active_session(),
    )
    assert calls
    assert calls[-1][0] == "response"


def test_handle_source_binary_and_reference(monkeypatch, tmp_path):
    # binary content (contains NUL) should not set mimeType
    p = tmp_path / "bin.py"
    p.write_bytes(b"\x00\x01")

    def get_source_content_binary(_path):
        return "\x00\x01"

    monkeypatch.setattr(
        dch._active_session(),
        "get_source_content_by_path",
        get_source_content_binary,
    )
    calls = []

    def recorder6(kind, **kwargs):
        calls.append((kind, kwargs))

    dch._active_session().transport.send = recorder6  # type: ignore[assignment]
    source_handlers.handle_source(
        {"path": str(p)},
        dch._active_session(),
    )
    assert calls
    assert calls[-1][0] == "response"

    # sourceReference path mapping
    monkeypatch.setattr(dch._active_session(), "get_source_meta", lambda _ref: {"path": str(p)})
    monkeypatch.setattr(
        dch._active_session(),
        "get_source_content_by_ref",
        lambda _ref: "print(2)",
    )
    calls.clear()
    source_handlers.handle_source(
        {"source": {"sourceReference": 1}},
        dch._active_session(),
    )
    assert calls
    assert calls[-1][0] == "response"
