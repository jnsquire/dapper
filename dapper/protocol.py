"""
Debug Adapter Protocol message parsing and handling.

This module provides classes for working with the Debug Adapter Protocol (DAP)
messages, including parsing, validation, and construction of messages.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

if TYPE_CHECKING:
    from dapper.protocol_types import BreakpointEvent
    from dapper.protocol_types import ConfigurationDoneRequest
    from dapper.protocol_types import ContinueRequest
    from dapper.protocol_types import ErrorResponse
    from dapper.protocol_types import EvaluateRequest
    from dapper.protocol_types import Event
    from dapper.protocol_types import ExitedEvent
    from dapper.protocol_types import InitializedEvent
    from dapper.protocol_types import InitializeRequest
    from dapper.protocol_types import LaunchRequest
    from dapper.protocol_types import OutputEvent
    from dapper.protocol_types import Request
    from dapper.protocol_types import Response
    from dapper.protocol_types import ScopesRequest
    from dapper.protocol_types import SetBreakpointsRequest
    from dapper.protocol_types import StackTraceRequest
    from dapper.protocol_types import StoppedEvent
    from dapper.protocol_types import TerminatedEvent
    from dapper.protocol_types import ThreadEvent
    from dapper.protocol_types import ThreadsRequest
    from dapper.protocol_types import VariablesRequest

logger = logging.getLogger(__name__)


class ProtocolError(Exception):
    """Exception raised for errors in the Debug Adapter Protocol."""


class ProtocolHandler:
    """
    Handles parsing and construction of Debug Adapter Protocol messages.
    """

    def __init__(self):
        self.seq_counter = 1

    def parse_message(self, message_json: str):
        # -> Union[Request, Response, Event]:
        """
        Parse a JSON message into a protocol message object.

        Args:
            message_json: JSON string containing the protocol message

        Returns:
            A parsed protocol message as a TypedDict

        Raises:
            ProtocolError: If the message is invalid or cannot be parsed
        """

        try:
            message = json.loads(message_json)
        except json.JSONDecodeError as e:
            msg = f"Failed to parse message as JSON: {e}"
            raise ProtocolError(msg) from e
        except Exception as e:
            msg = f"Error parsing message: {e}"
            raise ProtocolError(msg) from e

        if not isinstance(message, dict):
            raise ProtocolError("Message is not a JSON object")  # noqa: EM101, TRY003

        if "seq" not in message:
            raise ProtocolError("Message missing 'seq' field")  # noqa: EM101, TRY003

        if "type" not in message:
            raise ProtocolError("Message missing 'type' field")  # noqa: EM101, TRY003

        msg_type = message["type"]

        if msg_type == "request":
            return self._validate_request(message)

        if msg_type == "response":
            return self._validate_response(message)

        if msg_type == "event":
            return self._validate_event(message)

        raise ProtocolError(f"Invalid message type: {msg_type}")  # noqa: EM102, TRY003

    def _validate_request(self, message: dict[str, Any]):
        """Validate and return a request message."""
        if "command" not in message:
            msg = "Request message missing 'command' field"
            raise ProtocolError(msg)

        # We accept unknown commands as well, but keep the known command list
        # for potential future validation.
        return cast("Request", message)

    def _validate_response(self, message: dict[str, Any]):
        """Validate and return a response message."""
        for key in ("request_seq", "success", "command"):
            if key not in message:
                msg = f"Response message missing '{key}' field"
                raise ProtocolError(msg)

        return cast("Response", message)

    def _validate_event(self, message: dict[str, Any]):
        """Validate and return an event message."""
        if "event" not in message:
            msg = "Event message missing 'event' field"
            raise ProtocolError(msg)

        return cast("Event", message)

    def create_request(self, command: str, arguments: dict[str, Any] | None = None) -> Request:
        """
        Create a new request message.

        Args:
            command: The command to execute
            arguments: Optional arguments for the command

        Returns:
            A Request TypedDict
        """

        request_dict: dict[str, Any] = dict(seq=self.seq_counter, type="request")
        request_dict["command"] = command
        if arguments is not None:
            request_dict["arguments"] = arguments

        self.seq_counter += 1
        return cast("Request", request_dict)

    def create_response(
        self,
        request: Request,
        success: bool,
        body: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> Response:
        """
        Create a response message for a request.

        Args:
            request: The request to respond to
            success: Whether the request was successful
            body: Optional body with the response payload
            error_message: Optional error message if success is False

        Returns:
            A Response TypedDict
        """
        # request is typed as a TypedDict that may not declare 'command',
        # so access it via a cast to a plain dict to satisfy the type
        # checker before building the response dict.
        req = cast("dict[str, Any]", request)

        response_dict: dict[str, Any] = {
            "seq": self.seq_counter,
            "type": "response",
            "request_seq": req["seq"],
            "success": success,
            "command": req.get("command"),
        }

        if body is not None:
            response_dict["body"] = body

        if not success and error_message is not None:
            response_dict["message"] = error_message

        self.seq_counter += 1
        return cast("Response", response_dict)

    def create_error_response(self, request: Request, error_message: str) -> ErrorResponse:
        """
        Create an error response message.

        Args:
            request: The request that failed
            error_message: Error message explaining the failure

        Returns:
            An ErrorResponse TypedDict
        """
        error_body = {
            "error": {
                "id": 1,  # Generic error ID
                "format": error_message,
                "showUser": True,
            }
        }
        response = self.create_response(request, False, error_body, error_message)
        return cast("ErrorResponse", response)

    def create_event(self, event_type: str, body: dict[str, Any] | None = None) -> Event:
        """
        Create a new event message.

        Args:
            event_type: Type of the event
            body: Optional body with event-specific information

        Returns:
            An Event TypedDict
        """
        event_dict: dict[str, Any] = {
            "seq": self.seq_counter,
            "type": "event",
            "event": event_type,
        }

        if body is not None:
            event_dict["body"] = body

        self.seq_counter += 1
        return cast("Event", event_dict)

    # Specific request creation methods

    def create_initialize_request(self, client_id: str, adapter_id: str) -> InitializeRequest:
        """Create an initialize request."""
        args = {
            "clientID": client_id,
            "adapterID": adapter_id,
            "linesStartAt1": True,
            "columnsStartAt1": True,
            "supportsVariableType": True,
            "supportsVariablePaging": True,
            "supportsRunInTerminalRequest": False,
        }
        request = self.create_request("initialize", args)
        return cast("InitializeRequest", request)

    def create_launch_request(
        self, program: str, args: list | None = None, no_debug: bool = False
    ) -> LaunchRequest:
        """Create a launch request."""
        launch_args = {"program": program, "noDebug": no_debug}
        if args is not None:
            launch_args["args"] = args

        request = self.create_request("launch", launch_args)
        return cast("LaunchRequest", request)

    def create_configuration_done_request(self) -> ConfigurationDoneRequest:
        """Create a configurationDone request."""
        request = self.create_request("configurationDone")
        return cast("ConfigurationDoneRequest", request)

    def create_set_breakpoints_request(
        self, source: dict[str, Any], breakpoints: list
    ) -> SetBreakpointsRequest:
        """Create a setBreakpoints request."""
        args = {"source": source, "breakpoints": breakpoints}
        request = self.create_request("setBreakpoints", args)
        return cast("SetBreakpointsRequest", request)

    def create_continue_request(self, thread_id: int) -> ContinueRequest:
        """Create a continue request."""
        args = {"threadId": thread_id}
        request = self.create_request("continue", args)
        return cast("ContinueRequest", request)

    def create_threads_request(self) -> ThreadsRequest:
        """Create a threads request."""
        request = self.create_request("threads")
        return cast("ThreadsRequest", request)

    def create_stack_trace_request(
        self, thread_id: int, start_frame: int = 0, levels: int = 20
    ) -> StackTraceRequest:
        """Create a stackTrace request."""
        args = {
            "threadId": thread_id,
            "startFrame": start_frame,
            "levels": levels,
        }
        request = self.create_request("stackTrace", args)
        return cast("StackTraceRequest", request)

    def create_scopes_request(self, frame_id: int) -> ScopesRequest:
        """Create a scopes request."""
        args = {"frameId": frame_id}
        request = self.create_request("scopes", args)
        return cast("ScopesRequest", request)

    def create_variables_request(self, variables_reference: int) -> VariablesRequest:
        """Create a variables request."""
        args = {"variablesReference": variables_reference}
        request = self.create_request("variables", args)
        return cast("VariablesRequest", request)

    def create_evaluate_request(
        self, expression: str, frame_id: int | None = None
    ) -> EvaluateRequest:
        """Create an evaluate request."""
        args = {"expression": expression}
        if frame_id is not None:
            args["frameId"] = cast("Any", frame_id)

        request = self.create_request("evaluate", args)
        return cast("EvaluateRequest", request)

    # Event creation methods

    def create_initialized_event(self) -> InitializedEvent:
        """Create an initialized event."""
        event = self.create_event("initialized")
        return cast("InitializedEvent", event)

    def create_stopped_event(
        self, reason: str, thread_id: int, text: str | None = None
    ) -> StoppedEvent:
        """Create a stopped event."""
        body = {
            "reason": reason,
            "threadId": thread_id,
            "allThreadsStopped": False,
        }
        if text is not None:
            body["text"] = text

        event = self.create_event("stopped", body)
        return cast("StoppedEvent", event)

    def create_exited_event(self, exit_code: int) -> ExitedEvent:
        """Create an exited event."""
        body = {"exitCode": exit_code}
        event = self.create_event("exited", body)
        return cast("ExitedEvent", event)

    def create_terminated_event(self, restart: bool = False) -> TerminatedEvent:
        """Create a terminated event."""
        body = {}
        if restart:
            body["restart"] = True

        event = self.create_event("terminated", body if body else None)
        return cast("TerminatedEvent", event)

    def create_thread_event(self, reason: str, thread_id: int) -> ThreadEvent:
        """Create a thread event."""
        body = {"reason": reason, "threadId": thread_id}
        event = self.create_event("thread", body)
        return cast("ThreadEvent", event)

    def create_output_event(self, output: str, category: str = "console") -> OutputEvent:
        """Create an output event."""
        body = {"output": output, "category": category}
        event = self.create_event("output", body)
        return cast("OutputEvent", event)

    def create_breakpoint_event(
        self, reason: str, breakpoint_info: dict[str, Any]
    ) -> BreakpointEvent:
        """Create a breakpoint event."""
        body = {"reason": reason, "breakpoint": breakpoint_info}
        event = self.create_event("breakpoint", body)
        return cast("BreakpointEvent", event)
