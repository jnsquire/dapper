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
from dapper.protocol.protocol import make_request_from_dict
from dapper.protocol.requests import ConfigurationDoneRequest
from dapper.protocol.requests import ContinueRequest
from dapper.protocol.requests import EvaluateRequest

# concrete DAP typed dictionaries used in this test suite
from dapper.protocol.requests import InitializeRequest
from dapper.protocol.requests import LaunchRequest
from dapper.protocol.requests import LaunchResponse
from dapper.protocol.requests import ScopesRequest
from dapper.protocol.requests import SetBreakpointsRequest
from dapper.protocol.requests import SetBreakpointsResponse
from dapper.protocol.requests import StackTraceRequest
from dapper.protocol.requests import ThreadsRequest
from dapper.protocol.requests import VariablesRequest

# Use the protocol message types from dapper.protocol.messages
RequestMessage = GenericRequest
ResponseMessage = GenericResponse
EventMessage = GenericEvent

# Use ProtocolMessage as the base type for all messages
MessageType = ProtocolMessage
# for convenience the aliases below remain generic; specific assertions
# in individual tests will use the concrete TypedDict classes imported above
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
    req = handler.create_request("launch", args, return_type=LaunchRequest)

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
    request = handler.create_request("setBreakpoints", return_type=SetBreakpointsRequest)
    resp: SetBreakpointsResponse = handler.create_response(
        request,
        True,
        body,
        return_type=SetBreakpointsResponse,
    )

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
    err_resp = handler.create_response(
        request,
        False,
        None,
        "Invalid expression",
        return_type=SetBreakpointsResponse,
    )

    assert err_resp["seq"] == 3
    assert err_resp["success"] is False
    assert "message" in err_resp
    assert err_resp.get("message") == "Invalid expression"


def test_event_message(handler: ProtocolHandler) -> None:
    """Test the Event message class"""
    body: dict[str, Any] = {"reason": "breakpoint", "threadId": 1}
    event = handler.create_event("stopped", body, return_type=GenericEvent)

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
    request_msg = handler.create_request(
        "launch", {"program": "test.py"}, return_type=LaunchRequest
    )
    response_msg = handler.create_response(
        handler.create_request("launch", return_type=LaunchRequest),
        True,
        return_type=LaunchResponse,
    )
    event_msg = handler.create_event("stopped", {"reason": "breakpoint"}, return_type=GenericEvent)

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
    """Test the error-response behavior of ``create_response``.

    The former ``create_error_response`` helper built a specific body
    with ``{error: "ProtocolError", details: {command: …}}``; exercise
    the same pattern here to keep coverage.
    """
    request = handler.create_request("launch", {"program": "test.py"}, return_type=LaunchRequest)

    # normal failure with explicit message
    error_resp = handler.create_response(
        request=request,
        success=False,
        body=None,
        error_message="Failed to launch",
        return_type=LaunchResponse,
    )

    assert error_resp["seq"] == 2
    assert error_resp["type"] == "response"
    assert error_resp["request_seq"] == 1
    assert error_resp["success"] is False
    assert error_resp["command"] == "launch"
    assert error_resp.get("message") == "Failed to launch"
    assert "body" not in error_resp

    # missing message case
    error_resp_no_msg = handler.create_response(
        request=request,
        success=False,
        body=None,
        error_message=None,
        return_type=LaunchResponse,
    )
    assert "message" not in error_resp_no_msg

    # manually construct the canonical error body and round-trip it via
    # create_response to ensure callers can easily build the same envelope.
    canonical_body = {"error": "ProtocolError", "details": {"command": "launch"}}
    canonical_error = handler.create_response(
        request,
        False,
        canonical_body,
        "Failed to launch",
        return_type=LaunchResponse,
    )
    assert canonical_error["success"] is False
    assert canonical_error.get("message") == "Failed to launch"
    bdict = cast("dict[str, Any]", canonical_error.get("body", {}))
    assert bdict["error"] == "ProtocolError"
    assert bdict["details"]["command"] == "launch"


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

    request = handler.create_request("initialize", args, return_type=InitializeRequest)

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

    request = handler.create_request("launch", args, return_type=LaunchRequest)

    assert request["command"] == "launch"
    assert request["arguments"] == args
    assert request["type"] == "request"


