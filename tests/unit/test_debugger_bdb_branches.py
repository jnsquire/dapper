from __future__ import annotations

from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock

from dapper.core.breakpoint_resolver import ResolveAction
import dapper.core.debugger_bdb as debugger_bdb_module
from dapper.core.debugger_bdb import DebuggerBDB
from tests.mocks import make_real_frame


def _make_frame(name: str = "target_fn", filename: str = "test_file.py", lineno: int = 12):
    code = SimpleNamespace(co_name=name, co_filename=filename)
    return SimpleNamespace(f_code=code, f_lineno=lineno, f_locals={}, f_back=None)


def test_user_call_returns_early_without_function_breakpoints():
    messages: list[tuple[str, dict[str, object]]] = []
    dbg = DebuggerBDB(send_message=lambda event, **kwargs: messages.append((event, kwargs)))

    dbg.user_call(_make_frame(), None)

    assert messages == []


def test_user_call_continue_action_does_not_emit_stopped(monkeypatch):
    messages: list[tuple[str, dict[str, object]]] = []
    dbg = DebuggerBDB(send_message=lambda event, **kwargs: messages.append((event, kwargs)))
    dbg.bp_manager.function_names = ["target_fn"]
    dbg.bp_manager.function_meta["target_fn"] = {"logMessage": "hello"}

    monkeypatch.setattr(
        debugger_bdb_module,
        "get_function_candidate_names",
        lambda _frame: ["target_fn"],
    )

    def resolve_continue(*_args, **_kwargs):
        return SimpleNamespace(action=ResolveAction.CONTINUE)

    monkeypatch.setattr(dbg.breakpoint_resolver, "resolve", resolve_continue)

    dbg.user_call(_make_frame(), None)

    assert not any(event == "stopped" for event, _ in messages)


def test_user_call_stop_action_emits_function_breakpoint(monkeypatch):
    messages: list[tuple[str, dict[str, object]]] = []
    processed: list[bool] = []
    dbg = DebuggerBDB(
        send_message=lambda event, **kwargs: messages.append((event, kwargs)),
        process_commands=lambda: processed.append(True),
    )
    dbg.bp_manager.function_names = ["target_fn"]
    dbg.bp_manager.function_meta["target_fn"] = {}

    monkeypatch.setattr(
        debugger_bdb_module,
        "get_function_candidate_names",
        lambda _frame: ["target_fn"],
    )

    def resolve_stop(*_args, **_kwargs):
        return SimpleNamespace(action=ResolveAction.STOP)

    monkeypatch.setattr(dbg.breakpoint_resolver, "resolve", resolve_stop)

    frame = _make_frame()
    dbg.botframe = frame
    dbg.user_call(frame, None)

    stopped_events = [payload for event, payload in messages if event == "stopped"]
    assert stopped_events
    assert stopped_events[-1]["reason"] == "function breakpoint"
    assert processed == [True]


def test_clear_breaks_for_file_handles_invalid_entries_and_meta_errors(monkeypatch):
    dbg = DebuggerBDB()
    dbg.breaks = {"sample.py": [10, None, "not-an-int", 20]}  # type: ignore[attr-defined]

    cleared_lines: list[int] = []
    monkeypatch.setattr(dbg, "clear_break", lambda _path, line: cleared_lines.append(line))
    monkeypatch.setattr(
        dbg,
        "clear_break_meta_for_file",
        lambda _path: (_ for _ in ()).throw(RuntimeError("meta-clear-failed")),
    )

    dbg.clear_breaks_for_file("sample.py")

    assert cleared_lines == [10, 20]


def test_user_exception_swallows_set_continue_failure(monkeypatch):
    dbg = DebuggerBDB()
    dbg.exception_handler.config.break_on_raised = True
    monkeypatch.setattr(
        dbg,
        "set_continue",
        lambda: (_ for _ in ()).throw(RuntimeError("set_continue failed")),
    )

    frame = _make_frame()
    exc = ValueError("boom")
    dbg.user_exception(frame, (ValueError, exc, None))


