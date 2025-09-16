"""Pytest-style tests for the Debug Adapter Protocol message classes.

Converted from unittest.TestCase to plain pytest functions.
"""

from __future__ import annotations

import json

import pytest

from dapper.protocol import ProtocolError
from dapper.protocol import ProtocolHandler
from dapper.protocol_types import ProtocolMessage

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler():
    """Create a protocol handler for testing."""
    return ProtocolHandler()


# ---------------------------------------------------------------------------
# Protocol Message Tests
# ---------------------------------------------------------------------------


def test_request_message(handler):
    """Test the Request message class"""
    args = {"program": "test.py", "stopOnEntry": True}
    req = handler.create_request("launch", args)

    # Test attributes
    assert req["seq"] == 1
    assert req["command"] == "launch"
    assert req["arguments"] == args

    # Test conversion to dict
    req_dict = req
    assert req_dict["seq"] == 1
    assert req_dict["type"] == "request"
    assert req_dict["command"] == "launch"
    assert req_dict["arguments"] == args


def test_response_message(handler):
    """Test the Response message class"""
    body = {"breakpoints": [{"verified": True, "line": 10}]}
    request = handler.create_request("setBreakpoints")
    resp = handler.create_response(request, True, body)

    # Test attributes
    assert resp["seq"] == 2
    assert resp["request_seq"] == 1
    assert resp["success"] is True
    assert resp["command"] == "setBreakpoints"
    assert "body" in resp
    assert resp.get("body") == body

    # Test conversion to dict
    resp_dict = resp
    assert resp_dict["seq"] == 2
    assert resp_dict["type"] == "response"
    assert resp_dict["request_seq"] == 1
    assert resp_dict["success"] is True
    assert resp_dict["command"] == "setBreakpoints"
    assert "body" in resp_dict
    assert resp_dict.get("body") == body

    # Test error response
    err_resp = handler.create_response(request, False, None, "Invalid expression")

    err_dict = err_resp
    assert err_dict["seq"] == 3
    assert err_dict["success"] is False
    assert "message" in err_dict
    assert err_dict.get("message") == "Invalid expression"


def test_event_message(handler):
    """Test the Event message class"""
    body = {"reason": "breakpoint", "threadId": 1}
    event = handler.create_event("stopped", body)

    # Test attributes
    assert event["seq"] == 1
    assert event["event"] == "stopped"
    assert "body" in event
    assert event.get("body") == body

    # Test conversion to dict
    event_dict = event
    assert event_dict["seq"] == 1
    assert event_dict["type"] == "event"
    assert event_dict["event"] == "stopped"
    assert "body" in event_dict
    assert event_dict.get("body") == body


def test_json_serialization(handler):
    """Test that all messages can be properly serialized to JSON"""
    messages = [
        {"seq": 1, "type": "request"},  # ProtocolMessage base
        handler.create_request("launch", {"program": "test.py"}),
        handler.create_response(handler.create_request("launch"), True),
        handler.create_event("stopped", {"reason": "breakpoint"}),
    ]

    for msg in messages:
        # Convert to dict then JSON string
        msg_dict = msg
        json_str = json.dumps(msg_dict)

        # Parse back from JSON
        parsed_dict = json.loads(json_str)

        # Verify the structure is preserved
        assert parsed_dict == msg_dict


def test_parse_message_valid_request(handler):
    """Test parsing a valid request message"""
    json_msg = {
        "seq": 1,
        "type": "request",
        "command": "launch",
        "arguments": {"program": "test.py"},
    }
    json_str = json.dumps(json_msg)

    parsed = handler.parse_message(json_str)
    assert parsed["seq"] == 1
    assert parsed["type"] == "request"
    assert parsed["command"] == "launch"
    assert parsed["arguments"] == {"program": "test.py"}


def test_parse_message_valid_response(handler):
    """Test parsing a valid response message"""
    json_msg = {
        "seq": 2,
        "type": "response",
        "request_seq": 1,
        "success": True,
        "command": "launch",
        "body": {"threadId": 1},
    }
    json_str = json.dumps(json_msg)

    parsed = handler.parse_message(json_str)
    assert parsed["seq"] == 2
    assert parsed["type"] == "response"
    assert parsed["request_seq"] == 1
    assert parsed["success"] is True
    assert parsed["command"] == "launch"
    assert parsed["body"] == {"threadId": 1}