def test_create_launch_request_no_args(handler):
    """Test creating launch request with no arguments"""
    request = handler.create_request("launch", return_type=LaunchRequest)

    assert request["command"] == "launch"
    assert "arguments" not in request or request["arguments"] is None
    assert request["type"] == "request"


def test_create_configuration_done_request(handler):
    """Test creating configurationDone requests"""
    request = handler.create_request("configurationDone", return_type=ConfigurationDoneRequest)

    assert request["command"] == "configurationDone"
    assert request["type"] == "request"


def test_create_set_breakpoints_request(handler):
    """Test creating setBreakpoints requests"""
    args = {
        "source": {"path": "/path/to/file.py"},
        "breakpoints": [{"line": 10, "condition": "x > 5"}, {"line": 20}],
    }

    request = handler.create_request("setBreakpoints", args, return_type=SetBreakpointsRequest)

    assert request["command"] == "setBreakpoints"
    assert request["arguments"] == args
    assert request["type"] == "request"


def test_create_continue_request(handler):
    """Test creating continue requests"""
    args = {"threadId": 1}

    request = handler.create_request("continue", args, return_type=ContinueRequest)

    assert request["command"] == "continue"
    assert request["arguments"] == args
    assert request["type"] == "request"


def test_create_threads_request(handler):
    """Test creating threads requests"""
    request = handler.create_request("threads", return_type=ThreadsRequest)

    assert request["command"] == "threads"
    assert request["type"] == "request"


def test_create_stack_trace_request(handler):
    """Test creating stackTrace requests"""
    args = {"threadId": 1, "startFrame": 0, "levels": 20}

    request = handler.create_request("stackTrace", args, return_type=StackTraceRequest)

    assert request["command"] == "stackTrace"
    assert request["arguments"] == args
    assert request["type"] == "request"


def test_create_scopes_request(handler):
    """Test creating scopes requests"""
    args = {"frameId": 1}

    request = handler.create_request("scopes", args, return_type=ScopesRequest)

    assert request["command"] == "scopes"
    assert request["arguments"] == args
    assert request["type"] == "request"


def test_create_variables_request(handler):
    """Test creating variables requests"""
    args = {"variablesReference": 1001}

    request = handler.create_request("variables", args, return_type=VariablesRequest)

    assert request["command"] == "variables"
    assert request["arguments"] == args
    assert request["type"] == "request"


def test_create_evaluate_request(handler):
    """Test creating evaluate requests"""
    args = {"expression": "x + 1", "frameId": 1, "context": "watch"}

    request = handler.create_request("evaluate", args, return_type=EvaluateRequest)

    assert request["command"] == "evaluate"
    assert request["arguments"] == args
    assert request["type"] == "request"


def test_create_evaluate_request_no_frame(handler):
    """Test creating evaluate request without frame context"""
    args = {"expression": "len(sys.path)", "context": "repl"}

    request = handler.create_request("evaluate", args, return_type=EvaluateRequest)

    assert request["command"] == "evaluate"
    assert request["arguments"] == args
    assert request["type"] == "request"


def test_create_initialized_event(handler):
    """Test creating initialized events"""
    event = handler.create_initialized_event()

    assert event["event"] == "initialized"
    assert event["type"] == "event"
    assert "body" not in event or event["body"] is None


def test_create_stopped_event(handler):
    """Test creating stopped events"""
    event = handler.create_stopped_event("breakpoint", 1, text="Breakpoint hit")

    assert event["event"] == "stopped"
    assert event["body"] == {
        "reason": "breakpoint",
        "threadId": 1,
        "allThreadsStopped": False,
        "text": "Breakpoint hit",
    }
    assert event["type"] == "event"


