"""

import sys
from pathlib import Path

# Add the project root to the Python path
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

Additional tests for protocol.py to increase coverage.

This test file focuses on areas not covered by the main test_protocol.py file,
including ProtocolFactory methods, specialized request/event creators, and
error handling paths.
"""

from __future__ import annotations

import json

import pytest

from dapper.protocol import ProtocolError
from dapper.protocol import ProtocolFactory
from dapper.protocol import ProtocolHandler

# ---------------------------------------------------------------------------
# ProtocolFactory Tests
# ---------------------------------------------------------------------------


def test_protocol_factory_initialization():
    """Test ProtocolFactory initialization with different seq_start values."""
    # Default seq_start
    factory = ProtocolFactory()
    assert factory.seq_counter == 1

    # Custom seq_start
    factory_custom = ProtocolFactory(seq_start=100)
    assert factory_custom.seq_counter == 100


def test_protocol_factory_sequence_generation():
    """Test that sequence numbers increment correctly."""
    factory = ProtocolFactory(seq_start=5)

    # Test _next_seq increments properly
    assert factory._next_seq() == 5
    assert factory._next_seq() == 6
    assert factory._next_seq() == 7


def test_protocol_factory_create_request_basic():
    """Test basic request creation without arguments."""
    factory = ProtocolFactory()

    request = factory.create_request("configurationDone")

    assert request["seq"] == 1
    assert request["type"] == "request"
    assert request["command"] == "configurationDone"
    assert "arguments" not in request


def test_protocol_factory_create_request_with_arguments():
    """Test request creation with arguments."""
    factory = ProtocolFactory()
    args = {"program": "test.py", "args": ["--verbose"]}

    request = factory.create_request("launch", args)

    assert request["seq"] == 1
    assert request["type"] == "request"
    assert request["command"] == "launch"
    assert request["arguments"] == args


def test_protocol_factory_create_response_success():
    """Test successful response creation."""
    factory = ProtocolFactory()
    request = factory.create_request("threads")
    body = {"threads": [{"id": 1, "name": "MainThread"}]}

    response = factory.create_response(request, True, body)

    assert response["seq"] == 2  # factory seq incremented
    assert response["type"] == "response"
    assert response["request_seq"] == 1
    assert response["success"] is True
    assert response["command"] == "threads"
    assert response["body"] == body
    assert "message" not in response


def test_protocol_factory_create_response_error():
    """Test error response creation."""
    factory = ProtocolFactory()
    request = factory.create_request("evaluate")
    error_msg = "Invalid expression"

    response = factory.create_response(request, False, None, error_msg)

    assert response["seq"] == 2
    assert response["type"] == "response"
    assert response["request_seq"] == 1
    assert response["success"] is False
    assert response["command"] == "evaluate"
    assert response.get("message") == error_msg
    assert "body" not in response


def test_protocol_factory_create_error_response():
    """Test dedicated error response creation method."""
    factory = ProtocolFactory()
    request = factory.create_request("setVariable")
    error_msg = "Variable not found"

    error_response = factory.create_error_response(request, error_msg)

    assert error_response["seq"] == 2
    assert error_response["type"] == "response"
    assert error_response["request_seq"] == 1
    assert error_response["success"] is False
    assert error_response["command"] == "setVariable"
    assert error_response.get("message") == error_msg
    assert "body" in error_response
    assert error_response["body"]["error"]["format"] == error_msg
    assert error_response["body"]["error"]["showUser"] is True


def test_protocol_factory_create_event_basic():
    """Test basic event creation without body."""
    factory = ProtocolFactory()

    event = factory.create_event("initialized")

    assert event["seq"] == 1
    assert event["type"] == "event"
    assert event["event"] == "initialized"
    assert "body" not in event


def test_protocol_factory_create_event_with_body():
    """Test event creation with body."""
    factory = ProtocolFactory()
    body = {"reason": "step", "threadId": 1}

    event = factory.create_event("stopped", body)

    assert event["seq"] == 1
    assert event["type"] == "event"
    assert event["event"] == "stopped"
    assert event["body"] == body


# ---------------------------------------------------------------------------
# Specialized Request Creator Tests
# ---------------------------------------------------------------------------


def test_create_initialize_request():
    """Test initialize request creation."""
    factory = ProtocolFactory()

    request = factory.create_initialize_request("vscode", "python")

    assert request["command"] == "initialize"
    args = request["arguments"]
    assert args["clientID"] == "vscode"
    assert args["adapterID"] == "python"
    assert args["linesStartAt1"] is True
    assert args["columnsStartAt1"] is True
    assert args["supportsVariableType"] is True
    assert args["supportsVariablePaging"] is True
    assert args["supportsRunInTerminalRequest"] is False


def test_create_launch_request_minimal():
    """Test launch request creation with minimal arguments."""
    factory = ProtocolFactory()

    request = factory.create_launch_request("main.py")

    assert request["command"] == "launch"
    args = request["arguments"]
    assert args["program"] == "main.py"
    assert args["noDebug"] is False
    assert "args" not in args