def test_should_stop_for_data_breakpoint_defaults_to_true_without_meta():
    dbg = DebuggerBDB()
    dbg.data_bp_state.watch_meta = {}

    assert dbg._should_stop_for_data_breakpoint("x", _make_frame()) is True


def test_should_stop_for_data_breakpoint_returns_false_when_all_continue(monkeypatch):
    dbg = DebuggerBDB()
    dbg.data_bp_state.watch_meta = {"x": [{}, {}]}

    monkeypatch.setattr(
        dbg.breakpoint_resolver,
        "resolve",
        lambda _meta, _frame: SimpleNamespace(action=ResolveAction.CONTINUE),
    )

    assert dbg._should_stop_for_data_breakpoint("x", _make_frame()) is False


def test_ensure_thread_registered_emits_thread_started_only_once():
    messages: list[tuple[str, dict[str, object]]] = []
    dbg = DebuggerBDB(send_message=lambda event, **kwargs: messages.append((event, kwargs)))

    thread_id = 777
    dbg._ensure_thread_registered(thread_id)
    dbg._ensure_thread_registered(thread_id)

    thread_events = [payload for event, payload in messages if event == "thread"]
    assert len(thread_events) == 1
    assert thread_events[0]["threadId"] == thread_id
    assert thread_events[0]["reason"] == "started"


def test_emit_stopped_event_includes_optional_description(monkeypatch):
    messages: list[tuple[str, dict[str, object]]] = []
    dbg = DebuggerBDB(send_message=lambda event, **kwargs: messages.append((event, kwargs)))

    monkeypatch.setattr(dbg, "_get_stack_frames", lambda _frame: [{"id": 1}])

    frame = _make_frame()
    thread_id = 5
    dbg._emit_stopped_event(frame, thread_id, "data breakpoint", "x changed")

    stopped_events = [payload for event, payload in messages if event == "stopped"]
    assert stopped_events
    assert stopped_events[-1]["description"] == "x changed"
    assert dbg.thread_tracker.frames_by_thread[thread_id] == [{"id": 1}]
    assert thread_id in dbg.thread_tracker.stopped_thread_ids


