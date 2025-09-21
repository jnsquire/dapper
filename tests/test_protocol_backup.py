"""
Tests for the Debug Adapter Protocol message classes
"""

import json
import unittest

import pytest

from dapper.protocol import ProtocolError
from dapper.protocol import ProtocolHandler
from dapper.protocol_types import ProtocolMessage


class TestProtocolMessages(unittest.TestCase):
    """Test cases for the DAP message classes"""

    def setUp(self):
        """Set up test fixtures"""
        self.handler = ProtocolHandler()

    def test_protocol_message_base(self):
        """Test the base ProtocolMessage class"""
        msg = ProtocolMessage(seq=123)
        assert msg["seq"] == 123

        # Test conversion to dict
        msg_dict = msg
        assert msg_dict["seq"] == 123

    def test_request_message(self):
        """Test the Request message class"""
        args = {"program": "test.py", "stopOnEntry": True}
        req = self.handler.create_request("launch", args)

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

    def test_response_message(self):
        """Test the Response message class"""
        body = {"breakpoints": [{"verified": True, "line": 10}]}
        request = self.handler.create_request("setBreakpoints")
        resp = self.handler.create_response(request, True, body)

        # Test attributes
        assert resp["seq"] == 2
        assert resp["request_seq"] == 1
        assert resp["success"]
        assert resp["command"] == "setBreakpoints"
        assert "body" in resp
        assert resp.get("body") == body

        # Test conversion to dict
        resp_dict = resp
        assert resp_dict["seq"] == 2
        assert resp_dict["type"] == "response"
        assert resp_dict["request_seq"] == 1
        assert resp_dict["success"]
        assert resp_dict["command"] == "setBreakpoints"
        assert "body" in resp_dict
        assert resp_dict.get("body") == body

        # Test error response
        err_resp = self.handler.create_response(request, False, None, "Invalid expression")

        err_dict = err_resp
        assert err_dict["seq"] == 3
        assert not err_dict["success"]
        assert "message" in err_dict
        assert err_dict.get("message") == "Invalid expression"

    def test_event_message(self):
        """Test the Event message class"""
        body = {"reason": "breakpoint", "threadId": 1}
        event = self.handler.create_event("stopped", body)

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

    def test_json_serialization(self):
        """Test that all messages can be properly serialized to JSON"""
        messages = [
            {"seq": 1, "type": "request"},  # ProtocolMessage base
            self.handler.create_request("launch", {"program": "test.py"}),
            self.handler.create_response(self.handler.create_request("launch"), True),
            self.handler.create_event("stopped", {"reason": "breakpoint"}),
        ]

        for msg in messages:
            # Convert to dict then JSON string
            msg_dict = msg
            json_str = json.dumps(msg_dict)

            # Parse back from JSON
            parsed_dict = json.loads(json_str)

            # Verify the structure is preserved
            assert parsed_dict == msg_dict

    def test_parse_message_valid_request(self):
        """Test parsing a valid request message"""
        json_msg = {
            "seq": 1,
            "type": "request",
            "command": "launch",
            "arguments": {"program": "test.py"},
        }
        json_str = json.dumps(json_msg)

        parsed = self.handler.parse_message(json_str)
        assert parsed["seq"] == 1
        assert parsed["type"] == "request"
        assert parsed["command"] == "launch"
        assert parsed["arguments"] == {"program": "test.py"}

    def test_parse_message_valid_response(self):
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

        parsed = self.handler.parse_message(json_str)
        assert parsed["seq"] == 2
        assert parsed["type"] == "response"
        assert parsed["request_seq"] == 1
        assert parsed["success"]
        assert parsed["command"] == "launch"
        assert parsed["body"] == {"threadId": 1}

    def test_parse_message_valid_event(self):
        """Test parsing a valid event message"""
        json_msg = {
            "seq": 3,
            "type": "event",
            "event": "stopped",
            "body": {"reason": "breakpoint", "threadId": 1},
        }
        json_str = json.dumps(json_msg)

        parsed = self.handler.parse_message(json_str)
        assert parsed["seq"] == 3
        assert parsed["type"] == "event"
        assert parsed["event"] == "stopped"
        assert parsed["body"] == {"reason": "breakpoint", "threadId": 1}

    def test_parse_message_invalid_json(self):
        """Test parsing invalid JSON raises ProtocolError"""
        invalid_json = "{invalid json"

        with pytest.raises(ProtocolError) as cm:
            self.handler.parse_message(invalid_json)

        assert "Failed to parse message as JSON" in str(cm.value)

    def test_parse_message_missing_type(self):
        """Test parsing message without type field"""
        json_msg = {"seq": 1, "command": "launch"}
        json_str = json.dumps(json_msg)

        with pytest.raises(ProtocolError) as cm:
            self.handler.parse_message(json_str)

        assert "Message missing 'type' field" in str(cm.value)

    def test_parse_message_unknown_type(self):
        """Test parsing message with unknown type"""
        json_msg = {"seq": 1, "type": "unknown"}
        json_str = json.dumps(json_msg)

        with pytest.raises(ProtocolError) as cm:
            self.handler.parse_message(json_str)

        assert "Invalid message type: unknown" in str(cm.value)

    def test_create_error_response(self):
        """Test creating error response"""
        request = self.handler.create_request("launch")
        error_resp = self.handler.create_error_response(request, "Launch failed")

        assert error_resp["seq"] == 2
        assert error_resp["type"] == "response"
        assert error_resp["request_seq"] == 1
        assert not error_resp["success"]
        assert error_resp["command"] == "launch"
        assert "message" in error_resp
        assert error_resp["message"] == "Launch failed"
        assert "body" in error_resp
        assert "error" in error_resp["body"]
        assert error_resp["body"]["error"]["format"] == "Launch failed"

    def test_create_initialize_request(self):
        """Test creating initialize request"""
        req = self.handler.create_initialize_request("vscode", "python")

        assert req["seq"] == 1
        assert req["type"] == "request"
        assert req["command"] == "initialize"
        assert "arguments" in req

        args = req["arguments"]
        assert args.get("clientID") == "vscode"
        assert args.get("adapterID") == "python"
        assert args.get("linesStartAt1") is True
        assert args.get("columnsStartAt1") is True
        assert args.get("supportsVariableType") is True
        assert args.get("supportsVariablePaging") is True
        assert args.get("supportsRunInTerminalRequest", False) is False

    def test_create_launch_request(self):
        """Test creating launch request"""
        req = self.handler.create_launch_request("test.py", ["arg1", "arg2"], True)

        assert req["seq"] == 1
        assert req["type"] == "request"
        assert req["command"] == "launch"
        assert "arguments" in req
        args = req["arguments"]
        assert args["program"] == "test.py"
        assert args["args"] == ["arg1", "arg2"]
        assert args["noDebug"]

    def test_create_launch_request_no_args(self):
        """Test creating launch request without args"""
        req = self.handler.create_launch_request("test.py")

        assert req["seq"] == 1
        assert req["type"] == "request"
        assert req["command"] == "launch"
        assert "arguments" in req
        args = req["arguments"]
        assert args["program"] == "test.py"
        assert not args["noDebug"]
        assert "args" not in args

    def test_create_configuration_done_request(self):
        """Test creating configurationDone request"""
        req = self.handler.create_configuration_done_request()

        assert req["seq"] == 1
        assert req["type"] == "request"
        assert req["command"] == "configurationDone"
        assert "arguments" not in req

    def test_create_set_breakpoints_request(self):
        """Test creating setBreakpoints request"""
        source = {"path": "test.py"}
        breakpoints = [{"line": 10}, {"line": 20}]
        req = self.handler.create_set_breakpoints_request(source, breakpoints)

        assert req["seq"] == 1
        assert req["type"] == "request"
        assert req["command"] == "setBreakpoints"
        assert "arguments" in req
        args = req["arguments"]
        assert args["source"] == source
        assert args["breakpoints"] == breakpoints

    def test_create_continue_request(self):
        """Test creating continue request"""
        req = self.handler.create_continue_request(1)

        assert req["seq"] == 1
        assert req["type"] == "request"
        assert req["command"] == "continue"
        assert "arguments" in req
        args = req["arguments"]
        assert args["threadId"] == 1

    def test_create_threads_request(self):
        """Test creating threads request"""
        req = self.handler.create_threads_request()

        assert req["seq"] == 1
        assert req["type"] == "request"
        assert req["command"] == "threads"
        assert "arguments" not in req

    def test_create_stack_trace_request(self):
        """Test creating stackTrace request"""
        req = self.handler.create_stack_trace_request(1, 5, 10)

        assert req["seq"] == 1
        assert req["type"] == "request"
        assert req["command"] == "stackTrace"
        assert "arguments" in req
        args = req["arguments"]
        assert args["threadId"] == 1
        assert args.get("startFrame") == 5
        assert args.get("levels") == 10

    def test_create_scopes_request(self):
        """Test creating scopes request"""
        req = self.handler.create_scopes_request(1)

        assert req["seq"] == 1
        assert req["type"] == "request"
        assert req["command"] == "scopes"
        assert "arguments" in req
        args = req["arguments"]
        assert args["frameId"] == 1

    def test_create_variables_request(self):
        """Test creating variables request"""
        req = self.handler.create_variables_request(100)

        assert req["seq"] == 1
        assert req["type"] == "request"
        assert req["command"] == "variables"
        assert "arguments" in req
        args = req["arguments"]
        assert args["variablesReference"] == 100

    def test_create_evaluate_request(self):
        """Test creating evaluate request"""
        req = self.handler.create_evaluate_request("x + 1", 1)

        assert req["seq"] == 1
        assert req["type"] == "request"
        assert req["command"] == "evaluate"
        assert "arguments" in req
        args = req["arguments"]
        assert args["expression"] == "x + 1"
        assert args.get("frameId") == 1

    def test_create_evaluate_request_no_frame(self):
        """Test creating evaluate request without frameId"""
        req = self.handler.create_evaluate_request("x + 1")

        assert req["seq"] == 1
        assert req["type"] == "request"
        assert req["command"] == "evaluate"
        assert "arguments" in req
        args = req["arguments"]
        assert args["expression"] == "x + 1"
        assert "frameId" not in args

    def test_create_initialized_event(self):
        """Test creating initialized event"""
        event = self.handler.create_initialized_event()

        assert event["seq"] == 1
        assert event["type"] == "event"
        assert event["event"] == "initialized"
        assert "body" not in event

    def test_create_stopped_event(self):
        """Test creating stopped event"""
        event = self.handler.create_stopped_event("breakpoint", 1, "Hit breakpoint")

        assert event["seq"] == 1
        assert event["type"] == "event"
        assert event["event"] == "stopped"
        assert "body" in event
        body = event["body"]
        assert body.get("reason") == "breakpoint"
        assert body.get("threadId") == 1
        assert body.get("text") == "Hit breakpoint"
        assert not body.get("allThreadsStopped")

    def test_create_stopped_event_no_text(self):
        """Test creating stopped event without text"""
        event = self.handler.create_stopped_event("step", 2)

        assert event["seq"] == 1
        assert event["type"] == "event"
        assert event["event"] == "stopped"
        assert "body" in event
        body = event["body"]
        assert body.get("reason") == "step"
        assert body.get("threadId") == 2
        assert "text" not in body

    def test_create_exited_event(self):
        """Test creating exited event"""
        event = self.handler.create_exited_event(0)

        assert event["seq"] == 1
        assert event["type"] == "event"
        assert event["event"] == "exited"
        assert "body" in event
        body = event["body"]
        assert body["exitCode"] == 0

    def test_create_terminated_event(self):
        """Test creating terminated event"""
        event = self.handler.create_terminated_event(True)

        assert event["seq"] == 1
        assert event["type"] == "event"
        assert event["event"] == "terminated"
        assert "body" in event
        body = event["body"]
        assert body.get("restart")

    def test_create_terminated_event_no_restart(self):
        """Test creating terminated event without restart"""
        event = self.handler.create_terminated_event()

        assert event["seq"] == 1
        assert event["type"] == "event"
        assert event["event"] == "terminated"
        assert "body" not in event

    def test_create_thread_event(self):
        """Test creating thread event"""
        event = self.handler.create_thread_event("started", 1)

        assert event["seq"] == 1
        assert event["type"] == "event"
        assert event["event"] == "thread"
        assert "body" in event
        body = event["body"]
        assert body["reason"] == "started"
        assert body["threadId"] == 1

    def test_create_output_event(self):
        """Test creating output event"""
        event = self.handler.create_output_event("Hello World", "stdout")

        assert event["seq"] == 1
        assert event["type"] == "event"
        assert event["event"] == "output"
        assert "body" in event
        body = event["body"]
        assert body.get("output") == "Hello World"
        assert body.get("category") == "stdout"

    def test_create_output_event_default_category(self):
        """Test creating output event with default category"""
        event = self.handler.create_output_event("Debug message")

        assert event["seq"] == 1
        assert event["type"] == "event"
        assert event["event"] == "output"
        assert "body" in event
        body = event["body"]
        assert body.get("output") == "Debug message"
        assert body.get("category") == "console"

    def test_create_breakpoint_event(self):
        """Test creating breakpoint event"""
        breakpoint_info = {"id": 1, "verified": True, "line": 10}
        event = self.handler.create_breakpoint_event("new", breakpoint_info)

        assert event["seq"] == 1
        assert event["type"] == "event"
        assert event["event"] == "breakpoint"
        assert "body" in event
        body = event["body"]
        assert body["reason"] == "new"
        assert body["breakpoint"] == breakpoint_info

    def test_sequence_counter_increment(self):
        """Test that sequence counter increments properly"""
        req1 = self.handler.create_request("launch")
        assert req1["seq"] == 1

        req2 = self.handler.create_request("continue")
        assert req2["seq"] == 2

        resp = self.handler.create_response(req1, True)
        assert resp["seq"] == 3

        event = self.handler.create_event("stopped")
        assert event["seq"] == 4


if __name__ == "__main__":
    unittest.main()