def test_create_launch_request_full():
    """Test launch request creation with all arguments."""
    factory = ProtocolFactory()

    request = factory.create_launch_request("main.py", ["--debug", "--port", "8080"], True)

    assert request["command"] == "launch"
    args = request["arguments"]
    assert args["program"] == "main.py"
    assert args["args"] == ["--debug", "--port", "8080"]
    assert args["noDebug"] is True


def test_create_configuration_done_request():
    """Test configuration done request creation."""
    factory = ProtocolFactory()

    request = factory.create_configuration_done_request()

    assert request["command"] == "configurationDone"
    assert "arguments" not in request


def test_create_set_breakpoints_request():
    """Test set breakpoints request creation."""
    factory = ProtocolFactory()
    source = {"path": "/path/to/file.py"}
    breakpoints = [{"line": 10, "condition": "x > 5"}]

    request = factory.create_set_breakpoints_request(source, breakpoints)

    assert request["command"] == "setBreakpoints"
    args = request["arguments"]
    assert args["source"] == source
    assert args["breakpoints"] == breakpoints


def test_create_continue_request():
    """Test continue request creation."""
    factory = ProtocolFactory()

    request = factory.create_continue_request(123)

    assert request["command"] == "continue"
    args = request["arguments"]
    assert args["threadId"] == 123


def test_create_threads_request():
    """Test threads request creation."""
    factory = ProtocolFactory()

    request = factory.create_threads_request()

    assert request["command"] == "threads"
    assert "arguments" not in request


def test_create_stack_trace_request():
    """Test stack trace request creation with default parameters."""
    factory = ProtocolFactory()

    request = factory.create_stack_trace_request(456)

    assert request["command"] == "stackTrace"
    args = request["arguments"]
    assert args["threadId"] == 456
    assert args["startFrame"] == 0
    assert args["levels"] == 20


def test_create_stack_trace_request_custom():
    """Test stack trace request creation with custom parameters."""
    factory = ProtocolFactory()

    request = factory.create_stack_trace_request(789, 5, 10)

    assert request["command"] == "stackTrace"
    args = request["arguments"]
    assert args["threadId"] == 789
    assert args["startFrame"] == 5
    assert args["levels"] == 10


def test_create_scopes_request():
    """Test scopes request creation."""
    factory = ProtocolFactory()

    request = factory.create_scopes_request(42)

    assert request["command"] == "scopes"
    args = request["arguments"]
    assert args["frameId"] == 42


def test_create_variables_request():
    """Test variables request creation."""
    factory = ProtocolFactory()

    request = factory.create_variables_request(1001)

    assert request["command"] == "variables"
    args = request["arguments"]
    assert args["variablesReference"] == 1001


def test_create_evaluate_request_minimal():
    """Test evaluate request creation without frame ID."""
    factory = ProtocolFactory()

    request = factory.create_evaluate_request("x + y")

    assert request["command"] == "evaluate"
    args = request["arguments"]
    assert args["expression"] == "x + y"
    assert "frameId" not in args


def test_create_evaluate_request_with_frame():
    """Test evaluate request creation with frame ID."""
    factory = ProtocolFactory()

    request = factory.create_evaluate_request("len(items)", 15)

    assert request["command"] == "evaluate"
    args = request["arguments"]
    assert args["expression"] == "len(items)"
    assert args["frameId"] == 15


# ---------------------------------------------------------------------------
# Specialized Event Creator Tests
# ---------------------------------------------------------------------------


def test_create_initialized_event():
    """Test initialized event creation."""
    factory = ProtocolFactory()

    event = factory.create_initialized_event()

    assert event["event"] == "initialized"
    assert "body" not in event


def test_create_stopped_event_minimal():
    """Test stopped event creation without text."""
    factory = ProtocolFactory()

    event = factory.create_stopped_event("breakpoint", 100)

    assert event["event"] == "stopped"
    body = event["body"]
    assert body["reason"] == "breakpoint"
    assert body["threadId"] == 100
    assert body["allThreadsStopped"] is False
    assert "text" not in body


def test_create_stopped_event_with_text():
    """Test stopped event creation with text."""
    factory = ProtocolFactory()

    event = factory.create_stopped_event("exception", 200, "RuntimeError: Something went wrong")

    assert event["event"] == "stopped"
    body = event["body"]
    assert body["reason"] == "exception"
    assert body["threadId"] == 200
    assert body["allThreadsStopped"] is False
    assert body["text"] == "RuntimeError: Something went wrong"


def test_create_exited_event():
    """Test exited event creation."""
    factory = ProtocolFactory()

    event = factory.create_exited_event(1)

    assert event["event"] == "exited"
    body = event["body"]
    assert body["exitCode"] == 1


def test_create_terminated_event_no_restart():
    """Test terminated event creation without restart."""
    factory = ProtocolFactory()

    event = factory.create_terminated_event()

    assert event["event"] == "terminated"
    assert event.get("body") is None


def test_create_terminated_event_with_restart():
    """Test terminated event creation with restart."""
    factory = ProtocolFactory()

    event = factory.create_terminated_event(True)

    assert event["event"] == "terminated"
    body = event["body"]
    assert body["restart"] is True


