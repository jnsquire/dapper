from __future__ import annotations

import json
from typing import Any
from typing import cast

import pytest

from dapper.protocol import ProtocolError
from dapper.protocol import ProtocolHandler


@pytest.fixture
def handler() -> ProtocolHandler:
    return ProtocolHandler()


# -----------------------------
# parse_message error paths
# -----------------------------


def test_parse_message_non_object(handler: ProtocolHandler) -> None:
    msg = json.dumps(["not", "an", "object"])  # valid JSON array, not an object
    with pytest.raises(ProtocolError) as exc:
        handler.parse_message(msg)
    assert "Message is not a JSON object" in str(exc.value)


def test_parse_message_missing_seq(handler: ProtocolHandler) -> None:
    msg = json.dumps({"type": "request", "command": "launch"})
    with pytest.raises(ProtocolError) as exc:
        handler.parse_message(msg)
    assert "Message missing 'seq' field" in str(exc.value)


def test_parse_message_request_missing_command(handler: ProtocolHandler) -> None:
    msg = json.dumps({"seq": 1, "type": "request"})
    with pytest.raises(ProtocolError) as exc:
        handler.parse_message(msg)
    assert "Request message missing 'command' field" in str(exc.value)


def test_parse_message_response_missing_fields(handler: ProtocolHandler) -> None:
    base = {"seq": 2, "type": "response", "request_seq": 1, "success": True, "command": "foo"}
    for missing in ("request_seq", "success", "command"):
        payload = dict(base)
        payload.pop(missing)
        with pytest.raises(ProtocolError) as exc:
            handler.parse_message(json.dumps(payload))
        assert f"Response message missing '{missing}' field" in str(exc.value)


def test_parse_message_event_missing_event_field(handler: ProtocolHandler) -> None:
    msg = json.dumps({"seq": 3, "type": "event"})
    with pytest.raises(ProtocolError) as exc:
        handler.parse_message(msg)
    assert "Event message missing 'event' field" in str(exc.value)


# -----------------------------
# create_response variants
# -----------------------------


def test_create_error_response_wrapper(handler: ProtocolHandler) -> None:
    req = handler.create_request("evaluate", {"expression": "x"})
    err = handler.create_error_response(req, "Boom")
    err_dict = cast("dict[str, Any]", err)
    assert err_dict["type"] == "response"
    assert err_dict["success"] is False
    assert err_dict["request_seq"] == req["seq"]
    assert err_dict["command"] == "evaluate"
    assert err_dict["message"] == "Boom"
    assert "body" in err_dict
    assert "error" in err_dict["body"]
    assert err_dict["body"]["error"]["format"] == "Boom"
    assert err_dict["body"]["error"]["showUser"] is True


def test_create_response_without_error_message(handler: ProtocolHandler) -> None:
    req = handler.create_request("launch")
    resp = handler.create_response(req, False)
    resp_dict = cast("dict[str, Any]", resp)
    assert resp_dict["type"] == "response"
    assert resp_dict["success"] is False
    assert "message" not in resp_dict  # no error_message provided
    assert "body" not in resp_dict  # body=None should not produce key


# -----------------------------
# Specialized request creators
# -----------------------------


def test_create_initialize_request(handler: ProtocolHandler) -> None:
    r = handler.create_initialize_request("client", "adapter")
    assert r["type"] == "request"
    assert r["command"] == "initialize"
    args = r["arguments"]
    assert args["clientID"] == "client"
    assert args["adapterID"] == "adapter"
    assert args["linesStartAt1"] is True
    assert args["columnsStartAt1"] is True


def test_create_launch_request_variants(handler: ProtocolHandler) -> None:
    r1 = handler.create_launch_request("/prog.py", ["--x"], no_debug=True)
    assert r1["command"] == "launch"
    args1 = r1["arguments"]
    assert args1["program"] == "/prog.py"
    assert args1["args"] == ["--x"]
    assert args1["noDebug"] is True

    r2 = handler.create_launch_request("/prog2.py")
    args2 = r2["arguments"]
    assert args2["program"] == "/prog2.py"
    assert "args" not in args2
    assert args2["noDebug"] is False