def test_parse_message_valid_event(handler):
    """Test parsing a valid event message"""
    json_msg = {
        "seq": 3,
        "type": "event",
        "event": "stopped",
        "body": {"reason": "breakpoint", "threadId": 1},
    }
    json_str = json.dumps(json_msg)

    parsed = handler.parse_message(json_str)
    assert parsed["seq"] == 3
    assert parsed["type"] == "event"
    assert parsed["event"] == "stopped"
    assert parsed["body"] == {"reason": "breakpoint", "threadId": 1}


def test_parse_message_invalid_json(handler):
    """Test parsing invalid JSON raises ProtocolError"""
    invalid_json = "{invalid json"

    with pytest.raises(ProtocolError) as exc_info:
        handler.parse_message(invalid_json)

    assert "Failed to parse message as JSON" in str(exc_info.value)


def test_parse_message_missing_type(handler):
    """Test parsing message without type field"""
    json_msg = {"seq": 1, "command": "launch"}
    json_str = json.dumps(json_msg)

    with pytest.raises(ProtocolError) as exc_info:
        handler.parse_message(json_str)

    assert "Message missing 'type' field" in str(exc_info.value)


def test_parse_message_unknown_type(handler):
    """Test parsing message with unknown type"""
    json_msg = {"seq": 1, "type": "unknown", "command": "launch"}
    json_str = json.dumps(json_msg)

    with pytest.raises(ProtocolError) as exc_info:
        handler.parse_message(json_str)

    assert "Invalid message type: unknown" in str(exc_info.value)


def test_create_error_response(handler):
    """Test creating error responses"""
    request = handler.create_request("launch", {"program": "test.py"})

    # Test error response with just message
    error_resp = handler.create_response(request, False, None, "Failed to launch")

    assert error_resp["seq"] == 2
    assert error_resp["type"] == "response"
    assert error_resp["request_seq"] == 1
    assert error_resp["success"] is False
    assert error_resp["command"] == "launch"
    assert error_resp["message"] == "Failed to launch"
    assert "body" not in error_resp


def test_create_initialize_request(handler):
    """Test creating initialize requests"""
    args = {
        "clientID": "test-client",
        "clientName": "Test Client",
        "adapterID": "python",
        "pathFormat": "path",
        "linesStartAt1": True,
        "columnsStartAt1": True,
        "supportsVariableType": True,
        "supportsVariablePaging": False,
        "supportsRunInTerminalRequest": True,
    }

    request = handler.create_request("initialize", args)

    assert request["command"] == "initialize"
    assert request["arguments"] == args
    assert request["type"] == "request"


def test_create_launch_request(handler):
    """Test creating launch requests"""
    args = {
        "program": "/path/to/program.py",
        "args": ["--verbose", "--debug"],
        "stopOnEntry": True,
        "console": "integratedTerminal",
    }

    request = handler.create_request("launch", args)

    assert request["command"] == "launch"
    assert request["arguments"] == args
    assert request["type"] == "request"


def test_create_launch_request_no_args(handler):
    """Test creating launch request with no arguments"""
    request = handler.create_request("launch")

    assert request["command"] == "launch"
    assert "arguments" not in request or request["arguments"] is None
    assert request["type"] == "request"


def test_create_configuration_done_request(handler):
    """Test creating configurationDone requests"""
    request = handler.create_request("configurationDone")

    assert request["command"] == "configurationDone"
    assert request["type"] == "request"


def test_create_set_breakpoints_request(handler):
    """Test creating setBreakpoints requests"""
    args = {
        "source": {"path": "/path/to/file.py"},
        "breakpoints": [{"line": 10, "condition": "x > 5"}, {"line": 20}],
    }

    request = handler.create_request("setBreakpoints", args)

    assert request["command"] == "setBreakpoints"
    assert request["arguments"] == args
    assert request["type"] == "request"


def test_create_continue_request(handler):
    """Test creating continue requests"""
    args = {"threadId": 1}

    request = handler.create_request("continue", args)

    assert request["command"] == "continue"
    assert request["arguments"] == args
    assert request["type"] == "request"


def test_create_threads_request(handler):
    """Test creating threads requests"""
    request = handler.create_request("threads")

    assert request["command"] == "threads"
    assert request["type"] == "request"


def test_create_stack_trace_request(handler):
    """Test creating stackTrace requests"""
    args = {"threadId": 1, "startFrame": 0, "levels": 20}

    request = handler.create_request("stackTrace", args)

    assert request["command"] == "stackTrace"
    assert request["arguments"] == args
    assert request["type"] == "request"


