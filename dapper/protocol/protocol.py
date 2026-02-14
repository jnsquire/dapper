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
from typing import TypeVar
from typing import cast
from typing import overload

if TYPE_CHECKING:
    from dapper.protocol.messages import ErrorResponse
    from dapper.protocol.messages import GenericEvent
    from dapper.protocol.messages import GenericRequest
    from dapper.protocol.messages import GenericResponse
    from dapper.protocol.messages import ProtocolMessage

# Type variables for generic message types
T = TypeVar("T", bound="ProtocolMessage")
RequestT = TypeVar("RequestT", bound="GenericRequest")
ResponseT = TypeVar("ResponseT", bound="GenericResponse")
EventT = TypeVar("EventT", bound="GenericEvent")

logger = logging.getLogger(__name__)


class ProtocolError(Exception):
    """Exception raised for errors in the Debug Adapter Protocol."""


class ProtocolFactory:
    """
    Builds Debug Adapter Protocol messages.

    This class owns the sequencing for created messages and provides helpers
    for constructing requests, responses (including error responses), and
    events, as well as specialized convenience methods.
    """

    def __init__(self, *, seq_start: int = 1) -> None:
        self.seq_counter = seq_start

    # ---- Core constructors -------------------------------------------------

    def _next_seq(self) -> int:
        seq = self.seq_counter
        self.seq_counter += 1
        return seq

    def create_request(
        self, command: str, arguments: dict[str, Any] | None = None
    ) -> GenericRequest:
        request_dict: dict[str, Any] = dict(seq=self._next_seq(), type="request")
        request_dict["command"] = command
        if arguments is not None:
            request_dict["arguments"] = arguments

        return cast("GenericRequest", request_dict)

    def create_response(
        self,
        request: GenericRequest,
        success: bool,
        body: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> GenericResponse:
        # request is a TypedDict; access via plain dict for safety
        req = cast("dict[str, Any]", request)

        response_dict: dict[str, Any] = {
            "seq": self._next_seq(),
            "type": "response",
            "request_seq": req["seq"],
            "success": success,
            "command": req.get("command"),
        }

        if body is not None:
            response_dict["body"] = body

        if not success and error_message is not None:
            response_dict["message"] = error_message

        return cast("GenericResponse", response_dict)

    def create_error_response(self, request: GenericRequest, error_message: str) -> ErrorResponse:
        error_body = {
            "error": "ProtocolError",
            "details": {
                "command": request.get("command"),
            },
        }
        response = self.create_response(request, False, error_body, error_message)
        return cast("ErrorResponse", response)

    def create_event(self, event_type: str, body: dict[str, Any] | None = None) -> GenericEvent:
        event_dict: dict[str, Any] = {
            "seq": self._next_seq(),
            "type": "event",
            "event": event_type,
        }

        if body is not None:
            event_dict["body"] = body

        return cast("GenericEvent", event_dict)

    # ---- Specialized request creators -------------------------------------

    def create_initialize_request(self, client_id: str, adapter_id: str) -> GenericRequest:
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
        return cast("GenericRequest", request)

    def create_launch_request(
        self, program: str, args: list | None = None, no_debug: bool = False
    ) -> GenericRequest:
        launch_args = {"program": program, "noDebug": no_debug}
        if args is not None:
            launch_args["args"] = args
        request = self.create_request("launch", launch_args)
        return cast("GenericRequest", request)

    def create_configuration_done_request(self) -> GenericRequest:
        request = self.create_request("configurationDone")
        return cast("GenericRequest", request)

    def create_set_breakpoints_request(
        self, source: dict[str, Any], breakpoints: list
    ) -> GenericRequest:
        args = {"source": source, "breakpoints": breakpoints}
        request = self.create_request("setBreakpoints", args)
        return cast("GenericRequest", request)

    def create_continue_request(self, thread_id: int) -> GenericRequest:
        args = {"threadId": thread_id}
        request = self.create_request("continue", args)
        return cast("GenericRequest", request)

    def create_threads_request(self) -> GenericRequest:
        request = self.create_request("threads")
        return cast("GenericRequest", request)

    def create_stack_trace_request(
        self, thread_id: int, start_frame: int = 0, levels: int = 20
    ) -> GenericRequest:
        args = {"threadId": thread_id, "startFrame": start_frame, "levels": levels}
        request = self.create_request("stackTrace", args)
        return cast("GenericRequest", request)

    def create_scopes_request(self, frame_id: int) -> GenericRequest:
        args = {"frameId": frame_id}
        request = self.create_request("scopes", args)
        return cast("GenericRequest", request)

    def create_variables_request(self, variables_reference: int) -> GenericRequest:
        args = {"variablesReference": variables_reference}
        request = self.create_request("variables", args)
        return cast("GenericRequest", request)

    def create_evaluate_request(
        self, expression: str, frame_id: int | None = None
    ) -> GenericRequest:
        args = {"expression": expression}
        if frame_id is not None:
            args["frameId"] = cast("Any", frame_id)

        request = self.create_request("evaluate", args)
        return cast("GenericRequest", request)

    # ---- Specialized event creators ---------------------------------------

    def create_initialized_event(self) -> GenericEvent:
        event = self.create_event("initialized")
        return cast("GenericEvent", event)

    def create_stopped_event(
        self, reason: str, thread_id: int, text: str | None = None
    ) -> GenericEvent:
        body = {"reason": reason, "threadId": thread_id, "allThreadsStopped": False}
        if text is not None:
            body["text"] = text
        event = self.create_event("stopped", body)
        return cast("GenericEvent", event)

    def create_exited_event(self, exit_code: int) -> GenericEvent:
        body = {"exitCode": exit_code}
        event = self.create_event("exited", body)
        return cast("GenericEvent", event)

    def create_terminated_event(self, restart: bool = False) -> GenericEvent:
        body: dict[str, Any] = {}
        if restart:
            body["restart"] = True
        event = self.create_event("terminated", body or None)
        return cast("GenericEvent", event)

    def create_thread_event(self, reason: str, thread_id: int) -> GenericEvent:
        body = {"reason": reason, "threadId": thread_id}
        event = self.create_event("thread", body)
        return cast("GenericEvent", event)

    def create_output_event(self, output: str, category: str = "console") -> GenericEvent:
        body = {"output": output, "category": category}
        event = self.create_event("output", body)
        return cast("GenericEvent", event)

    def create_breakpoint_event(
        self, reason: str, breakpoint_info: dict[str, Any]
    ) -> GenericEvent:
        body = {"reason": reason, "breakpoint": breakpoint_info}
        event = self.create_event("breakpoint", body)
        return cast("GenericEvent", event)


class ProtocolHandler:
    """
    Handles parsing and construction of Debug Adapter Protocol messages.
    """

    def __init__(self):
        # Creation responsibilities are moved to ProtocolFactory.
        self._factory = ProtocolFactory(seq_start=1)

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
            raise ProtocolError("Message is not a JSON object")

        if "seq" not in message:
            raise ProtocolError("Message missing 'seq' field")

        if "type" not in message:
            raise ProtocolError("Message missing 'type' field")

        msg_type = message["type"]

        if msg_type == "request":
            return self._validate_request(message)

        if msg_type == "response":
            return self._validate_response(message)

        if msg_type == "event":
            return self._validate_event(message)

        raise ProtocolError(f"Invalid message type: {msg_type}")  # noqa: EM102

    def _validate_request(self, message: dict[str, Any]):
        """Validate and return a request message."""
        if "command" not in message:
            msg = "Request message missing 'command' field"
            raise ProtocolError(msg)

        # We accept unknown commands as well, but keep the known command list
        # for potential future validation.
        return cast("GenericRequest", message)

    def _validate_response(self, message: dict[str, Any]):
        """Validate and return a response message."""
        for key in ("request_seq", "success", "command"):
            if key not in message:
                msg = f"Response message missing '{key}' field"
                raise ProtocolError(msg)

        return cast("GenericResponse", message)

    def _validate_event(self, message: dict[str, Any]):
        """Validate and return an event message."""
        if "event" not in message:
            msg = "Event message missing 'event' field"
            raise ProtocolError(msg)

        return cast("GenericEvent", message)

    @overload
    def create_request(
        self, command: str, arguments: dict[str, Any] | None = None
    ) -> GenericRequest: ...

    @overload
    def create_request(
        self, command: str, arguments: dict[str, Any] | None = None, *, return_type: type[RequestT]
    ) -> RequestT: ...

    def create_request(
        self,
        command: str,
        arguments: dict[str, Any] | None = None,
        *,
        return_type: type[RequestT] | None = None,
    ) -> RequestT | GenericRequest:
        result = self._factory.create_request(command, arguments)
        return cast("RequestT", result) if return_type else result  # type: ignore[return-value]

    @overload
    def create_response(
        self,
        request: GenericRequest,
        success: bool,
        body: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> GenericResponse: ...

    @overload
    def create_response(
        self,
        request: GenericRequest,
        success: bool,
        body: dict[str, Any] | None = None,
        error_message: str | None = None,
        *,
        return_type: type[ResponseT],
    ) -> ResponseT: ...

    def create_response(
        self,
        request: GenericRequest,
        success: bool,
        body: dict[str, Any] | None = None,
        error_message: str | None = None,
        *,
        return_type: type[ResponseT] | None = None,
    ) -> ResponseT | GenericResponse:
        result = self._factory.create_response(request, success, body, error_message)
        return cast("ResponseT", result) if return_type else result  # type: ignore[return-value]

    @overload
    def create_error_response(
        self, request: GenericRequest, error_message: str
    ) -> ErrorResponse: ...

    @overload
    def create_error_response(
        self, request: GenericRequest, error_message: str, *, return_type: type[ResponseT]
    ) -> ResponseT: ...

    def create_error_response(
        self,
        request: GenericRequest,
        error_message: str,
        *,
        return_type: type[ResponseT] | None = None,
    ) -> ResponseT | ErrorResponse:
        result = self._factory.create_error_response(request, error_message)
        return cast("ResponseT", result) if return_type else result  # type: ignore[return-value]

    @overload
    def create_event(
        self, event_type: str, body: dict[str, Any] | None = None
    ) -> GenericEvent: ...

    @overload
    def create_event(
        self, event_type: str, body: dict[str, Any] | None = None, *, return_type: type[EventT]
    ) -> EventT: ...

    def create_event(
        self,
        event_type: str,
        body: dict[str, Any] | None = None,
        *,
        return_type: type[EventT] | None = None,
    ) -> EventT | GenericEvent:
        result = self._factory.create_event(event_type, body)
        return cast("EventT", result) if return_type else result  # type: ignore[return-value]

    # Specific request creation methods

    def create_initialize_request(self, client_id: str, adapter_id: str) -> GenericRequest:
        return self._factory.create_initialize_request(client_id, adapter_id)

    def create_launch_request(
        self, program: str, args: list | None = None, no_debug: bool = False
    ) -> GenericRequest:
        return self._factory.create_launch_request(program, args, no_debug)

    def create_configuration_done_request(self) -> GenericRequest:
        return self._factory.create_configuration_done_request()

    def create_set_breakpoints_request(
        self, source: dict[str, Any], breakpoints: list
    ) -> GenericRequest:
        return self._factory.create_set_breakpoints_request(source, breakpoints)

    def create_continue_request(self, thread_id: int) -> GenericRequest:
        return self._factory.create_continue_request(thread_id)

    def create_threads_request(self) -> GenericRequest:
        return self._factory.create_threads_request()

    def create_stack_trace_request(
        self, thread_id: int, start_frame: int = 0, levels: int = 20
    ) -> GenericRequest:
        return self._factory.create_stack_trace_request(thread_id, start_frame, levels)

    def create_scopes_request(self, frame_id: int) -> GenericRequest:
        return self._factory.create_scopes_request(frame_id)

    def create_variables_request(self, variables_reference: int) -> GenericRequest:
        return self._factory.create_variables_request(variables_reference)

    def create_evaluate_request(
        self, expression: str, frame_id: int | None = None
    ) -> GenericRequest:
        return self._factory.create_evaluate_request(expression, frame_id)

    # Event creation methods

    def create_initialized_event(self) -> GenericEvent:
        return self._factory.create_initialized_event()

    def create_stopped_event(
        self, reason: str, thread_id: int, text: str | None = None
    ) -> GenericEvent:
        return self._factory.create_stopped_event(reason, thread_id, text)

    def create_exited_event(self, exit_code: int) -> GenericEvent:
        return self._factory.create_exited_event(exit_code)

    def create_terminated_event(self, restart: bool = False) -> GenericEvent:
        return self._factory.create_terminated_event(restart)

    def create_thread_event(self, reason: str, thread_id: int) -> GenericEvent:
        return self._factory.create_thread_event(reason, thread_id)

    def create_output_event(self, output: str, category: str = "console") -> GenericEvent:
        return self._factory.create_output_event(output, category)

    def create_breakpoint_event(
        self, reason: str, breakpoint_info: dict[str, Any]
    ) -> GenericEvent:
        return self._factory.create_breakpoint_event(reason, breakpoint_info)
