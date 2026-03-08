from __future__ import annotations

from dapper.utils.logging_message_summary import summarize_dap_message
from dapper.utils.logging_message_summary import summarize_debugger_bdb_event


def test_summarize_response_message() -> None:
    summary = summarize_dap_message({"event": "response", "id": 7, "success": True})
    assert summary == "response id=7 success=True"


def test_summarize_command_message() -> None:
    summary = summarize_dap_message(
        {"command": "initialize", "id": 3, "arguments": {"clientID": "vscode"}}
    )
    assert summary == "command=initialize id=3 args=clientID"


def test_summarize_event_message() -> None:
    summary = summarize_dap_message(
        {"event": "stopped", "body": {"reason": "pause", "threadId": 4}}
    )
    assert summary == "event=stopped body=reason,threadId"


def test_summarize_debugger_bdb_event_shortens_paths_and_sequences() -> None:
    summary = summarize_debugger_bdb_event(
        "regular_breakpoint.hit",
        file="/tmp/example/app.py",
        line=66,
        via=["get_break", "break_table"],
    )

    assert summary == "regular_breakpoint.hit file=app.py line=66 via=get_break,break_table"


def test_summarize_debugger_bdb_event_truncates_long_values() -> None:
    summary = summarize_debugger_bdb_event(
        "user_exception.stop",
        exc="ValueError",
        value="x" * 120,
    )

    assert summary == f"user_exception.stop exc=ValueError value={'x' * 77}..."
