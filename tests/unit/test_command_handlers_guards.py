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
        (handlers._cmd_goto_targets, {}),
        (handlers._cmd_goto, {}),
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
    # This test merely ensures the handler can be invoked without blowing up
    # when no debugger is attached.  behaviour is covered by more precise
    # assertions below.
    monkeypatch.setattr(handlers, "_active_debugger", lambda: None)

    handler(args)


def test_handlers_send_error_response_without_debugger(monkeypatch: pytest.MonkeyPatch) -> None:
    """When no debugger is configured handlers should still reply.

    We exercise a handful of commands that historically returned ``None`` and
    therefore would produce no response.  The new contract requires an
    explicit failure message so clients don't hang.
    """
    monkeypatch.setattr(handlers, "_active_debugger", lambda: None)

    session = DebugSession()
    sent: list[tuple[str, dict]] = []
    session.transport.send = lambda mtype, **kw: sent.append((mtype, kw))  # type: ignore[assignment]
    monkeypatch.setattr(handlers, "_active_session", lambda: session)

    # choose a representative sample of handlers that formerly silenced
    # themselves when no debugger was present
    handlers_to_call = [
        handlers._cmd_set_breakpoints,
        handlers._cmd_threads,
        handlers._cmd_scopes,
        handlers._cmd_variables,
        handlers._cmd_set_variable,
        handlers._cmd_evaluate,
        handlers._cmd_set_data_breakpoints,
        handlers._cmd_data_breakpoint_info,
    ]

    for handler in handlers_to_call:
        sent.clear()
        handler({})
        assert sent, f"{handler.__name__} did not send a response"
        typ, payload = sent[-1]
        assert typ == "response"
        # at minimum, indicate failure or empty success
        assert "success" in payload


def test_handle_debug_command_rejects_non_string_command(monkeypatch: pytest.MonkeyPatch):
    sent: list[tuple[str, dict[str, object]]] = []
    session = DebugSession()
    session.transport.send = lambda message_type, **payload: sent.append((message_type, payload))  # type: ignore[assignment]

    handlers.handle_debug_command({"id": 7, "command": 123, "arguments": {}}, session=session)

    assert sent
    message_type, payload = sent[-1]
    assert message_type == "response"
    assert payload["id"] == 7
    assert payload["success"] is False
    assert "Invalid command" in str(payload["message"])


def test_handle_debug_command_rejects_unknown_command(monkeypatch: pytest.MonkeyPatch):
    sent: list[tuple[str, dict[str, object]]] = []
    session = DebugSession()
    session.transport.send = lambda message_type, **payload: sent.append((message_type, payload))  # type: ignore[assignment]

    handlers.handle_debug_command(
        {"id": 8, "command": "definitelyUnknown", "arguments": {}},
        session=session,
    )

    assert sent
    message_type, payload = sent[-1]
    assert message_type == "response"
    assert payload["id"] == 8
    assert payload["success"] is False
    assert payload["message"] == "Unknown command: definitelyUnknown"


def test_set_breakpoints_handler_exercises_debugger_clear_breaks_for_file(
    monkeypatch: pytest.MonkeyPatch,
):
    dbg = DebuggerBDB()
    dbg.breaks = {"/tmp/sample.py": [10]}  # type: ignore[attr-defined]

    cleared_lines: list[int] = []
    monkeypatch.setattr(dbg, "clear_break", lambda _path, line: cleared_lines.append(line))

    session = DebugSession()
    session.debugger = dbg
    session.transport.send = lambda *_a, **_kw: None  # type: ignore[assignment]
    monkeypatch.setattr(handlers, "_active_session", lambda: session)

    handlers._cmd_set_breakpoints({"source": {"path": "/tmp/sample.py"}, "breakpoints": []})

    assert cleared_lines == [10]