def test_create_stopped_event_no_text(handler):
    """Test creating stopped event without text"""
    event = handler.create_stopped_event("step", 1)

    assert event["event"] == "stopped"
    assert event["body"] == {"reason": "step", "threadId": 1, "allThreadsStopped": False}
    assert event["type"] == "event"


def test_create_exited_event(handler):
    """Test creating exited events"""
    event = handler.create_exited_event(0)

    assert event["event"] == "exited"
    assert event["body"] == {"exitCode": 0}
    assert event["type"] == "event"


def test_create_terminated_event(handler):
    """Test creating terminated events"""
    event = handler.create_terminated_event(restart=True)

    assert event["event"] == "terminated"
    assert event["body"] == {"restart": True}
    assert event["type"] == "event"


def test_create_terminated_event_no_restart(handler):
    """Test creating terminated event without restart info"""
    event = handler.create_terminated_event()

    assert event["event"] == "terminated"
    assert event["type"] == "event"


def test_create_thread_event(handler):
    """Test creating thread events"""
    event = handler.create_thread_event("started", 2)

    assert event["event"] == "thread"
    assert event["body"] == {"reason": "started", "threadId": 2}
    assert event["type"] == "event"


def test_create_output_event(handler):
    """Test creating output events"""
    event = handler.create_output_event("Hello, World!\n", category="stdout")

    assert event["event"] == "output"
    assert event["body"] == {
        "output": "Hello, World!\n",
        "category": "stdout",
    }
    assert event["type"] == "event"


def test_create_output_event_default_category(handler):
    """Test creating output event with default category"""
    event = handler.create_output_event("Debug output\n")

    assert event["event"] == "output"
    assert event["body"] == {"output": "Debug output\n", "category": "console"}
    assert event["type"] == "event"


def test_create_breakpoint_event(handler):
    """Test creating breakpoint events"""
    breakpoint_info = {
        "id": 1,
        "verified": True,
        "line": 10,
        "source": {"path": "/test.py"},
    }

    event = handler.create_breakpoint_event("new", breakpoint_info)

    assert event["event"] == "breakpoint"
    assert event["type"] == "event"

    body = event["body"]
    assert body["reason"] == "new"
    assert body["breakpoint"] == breakpoint_info


def test_sequence_counter_increment(handler):
    """Test that sequence counter increments properly"""
    req1 = handler.create_request("launch", return_type=LaunchRequest)
    assert req1["seq"] == 1

    req2 = handler.create_request("continue", return_type=ContinueRequest)
    assert req2["seq"] == 2

    resp = handler.create_response(req1, True, return_type=LaunchResponse)
    assert resp["seq"] == 3

    event = handler.create_stopped_event("breakpoint", 1)
    assert event["seq"] == 4


def test_protocol_factory_sequence_is_thread_safe() -> None:
    """Concurrent sequence generation should produce unique values."""
    factory = ProtocolFactory(seq_start=1)
    collected: list[int] = []
    collect_lock = threading.Lock()

    def _worker() -> None:
        local: list[int] = []
        for _ in range(100):
            # specify concrete type for better typing even when return_type
            # wasn't required previously
            request = factory.create_request("launch", return_type=LaunchRequest)
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


def test_request_maker_helpers(handler: ProtocolHandler) -> None:
    """Ensure the generic request-maker factory behaves at runtime."""

    # dict-based variant only - the keyword-arg helper was removed because
    # it wasn't used anywhere in the codebase.
    create_launch = make_request_from_dict(handler, "launch", return_type=LaunchRequest)  # type: ignore[arg-type]
    req = create_launch({"program": "foo"})
    assert req["command"] == "launch"
    assert req["arguments"]["program"] == "foo"