def test_user_line_data_change_without_stop_returns_early(monkeypatch):
    messages: list[tuple[str, dict[str, object]]] = []
    dbg = DebuggerBDB(send_message=lambda event, **kwargs: messages.append((event, kwargs)))

    monkeypatch.setattr(dbg, "_check_data_watch_changes", lambda _frame: ["x"])
    monkeypatch.setattr(dbg, "_update_watch_snapshots", lambda _frame: None)
    monkeypatch.setattr(dbg, "_should_stop_for_data_breakpoint", lambda _name, _frame: False)
    monkeypatch.setattr(
        dbg,
        "_handle_regular_breakpoint",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    dbg.user_line(_make_frame())

    assert not any(event == "stopped" for event, _ in messages)


def test_user_line_default_stop_path_emits_event_and_continues(monkeypatch):
    messages: list[tuple[str, dict[str, object]]] = []
    processed: list[bool] = []
    dbg = DebuggerBDB(
        send_message=lambda event, **kwargs: messages.append((event, kwargs)),
        process_commands=lambda: processed.append(True),
    )

    monkeypatch.setattr(dbg, "_check_data_watch_changes", lambda _frame: [])
    monkeypatch.setattr(dbg, "_update_watch_snapshots", lambda _frame: None)
    monkeypatch.setattr(dbg, "_handle_regular_breakpoint", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        dbg.stepping_controller,
        "consume_stop_state",
        lambda: SimpleNamespace(value="step"),
    )
    monkeypatch.setattr(dbg.thread_tracker, "clear_frames", MagicMock())
    monkeypatch.setattr(dbg, "set_continue", lambda: None)
    # The user_line guard skips when stepping is False; set it True so
    # we actually reach the default stop path.
    dbg.stepping_controller.stepping = True

    dbg.user_line(_make_frame())

    stopped_events = [payload for event, payload in messages if event == "stopped"]
    assert stopped_events
    assert stopped_events[-1]["reason"] == "step"
    assert processed == [True]
    dbg.thread_tracker.clear_frames.assert_called_once()


def test_user_exception_returns_early_when_exception_break_disabled():
    messages: list[tuple[str, dict[str, object]]] = []
    dbg = DebuggerBDB(send_message=lambda event, **kwargs: messages.append((event, kwargs)))
    dbg.exception_handler.config.break_on_raised = False

    frame = _make_frame()
    exc = ValueError("boom")
    dbg.user_exception(frame, (ValueError, exc, None))

    assert messages == []


def test_user_call_returns_early_when_no_function_name_matches(monkeypatch):
    messages: list[tuple[str, dict[str, object]]] = []
    dbg = DebuggerBDB(send_message=lambda event, **kwargs: messages.append((event, kwargs)))
    dbg.bp_manager.function_names = ["target_fn"]

    monkeypatch.setattr(
        debugger_bdb_module,
        "get_function_candidate_names",
        lambda _frame: ["other_fn"],
    )

    dbg.user_call(_make_frame(), None)

    assert messages == []


def test_user_call_matches_second_function_name(monkeypatch):
    messages: list[tuple[str, dict[str, object]]] = []
    dbg = DebuggerBDB(send_message=lambda event, **kwargs: messages.append((event, kwargs)))
    dbg.bp_manager.function_names = ["first_fn", "target_fn"]
    dbg.bp_manager.function_meta["target_fn"] = {}

    monkeypatch.setattr(
        debugger_bdb_module,
        "get_function_candidate_names",
        lambda _frame: ["target_fn"],
    )
    monkeypatch.setattr(
        dbg.breakpoint_resolver,
        "resolve",
        lambda *_args, **_kwargs: SimpleNamespace(action=ResolveAction.CONTINUE),
    )

    dbg.user_call(_make_frame(), None)

    assert not any(event == "stopped" for event, _ in messages)


def test_check_data_watch_helpers_return_early_for_non_mapping_locals():
    dbg = DebuggerBDB()
    frame = _make_frame()
    frame.f_locals = object()

    assert dbg._check_data_watch_changes(frame) == []
    assert dbg._update_watch_snapshots(frame) is None


def test_set_custom_breakpoint_uses_existing_file_mapping(monkeypatch):
    dbg = DebuggerBDB()
    dbg.bp_manager.custom["/test.py"] = {1: "x > 0"}

    set_break_calls: list[tuple[str, int, str | None]] = []
    monkeypatch.setattr(
        dbg,
        "set_break",
        lambda path, line, cond=None: set_break_calls.append((path, line, cond)),
    )

    dbg.set_custom_breakpoint("/test.py", 2, condition="y > 0")

    assert dbg.bp_manager.custom["/test.py"] == {1: "x > 0", 2: "y > 0"}
    assert set_break_calls == [("/test.py", 2, "y > 0")]


def test_clear_custom_breakpoint_noop_when_target_missing(monkeypatch):
    dbg = DebuggerBDB()
    dbg.bp_manager.custom["/test.py"] = {10: None}

    clear_break = MagicMock()
    monkeypatch.setattr(dbg, "clear_break", clear_break)

    dbg.clear_custom_breakpoint("/test.py", 20)
    dbg.clear_custom_breakpoint("/missing.py", 1)

    assert dbg.bp_manager.custom["/test.py"] == {10: None}
    clear_break.assert_not_called()


def test_handle_regular_breakpoint_continue_path(monkeypatch):
    dbg = DebuggerBDB()

    monkeypatch.setattr(dbg, "get_break", lambda _filename, _line: True)
    monkeypatch.setattr(
        dbg.breakpoint_resolver,
        "resolve",
        lambda *_args, **_kwargs: SimpleNamespace(action=ResolveAction.CONTINUE),
    )

    set_continue = MagicMock()
    monkeypatch.setattr(dbg, "set_continue", set_continue)

    result = dbg._handle_regular_breakpoint("test_file.py", 12, _make_frame())

    assert result is True
    set_continue.assert_called_once()


def test_handle_regular_breakpoint_stop_path_emits_stopped(monkeypatch):
    messages: list[tuple[str, dict[str, object]]] = []
    processed: list[bool] = []
    dbg = DebuggerBDB(
        send_message=lambda event, **kwargs: messages.append((event, kwargs)),
        process_commands=lambda: processed.append(True),
    )

    monkeypatch.setattr(dbg, "get_break", lambda _filename, _line: True)
    monkeypatch.setattr(
        dbg.breakpoint_resolver,
        "resolve",
        lambda *_args, **_kwargs: SimpleNamespace(action=ResolveAction.STOP),
    )
    monkeypatch.setattr(dbg, "set_continue", lambda: None)

    result = dbg._handle_regular_breakpoint("test_file.py", 12, _make_frame())

    stopped_events = [payload for event, payload in messages if event == "stopped"]
    assert result is True
    assert stopped_events
    assert stopped_events[-1]["reason"] == "breakpoint"
    assert processed == [True]


def test_user_line_stops_on_data_breakpoint_and_returns(monkeypatch):
    messages: list[tuple[str, dict[str, object]]] = []
    dbg = DebuggerBDB(send_message=lambda event, **kwargs: messages.append((event, kwargs)))

    monkeypatch.setattr(dbg, "_check_data_watch_changes", lambda _frame: ["x"])
    monkeypatch.setattr(dbg, "_update_watch_snapshots", lambda _frame: None)
    monkeypatch.setattr(dbg, "_should_stop_for_data_breakpoint", lambda _name, _frame: True)
    monkeypatch.setattr(
        dbg,
        "_handle_regular_breakpoint",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    dbg.user_line(_make_frame())

    stopped_events = [payload for event, payload in messages if event == "stopped"]
    assert stopped_events
    assert stopped_events[-1]["reason"] == "data breakpoint"
    assert "description" in stopped_events[-1]


def test_user_line_returns_when_regular_breakpoint_is_handled(monkeypatch):
    dbg = DebuggerBDB()

    monkeypatch.setattr(dbg, "_check_data_watch_changes", lambda _frame: [])
    monkeypatch.setattr(dbg, "_update_watch_snapshots", lambda _frame: None)
    monkeypatch.setattr(dbg, "_handle_regular_breakpoint", lambda *_args, **_kwargs: True)
    consume_stop_state = MagicMock()
    monkeypatch.setattr(dbg.stepping_controller, "consume_stop_state", consume_stop_state)

    dbg.user_line(_make_frame())

    consume_stop_state.assert_not_called()


def test_user_exception_stop_path_emits_and_stores_exception(monkeypatch):
    messages: list[tuple[str, dict[str, object]]] = []
    processed: list[bool] = []
    dbg = DebuggerBDB(
        send_message=lambda event, **kwargs: messages.append((event, kwargs)),
        process_commands=lambda: processed.append(True),
    )

    frame = _make_frame()
    exc = ValueError("boom")

    monkeypatch.setattr(dbg.exception_handler, "should_break", lambda _frame: True)
    monkeypatch.setattr(
        dbg.exception_handler,
        "build_exception_info",
        lambda _exc_info, _frame: {"exceptionId": "ValueError", "description": "boom"},
    )
    store_exception_info = MagicMock()
    monkeypatch.setattr(dbg.exception_handler, "store_exception_info", store_exception_info)
    monkeypatch.setattr(
        dbg.exception_handler,
        "get_exception_text",
        lambda _exc_info: "ValueError",
    )
    monkeypatch.setattr(dbg, "_get_stack_frames", lambda _frame: [{"id": 1}])
    set_continue = MagicMock()
    monkeypatch.setattr(dbg, "set_continue", set_continue)

    dbg.user_exception(frame, (ValueError, exc, None))

    stopped_events = [payload for event, payload in messages if event == "stopped"]
    assert stopped_events
    assert stopped_events[-1]["reason"] == "exception"
    assert processed == [True]
    store_exception_info.assert_called_once()
    # set_continue is no longer called; blocking process_commands handles
    # resumption via _resume_event.


def test_clear_breaks_for_file_handles_breaks_lookup_exception(monkeypatch):
    dbg = DebuggerBDB()

    class ExplodingBreaks(dict):
        def get(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    dbg.breaks = ExplodingBreaks()  # type: ignore[attr-defined]

    clear_break = MagicMock()
    clear_meta = MagicMock()
    monkeypatch.setattr(dbg, "clear_break", clear_break)
    monkeypatch.setattr(dbg, "clear_break_meta_for_file", clear_meta)

    dbg.clear_breaks_for_file("sample.py")

    clear_break.assert_not_called()
    clear_meta.assert_called_once_with("sample.py")


def test_user_line_default_path_with_real_frame_and_entry_reason(monkeypatch):
    messages: list[tuple[str, dict[str, object]]] = []
    processed: list[bool] = []
    dbg = DebuggerBDB(
        send_message=lambda event, **kwargs: messages.append((event, kwargs)),
        process_commands=lambda: processed.append(True),
    )
    dbg.stepping_controller.stop_on_entry = True
    monkeypatch.setattr(dbg, "set_continue", lambda: None)

    frame = make_real_frame(
        {"x": 1},
        filename="/tmp/test_user_line_default.py",
        lineno=10,
    )
    dbg.user_line(frame)

    stopped_events = [payload for event, payload in messages if event == "stopped"]
    assert stopped_events
    assert stopped_events[-1]["reason"] == "entry"
    assert processed == [True]


def test_handle_regular_breakpoint_with_real_break_table_continue(monkeypatch):
    dbg = DebuggerBDB()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as handle:
        handle.write("x = 1\n")
        file_path = handle.name

    try:
        dbg.breaks = {file_path: [1]}  # type: ignore[attr-defined]
        dbg.breakpoint_resolver.resolve = lambda *_args, **_kwargs: SimpleNamespace(
            action=ResolveAction.CONTINUE,
        )
        set_continue = MagicMock()
        monkeypatch.setattr(dbg, "set_continue", set_continue)

        frame = make_real_frame({"x": 1}, filename=file_path, lineno=1)
        result = dbg._handle_regular_breakpoint(file_path, 1, frame)

        assert result is True
        set_continue.assert_called_once()
    finally:
        Path(file_path).unlink(missing_ok=True)


def test_user_exception_full_flow_with_real_exc_info(monkeypatch):
    messages: list[tuple[str, dict[str, object]]] = []
    processed: list[bool] = []
    dbg = DebuggerBDB(
        send_message=lambda event, **kwargs: messages.append((event, kwargs)),
        process_commands=lambda: processed.append(True),
    )
    dbg.exception_handler.config.break_on_raised = True

    set_continue = MagicMock()
    monkeypatch.setattr(dbg, "set_continue", set_continue)

    frame = make_real_frame({"x": 1}, filename="/tmp/test_user_exception.py", lineno=5)

    def _raise_value_error() -> None:
        raise ValueError("boom")

    try:
        _raise_value_error()
    except ValueError as error:
        exc_info = (ValueError, error, error.__traceback__)

    dbg.user_exception(frame, exc_info)

    stopped_events = [payload for event, payload in messages if event == "stopped"]
    assert stopped_events
    assert stopped_events[-1]["reason"] == "exception"
    assert processed == [True]
    # set_continue is no longer called; blocking process_commands handles
    # resumption via _resume_event.


def test_clear_breaks_for_file_success_path_clears_lines_and_meta(monkeypatch):
    dbg = DebuggerBDB()
    dbg.breaks = {"/tmp/sample.py": [10, 20]}  # type: ignore[attr-defined]

    cleared_lines: list[int] = []
    clear_meta = MagicMock()
    monkeypatch.setattr(dbg, "clear_break", lambda _path, line: cleared_lines.append(line))
    monkeypatch.setattr(dbg, "clear_break_meta_for_file", clear_meta)

    dbg.clear_breaks_for_file("/tmp/sample.py")

    assert cleared_lines == [10, 20]
    clear_meta.assert_called_once_with("/tmp/sample.py")