def test_create_scopes_request(handler):
    """Test creating scopes requests"""
    args = {"frameId": 1}

    request = handler.create_request("scopes", args)

    assert request["command"] == "scopes"
    assert request["arguments"] == args
    assert request["type"] == "request"


def test_create_variables_request(handler):
    """Test creating variables requests"""
    args = {"variablesReference": 1001}

    request = handler.create_request("variables", args)

    assert request["command"] == "variables"
    assert request["arguments"] == args
    assert request["type"] == "request"


def test_create_evaluate_request(handler):
    """Test creating evaluate requests"""
    args = {"expression": "x + 1", "frameId": 1, "context": "watch"}

    request = handler.create_request("evaluate", args)

    assert request["command"] == "evaluate"
    assert request["arguments"] == args
    assert request["type"] == "request"


def test_create_evaluate_request_no_frame(handler):
    """Test creating evaluate request without frame context"""
    args = {"expression": "len(sys.path)", "context": "repl"}

    request = handler.create_request("evaluate", args)

    assert request["command"] == "evaluate"
    assert request["arguments"] == args
    assert request["type"] == "request"


def test_create_initialized_event(handler):
    """Test creating initialized events"""
    event = handler.create_event("initialized")

    assert event["event"] == "initialized"
    assert event["type"] == "event"
    assert "body" not in event or event["body"] is None


def test_create_stopped_event(handler):
    """Test creating stopped events"""
    body = {
        "reason": "breakpoint",
        "threadId": 1,
        "allThreadsStopped": True,
        "text": "Breakpoint hit",
    }

    event = handler.create_event("stopped", body)

    assert event["event"] == "stopped"
    assert event["body"] == body
    assert event["type"] == "event"


def test_create_stopped_event_no_text(handler):
    """Test creating stopped event without text"""
    body = {"reason": "step", "threadId": 1, "allThreadsStopped": False}

    event = handler.create_event("stopped", body)

    assert event["event"] == "stopped"
    assert event["body"] == body
    assert event["type"] == "event"


def test_create_exited_event(handler):
    """Test creating exited events"""
    body = {"exitCode": 0}

    event = handler.create_event("exited", body)

    assert event["event"] == "exited"
    assert event["body"] == body
    assert event["type"] == "event"


def test_create_terminated_event(handler):
    """Test creating terminated events"""
    body = {"restart": False}

    event = handler.create_event("terminated", body)

    assert event["event"] == "terminated"
    assert event["body"] == body
    assert event["type"] == "event"


def test_create_terminated_event_no_restart(handler):
    """Test creating terminated event without restart info"""
    event = handler.create_event("terminated")

    assert event["event"] == "terminated"
    assert event["type"] == "event"


def test_create_thread_event(handler):
    """Test creating thread events"""
    body = {"reason": "started", "threadId": 2}

    event = handler.create_event("thread", body)

    assert event["event"] == "thread"
    assert event["body"] == body
    assert event["type"] == "event"


def test_create_output_event(handler):
    """Test creating output events"""
    body = {
        "category": "stdout",
        "output": "Hello, World!\n",
        "source": {"path": "/test.py"},
        "line": 1,
    }

    event = handler.create_event("output", body)

    assert event["event"] == "output"
    assert event["body"] == body
    assert event["type"] == "event"


def test_create_output_event_default_category(handler):
    """Test creating output event with default category"""
    body = {"output": "Debug output\n"}

    event = handler.create_event("output", body)

    assert event["event"] == "output"
    assert event["body"] == body
    assert event["type"] == "event"


def test_create_breakpoint_event(handler):
    """Test creating breakpoint events"""
    breakpoint_info = {
        "id": 1,
        "verified": True,
        "line": 10,
        "source": {"path": "/test.py"},
    }

    body = {"reason": "new", "breakpoint": breakpoint_info}

    event = handler.create_event("breakpoint", body)

    assert event["event"] == "breakpoint"
    assert event["type"] == "event"

    body = event["body"]
    assert body["reason"] == "new"
    assert body["breakpoint"] == breakpoint_info


def test_sequence_counter_increment(handler):
    """Test that sequence counter increments properly"""
    req1 = handler.create_request("launch")
    assert req1["seq"] == 1

    req2 = handler.create_request("continue")
    assert req2["seq"] == 2

    resp = handler.create_response(req1, True)
    assert resp["seq"] == 3

    event = handler.create_event("stopped")
    assert event["seq"] == 4