def test_create_thread_event():
    """Test thread event creation."""
    factory = ProtocolFactory()

    event = factory.create_thread_event("started", 300)

    assert event["event"] == "thread"
    body = event["body"]
    assert body["reason"] == "started"
    assert body["threadId"] == 300


def test_create_output_event_default_category():
    """Test output event creation with default category."""
    factory = ProtocolFactory()

    event = factory.create_output_event("Hello, world!")

    assert event["event"] == "output"
    body = event["body"]
    assert body["output"] == "Hello, world!"
    assert body["category"] == "console"


def test_create_output_event_custom_category():
    """Test output event creation with custom category."""
    factory = ProtocolFactory()

    event = factory.create_output_event("Error occurred", "stderr")

    assert event["event"] == "output"
    body = event["body"]
    assert body["output"] == "Error occurred"
    assert body["category"] == "stderr"


def test_create_breakpoint_event():
    """Test breakpoint event creation."""
    factory = ProtocolFactory()
    bp_info = {"id": 1, "verified": True, "line": 25}

    event = factory.create_breakpoint_event("changed", bp_info)

    assert event["event"] == "breakpoint"
    body = event["body"]
    assert body["reason"] == "changed"
    assert body["breakpoint"] == bp_info


# ---------------------------------------------------------------------------
# ProtocolHandler Delegation Tests
# ---------------------------------------------------------------------------


def test_protocol_handler_factory_delegation():
    """Test that ProtocolHandler properly delegates to its internal factory."""
    handler = ProtocolHandler()

    # Test that all factory methods are available via handler
    request = handler.create_initialize_request("test-client", "test-adapter")
    assert request["command"] == "initialize"

    event = handler.create_exited_event(0)
    assert event["event"] == "exited"


def test_protocol_handler_sequence_independence():
    """Test that multiple handlers have independent sequence counters."""
    handler1 = ProtocolHandler()
    handler2 = ProtocolHandler()

    req1 = handler1.create_request("test1")
    req2 = handler2.create_request("test2")

    # Both should start from seq=1
    assert req1["seq"] == 1
    assert req2["seq"] == 1


# ---------------------------------------------------------------------------
# Error Handling Tests
# ---------------------------------------------------------------------------


def test_parse_message_not_json_object():
    """Test parsing a JSON string that is not an object."""
    handler = ProtocolHandler()

    with pytest.raises(ProtocolError) as exc_info:
        handler.parse_message('"just a string"')

    assert "Message is not a JSON object" in str(exc_info.value)


def test_parse_message_missing_seq():
    """Test parsing a message without seq field."""
    handler = ProtocolHandler()
    message = {"type": "request", "command": "test"}

    with pytest.raises(ProtocolError) as exc_info:
        handler.parse_message(json.dumps(message))

    assert "Message missing 'seq' field" in str(exc_info.value)


def test_parse_message_missing_type():
    """Test parsing a message without type field."""
    handler = ProtocolHandler()
    message = {"seq": 1, "command": "test"}

    with pytest.raises(ProtocolError) as exc_info:
        handler.parse_message(json.dumps(message))

    assert "Message missing 'type' field" in str(exc_info.value)


def test_parse_message_invalid_type():
    """Test parsing a message with invalid type."""
    handler = ProtocolHandler()
    message = {"seq": 1, "type": "invalid"}

    with pytest.raises(ProtocolError) as exc_info:
        handler.parse_message(json.dumps(message))

    assert "Invalid message type: invalid" in str(exc_info.value)


def test_parse_request_missing_command():
    """Test parsing a request without command field."""
    handler = ProtocolHandler()
    message = {"seq": 1, "type": "request"}

    with pytest.raises(ProtocolError) as exc_info:
        handler.parse_message(json.dumps(message))

    assert "Request message missing 'command' field" in str(exc_info.value)


def test_parse_response_missing_required_fields():
    """Test parsing responses missing required fields."""
    handler = ProtocolHandler()

    # Missing request_seq
    message1 = {"seq": 1, "type": "response", "success": True, "command": "test"}
    with pytest.raises(ProtocolError) as exc_info:
        handler.parse_message(json.dumps(message1))
    assert "Response message missing 'request_seq' field" in str(exc_info.value)

    # Missing success
    message2 = {"seq": 1, "type": "response", "request_seq": 0, "command": "test"}
    with pytest.raises(ProtocolError) as exc_info:
        handler.parse_message(json.dumps(message2))
    assert "Response message missing 'success' field" in str(exc_info.value)

    # Missing command
    message3 = {"seq": 1, "type": "response", "request_seq": 0, "success": True}
    with pytest.raises(ProtocolError) as exc_info:
        handler.parse_message(json.dumps(message3))
    assert "Response message missing 'command' field" in str(exc_info.value)


def test_parse_event_missing_event():
    """Test parsing an event without event field."""
    handler = ProtocolHandler()
    message = {"seq": 1, "type": "event"}

    with pytest.raises(ProtocolError) as exc_info:
        handler.parse_message(json.dumps(message))

    assert "Event message missing 'event' field" in str(exc_info.value)
