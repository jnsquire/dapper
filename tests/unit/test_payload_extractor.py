"""Unit tests for dapper.adapter.payload_extractor."""

from __future__ import annotations

import pytest

from dapper.adapter.payload_extractor import extract_payload

# ---------------------------------------------------------------------------
# Unknown event type
# ---------------------------------------------------------------------------


def test_unknown_event_type_returns_none() -> None:
    assert extract_payload("nonexistent", {}) is None


def test_unknown_event_type_with_data_returns_none() -> None:
    assert extract_payload("bogus", {"key": "value"}) is None


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------


def test_output_defaults() -> None:
    result = extract_payload("output", {})
    assert result == {
        "category": "console",
        "output": "",
        "source": None,
        "line": None,
        "column": None,
    }


def test_output_explicit_values() -> None:
    data = {"category": "stderr", "output": "hello\n", "source": "app.py", "line": 10, "column": 3}
    result = extract_payload("output", data)
    assert result is not None
    assert result["category"] == "stderr"
    assert result["output"] == "hello\n"
    assert result["source"] == "app.py"
    assert result["line"] == 10
    assert result["column"] == 3


def test_continued_defaults() -> None:
    result = extract_payload("continued", {})
    assert result == {"threadId": 1, "allThreadsContinued": True}


def test_continued_explicit_values() -> None:
    result = extract_payload("continued", {"threadId": 42, "allThreadsContinued": False})
    assert result is not None
    assert result["threadId"] == 42
    assert result["allThreadsContinued"] is False


def test_exception_defaults() -> None:
    result = extract_payload("exception", {})
    assert result == {
        "exceptionId": "Exception",
        "description": "",
        "breakMode": "always",
        "threadId": 1,
    }


def test_exception_explicit_values() -> None:
    data = {
        "exceptionId": "ValueError",
        "description": "bad val",
        "breakMode": "unhandled",
        "threadId": 7,
    }
    result = extract_payload("exception", data)
    assert result is not None
    assert result["exceptionId"] == "ValueError"
    assert result["description"] == "bad val"
    assert result["breakMode"] == "unhandled"
    assert result["threadId"] == 7


def test_breakpoint_defaults() -> None:
    result = extract_payload("breakpoint", {})
    assert result == {"reason": "changed", "breakpoint": {}}


def test_breakpoint_explicit_values() -> None:
    bp = {"id": 5, "verified": True}
    result = extract_payload("breakpoint", {"reason": "new", "breakpoint": bp})
    assert result is not None
    assert result["reason"] == "new"
    assert result["breakpoint"] == bp


def test_module_defaults() -> None:
    result = extract_payload("module", {})
    assert result == {"reason": "new", "module": {}}


def test_module_explicit_values() -> None:
    mod = {"id": "mymod", "name": "mymod"}
    result = extract_payload("module", {"reason": "removed", "module": mod})
    assert result is not None
    assert result["reason"] == "removed"
    assert result["module"] == mod


def test_process_defaults() -> None:
    result = extract_payload("process", {})
    assert result == {
        "name": "",
        "systemProcessId": None,
        "isLocalProcess": True,
        "startMethod": "launch",
    }


def test_process_explicit_values() -> None:
    data = {
        "name": "myapp",
        "systemProcessId": 1234,
        "isLocalProcess": False,
        "startMethod": "attach",
    }
    result = extract_payload("process", data)
    assert result is not None
    assert result["name"] == "myapp"
    assert result["systemProcessId"] == 1234
    assert result["isLocalProcess"] is False
    assert result["startMethod"] == "attach"


def test_loaded_source_defaults() -> None:
    result = extract_payload("loadedSource", {})
    assert result == {"reason": "new", "source": {}}


def test_loaded_source_explicit_values() -> None:
    src = {"path": "/tmp/foo.py"}
    result = extract_payload("loadedSource", {"reason": "changed", "source": src})
    assert result is not None
    assert result["reason"] == "changed"
    assert result["source"] == src


def test_stopped_defaults() -> None:
    result = extract_payload("stopped", {})
    assert result is not None
    assert result == {
        "reason": "breakpoint",
        "threadId": 1,
        "allThreadsStopped": True,
    }
    assert "text" not in result


def test_stopped_with_text() -> None:
    data = {
        "reason": "exception",
        "threadId": 3,
        "allThreadsStopped": False,
        "text": "ZeroDivisionError",
    }
    result = extract_payload("stopped", data)
    assert result is not None
    assert result["reason"] == "exception"
    assert result["threadId"] == 3
    assert result["allThreadsStopped"] is False
    assert result["text"] == "ZeroDivisionError"


def test_stopped_without_text_field_absent() -> None:
    """The 'text' key must only appear when the source data contains it."""
    result = extract_payload("stopped", {"reason": "step"})
    assert result is not None
    assert "text" not in result


def test_thread_defaults() -> None:
    result = extract_payload("thread", {})
    assert result == {"reason": "started", "threadId": 1}


def test_thread_explicit_values() -> None:
    result = extract_payload("thread", {"reason": "exited", "threadId": 99})
    assert result is not None
    assert result["reason"] == "exited"
    assert result["threadId"] == 99


@pytest.mark.parametrize(
    "event_type",
    [
        "output",
        "continued",
        "exception",
        "breakpoint",
        "module",
        "process",
        "loadedSource",
        "stopped",
        "thread",
    ],
)
def test_all_known_types_return_dict(event_type: str) -> None:
    result = extract_payload(event_type, {})
    assert isinstance(result, dict)
