from __future__ import annotations

import pytest

from dapper.core.debugger_bdb import DebuggerBDB
from dapper.shared import command_handlers as handlers
from dapper.shared.debug_shared import DebugSession


@pytest.mark.parametrize(
    ("handler", "args"),
    [
        (handlers._cmd_set_breakpoints, {}),
        (handlers._cmd_set_function_breakpoints, {}),
        (handlers._cmd_set_exception_breakpoints, {}),
        (handlers._cmd_continue, {}),
        (handlers._cmd_next, {}),
        (handlers._cmd_step_in, {}),
        (handlers._cmd_step_out, {}),
        (handlers._cmd_pause, {}),
        (handlers._cmd_stack_trace, {}),
        (handlers._cmd_threads, {}),
        (handlers._cmd_scopes, {}),
        (handlers._cmd_variables, {}),
        (handlers._cmd_set_variable, {}),
        (handlers._cmd_evaluate, {}),
        (handlers._cmd_set_data_breakpoints, {}),
        (handlers._cmd_data_breakpoint_info, {}),
    ],
)
def test_debugger_dependent_handlers_noop_without_debugger(
    monkeypatch: pytest.MonkeyPatch,
    handler,
    args,
):
    monkeypatch.setattr(handlers, "_active_debugger", lambda: None)

    handler(args)


def test_handle_debug_command_rejects_non_string_command(monkeypatch: pytest.MonkeyPatch):
    sent: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        handlers,
        "_safe_send_debug_message",
        lambda message_type, **payload: sent.append((message_type, payload)) or True,
    )
    session = DebugSession()

    handlers.handle_debug_command({"seq": 7, "command": 123, "arguments": {}}, session=session)

    assert sent
    message_type, payload = sent[-1]
    assert message_type == "response"
    assert payload["request_seq"] == 7
    assert payload["success"] is False
    assert "Invalid command" in str(payload["message"])


def test_handle_debug_command_rejects_unknown_command(monkeypatch: pytest.MonkeyPatch):
    sent: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        handlers,
        "_safe_send_debug_message",
        lambda message_type, **payload: sent.append((message_type, payload)) or True,
    )
    session = DebugSession()

    handlers.handle_debug_command(
        {"seq": 8, "command": "definitelyUnknown", "arguments": {}},
        session=session,
    )

    assert sent
    message_type, payload = sent[-1]
    assert message_type == "response"
    assert payload["request_seq"] == 8
    assert payload["success"] is False
    assert payload["message"] == "Unknown command: definitelyUnknown"


def test_set_breakpoints_handler_exercises_debugger_clear_breaks_for_file(
    monkeypatch: pytest.MonkeyPatch,
):
    dbg = DebuggerBDB()
    dbg.breaks = {"/tmp/sample.py": [10]}  # type: ignore[attr-defined]

    cleared_lines: list[int] = []
    monkeypatch.setattr(dbg, "clear_break", lambda _path, line: cleared_lines.append(line))
    monkeypatch.setattr(handlers, "_active_debugger", lambda: dbg)
    monkeypatch.setattr(
        handlers, "_safe_send_debug_message", lambda _message_type, **_payload: True
    )

    handlers._cmd_set_breakpoints({"source": {"path": "/tmp/sample.py"}, "breakpoints": []})

    assert cleared_lines == [10]
