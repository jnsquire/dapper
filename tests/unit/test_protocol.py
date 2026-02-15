"""
Pytest-style tests for the Debug Adapter Protocol message handling.
"""

from __future__ import annotations

import json
import threading
from typing import Any
from typing import cast

import pytest

from dapper.protocol.messages import GenericEvent
from dapper.protocol.messages import GenericRequest
from dapper.protocol.messages import GenericResponse
from dapper.protocol.messages import ProtocolMessage
from dapper.protocol.protocol import ProtocolError
from dapper.protocol.protocol import ProtocolFactory
from dapper.protocol.protocol import ProtocolHandler

# Use the protocol message types from dapper.protocol.messages
RequestMessage = GenericRequest
ResponseMessage = GenericResponse
EventMessage = GenericEvent

# Use ProtocolMessage as the base type for all messages
MessageType = ProtocolMessage
RequestType = GenericRequest
ResponseType = GenericResponse
EventType = GenericEvent

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler() -> ProtocolHandler:
    """Create a protocol handler for testing."""
    return ProtocolHandler()


# ---------------------------------------------------------------------------
# Protocol Message Tests
# ---------------------------------------------------------------------------


def test_request_message(handler: ProtocolHandler) -> None:
    """Test the Request message class"""
    args: dict[str, Any] = {"program": "test.py", "stopOnEntry": True}
    req = handler.create_request("launch", args)

    # Test attributes
    assert req["seq"] == 1
    assert req["command"] == "launch"
    assert req["arguments"] == args

    # Test conversion to dict
    req_dict = cast("dict[str, Any]", req)
    assert req_dict["seq"] == 1
    assert req_dict["type"] == "request"
    assert req_dict["command"] == "launch"
    assert req_dict["arguments"] == args


def test_response_message(handler: ProtocolHandler) -> None:
    """Test the Response message class"""
    body: dict[str, Any] = {"breakpoints": [{"verified": True, "line": 10}]}
    request = handler.create_request("setBreakpoints", return_type=GenericRequest)
    resp: ResponseType = handler.create_response(request, True, body)

    # Test attributes
    assert resp["seq"] == 2
    assert resp["request_seq"] == 1
    assert resp["success"] is True
    assert resp["command"] == "setBreakpoints"
    assert "body" in resp
    assert resp.get("body") == body

    # Test conversion to dict
    resp_dict = cast("dict[str, Any]", resp)
    assert resp_dict["seq"] == 2
    assert resp_dict["type"] == "response"
    assert resp_dict["request_seq"] == 1
    assert resp_dict["success"] is True
    assert resp_dict["command"] == "setBreakpoints"
    assert "body" in resp_dict
    assert resp_dict.get("body") == body

    # Test error response
    err_resp = cast(
        "GenericResponse", handler.create_response(request, False, None, "Invalid expression")
    )

    assert err_resp["seq"] == 3
    assert err_resp["success"] is False
    assert "message" in err_resp
    assert err_resp.get("message") == "Invalid expression"


def test_event_message(handler: ProtocolHandler) -> None:
    """Test the Event message class"""
    body: dict[str, Any] = {"reason": "breakpoint", "threadId": 1}
    event: EventType = handler.create_event("stopped", body)

    # Test attributes
    assert event["seq"] == 1
    assert event["event"] == "stopped"
    assert "body" in event
    assert event.get("body") == body

    # Test conversion to dict
    event_dict = cast("dict[str, Any]", event)
    assert event_dict["seq"] == 1
    assert event_dict["type"] == "event"
    assert event_dict["event"] == "stopped"
    assert "body" in event_dict
    assert event_dict.get("body") == body


def test_json_serialization(handler: ProtocolHandler) -> None:
    """Test that all messages can be properly serialized to JSON"""
    # Create a base message with explicit type to satisfy the type checker
    base_message: dict[str, Any] = {"seq": 1, "type": "request"}

    # Create test messages
    request_msg = handler.create_request("launch", {"program": "test.py"})
    response_msg = handler.create_response(handler.create_request("launch"), True)
    event_msg = handler.create_event("stopped", {"reason": "breakpoint"})

    # Test each message type separately to avoid mixed type issues
    for msg in [
        base_message,
        cast("dict[str, Any]", request_msg),
        cast("dict[str, Any]", response_msg),
        cast("dict[str, Any]", event_msg),
    ]:
        # Convert to JSON string
        json_str = json.dumps(msg)

        # Parse back from JSON
        parsed_dict = json.loads(json_str)

        # Verify the structure is preserved
        assert parsed_dict == msg