def test_create_configuration_done_set_breakpoints(handler: ProtocolHandler) -> None:
    rc = handler.create_configuration_done_request()
    assert rc["command"] == "configurationDone"

    rsb = handler.create_set_breakpoints_request({"path": "a.py"}, [{"line": 10}])
    assert rsb["command"] == "setBreakpoints"
    assert rsb["arguments"]["source"]["path"] == "a.py"
    assert rsb["arguments"]["breakpoints"][0]["line"] == 10


def test_create_continue_threads_stacktrace(handler: ProtocolHandler) -> None:
    r1 = handler.create_continue_request(7)
    assert r1["command"] == "continue"
    assert r1["arguments"]["threadId"] == 7

    r2 = handler.create_threads_request()
    assert r2["command"] == "threads"

    r3 = handler.create_stack_trace_request(9, start_frame=3, levels=5)
    args = r3["arguments"]
    assert args["threadId"] == 9
    assert args["startFrame"] == 3
    assert args["levels"] == 5


def test_create_scopes_variables_evaluate(handler: ProtocolHandler) -> None:
    rs = handler.create_scopes_request(101)
    assert rs["command"] == "scopes"
    assert rs["arguments"]["frameId"] == 101

    rv = handler.create_variables_request(202)
    assert rv["command"] == "variables"
    assert rv["arguments"]["variablesReference"] == 202

    re_no_frame = handler.create_evaluate_request("1+1")
    assert re_no_frame["command"] == "evaluate"
    assert re_no_frame["arguments"]["expression"] == "1+1"
    assert "frameId" not in re_no_frame["arguments"]

    re_with_frame = handler.create_evaluate_request("x", frame_id=303)
    assert re_with_frame["arguments"]["frameId"] == 303


# -----------------------------
# Specialized event creators
# -----------------------------


def test_create_initialized_and_stopped(handler: ProtocolHandler) -> None:
    e1 = handler.create_initialized_event()
    assert e1["type"] == "event"
    assert e1["event"] == "initialized"
    assert "body" not in e1

    e2 = handler.create_stopped_event("breakpoint", thread_id=1, text="hit")
    assert e2["event"] == "stopped"
    body = e2["body"]
    assert body["reason"] == "breakpoint"
    assert body["threadId"] == 1  # pyright: ignore[reportTypedDictNotRequiredAccess]
    assert body["allThreadsStopped"] is False  # pyright: ignore[reportTypedDictNotRequiredAccess]
    assert body["text"] == "hit"  # pyright: ignore[reportTypedDictNotRequiredAccess]

    e3 = handler.create_stopped_event("step", thread_id=2)
    assert "text" not in e3["body"]


def test_create_exited_terminated(handler: ProtocolHandler) -> None:
    e1 = handler.create_exited_event(0)
    assert e1["event"] == "exited"
    assert e1["body"]["exitCode"] == 0

    e2 = handler.create_terminated_event()
    assert e2["event"] == "terminated"
    assert "body" not in e2  # restart False -> omitted body

    e3 = handler.create_terminated_event(restart=True)
    assert e3["event"] == "terminated"
    assert e3["body"]["restart"] is True  # pyright: ignore[reportTypedDictNotRequiredAccess]


def test_create_thread_output_breakpoint(handler: ProtocolHandler) -> None:
    et = handler.create_thread_event("started", 42)
    assert et["event"] == "thread"
    assert et["body"]["threadId"] == 42

    eo_default = handler.create_output_event("hi")
    assert eo_default["event"] == "output"
    assert eo_default["body"]["category"] == "console"  # pyright: ignore[reportTypedDictNotRequiredAccess]

    eo_custom = handler.create_output_event("hello", category="stdout")
    assert eo_custom["body"]["category"] == "stdout"  # pyright: ignore[reportTypedDictNotRequiredAccess]
    assert eo_custom["body"]["output"] == "hello"

    eb = handler.create_breakpoint_event("new", {"id": 1, "line": 10})
    assert eb["event"] == "breakpoint"
    assert eb["body"]["reason"] == "new"