def test_parse_message_valid_request(handler: ProtocolHandler) -> None:
    """Test parsing a valid request message"""
    json_msg: dict[str, Any] = {
        "seq": 1,
        "type": "request",
        "command": "launch",
        "arguments": {"program": "test.py"},
    }
    json_str: str = json.dumps(json_msg)

    parsed = handler.parse_message(json_str)
    assert parsed["seq"] == 1
    assert parsed["type"] == "request"
    assert parsed["command"] == "launch"
    assert parsed["arguments"] == {"program": "test.py"}


def test_parse_message_valid_response(handler: ProtocolHandler) -> None:
    """Test parsing a valid response message"""
    json_msg: dict[str, Any] = {
        "seq": 2,
        "type": "response",
        "request_seq": 1,
        "success": True,
        "command": "launch",
        "body": {"threadId": 1},
    }
    json_str: str = json.dumps(json_msg)

    parsed = handler.parse_message(json_str)
    assert parsed["seq"] == 2
    assert parsed["type"] == "response"
    assert parsed["request_seq"] == 1
    assert parsed["success"] is True
    assert parsed["command"] == "launch"
    assert parsed["body"] == {"threadId": 1}


def test_parse_message_valid_event(handler: ProtocolHandler) -> None:
    """Test parsing a valid event message"""
    json_msg: dict[str, Any] = {
        "seq": 3,
        "type": "event",
        "event": "stopped",
        "body": {"reason": "breakpoint", "threadId": 1},
    }
    json_str: str = json.dumps(json_msg)

    parsed = handler.parse_message(json_str)
    assert parsed["seq"] == 3
    assert parsed["type"] == "event"
    assert parsed["event"] == "stopped"
    assert parsed["body"] == {"reason": "breakpoint", "threadId": 1}


def test_parse_message_invalid_json(handler: ProtocolHandler) -> None:
    """Test parsing invalid JSON raises ProtocolError"""
    invalid_json: str = "{invalid json"

    with pytest.raises(ProtocolError) as exc_info:
        handler.parse_message(invalid_json)

    assert "Failed to parse message as JSON" in str(exc_info.value)


def test_parse_message_missing_type(handler: ProtocolHandler) -> None:
    """Test parsing message without type field"""
    json_msg: dict[str, Any] = {"seq": 1, "command": "launch"}
    json_str: str = json.dumps(json_msg)

    with pytest.raises(ProtocolError) as exc_info:
        handler.parse_message(json_str)

    assert "Message missing 'type' field" in str(exc_info.value)


def test_parse_message_unknown_type(handler: ProtocolHandler) -> None:
    """Test parsing message with unknown type"""
    json_msg: dict[str, Any] = {"seq": 1, "type": "unknown", "command": "launch"}
    json_str: str = json.dumps(json_msg)

    with pytest.raises(ProtocolError) as exc_info:
        handler.parse_message(json_str)

    assert "Invalid message type: unknown" in str(exc_info.value)


def test_create_error_response(handler: ProtocolHandler) -> None:
    """Test creating error responses"""
    request = handler.create_request("launch", {"program": "test.py"})

    # Test error response with message
    error_resp = handler.create_response(
        request=request, success=False, body=None, error_message="Failed to launch"
    )

    assert error_resp["seq"] == 2
    assert error_resp["type"] == "response"
    assert error_resp["request_seq"] == 1
    assert error_resp["success"] is False
    assert error_resp["command"] == "launch"
    assert (
        error_resp.get("message") == "Failed to launch"
    )  # Use .get() since message is NotRequired
    assert "body" not in error_resp

    # Test error response without message
    error_resp_no_msg = handler.create_response(
        request=request, success=False, body=None, error_message=None
    )
    assert (
        "message" not in error_resp_no_msg
    )  # Should not include message when error_message is None

    # Test standardized error response helper
    canonical_error_resp = handler.create_error_response(request, "Failed to launch")
    assert canonical_error_resp["success"] is False
    assert canonical_error_resp["message"] == "Failed to launch"
    assert canonical_error_resp["body"]["error"] == "ProtocolError"
    assert canonical_error_resp["body"]["details"]["command"] == "launch"


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


def test_protocol_factory_sequence_is_thread_safe() -> None:
    """Concurrent sequence generation should produce unique values."""
    factory = ProtocolFactory(seq_start=1)
    collected: list[int] = []
    collect_lock = threading.Lock()

    def _worker() -> None:
        local: list[int] = []
        for _ in range(100):
            request = factory.create_request("launch")
            local.append(request["seq"])
        with collect_lock:
            collected.extend(local)

    threads = [threading.Thread(target=_worker) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(collected) == 1000
    assert len(set(collected)) == 1000
    assert sorted(collected) == list(range(1, 1001))
