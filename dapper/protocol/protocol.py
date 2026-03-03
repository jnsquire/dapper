"""Debug Adapter Protocol message parsing and handling.

This module provides classes for working with the Debug Adapter Protocol (DAP)
messages, including parsing, validation, and construction of messages.
"""

from __future__ import annotations

import itertools
import json
import logging
import threading
from typing import TYPE_CHECKING
from typing import Any
from typing import Protocol
from typing import TypeVar
from typing import cast
from typing import overload

from dapper.protocol.messages import ErrorResponse
from dapper.protocol.messages import GenericEvent

# runtime imports for use in return_type arguments and casts
from dapper.protocol.messages import GenericRequest
from dapper.protocol.messages import GenericResponse
from dapper.protocol.requests import BreakpointEvent
from dapper.protocol.requests import ConfigurationDoneRequest
from dapper.protocol.requests import ContinueRequest
from dapper.protocol.requests import EvaluateRequest
from dapper.protocol.requests import ExitedEvent

# event TypedDicts used by convenience event helpers
from dapper.protocol.requests import InitializedEvent

# specific request/response TypedDicts used by convenience helpers and tests
from dapper.protocol.requests import InitializeRequest
from dapper.protocol.requests import LaunchRequest
from dapper.protocol.requests import NextRequest
from dapper.protocol.requests import OutputEvent
from dapper.protocol.requests import ScopesRequest
from dapper.protocol.requests import SetBreakpointsRequest
from dapper.protocol.requests import StackTraceRequest
from dapper.protocol.requests import StepInRequest
from dapper.protocol.requests import StepOutRequest
from dapper.protocol.requests import StoppedEvent
from dapper.protocol.requests import TerminatedEvent
from dapper.protocol.requests import ThreadEvent
from dapper.protocol.requests import ThreadsRequest
from dapper.protocol.requests import VariablesRequest

if TYPE_CHECKING:
    # ProtocolMessage is only needed for typing, not used at runtime
    from dapper.protocol.messages import ProtocolMessage

# Type variables for generic message types
T = TypeVar("T", bound="ProtocolMessage")

# ``RequestT``/``ResponseT``/``EventT`` are only used for the return type of
# the factory helpers; they stay unbounded so callers can use any concrete
# TypedDict (including our ``*Request``/``*Response`` types) without hitting
# variance problems.
RequestT = TypeVar("RequestT")
ResponseT = TypeVar("ResponseT")
EventT = TypeVar("EventT")


# A minimal structural view of a request-like object.  The factory only
# indexes into it; no actual attributes are required.  By restricting the
# protocol to the mapping methods we allow any TypedDict (e.g. ``LaunchRequest``)
# to be treated as a ``RequestLike`` without casting.
class RequestLike(Protocol):
    # TypedDict and dict define ``__getitem__`` with a position-only key
    # parameter, so the protocol must match that exactly or subclasses will
    # not satisfy it.  Using ``/__`` syntax forces the argument to be
    # position-only.
    def __getitem__(self, __key: str, /) -> Any: ...

    # ``get`` is intentionally omitted; callers should either index or
    # handle missing keys themselves.  This avoids painful signature
    # mismatches with TypedDict's implementation.

logger = logging.getLogger(__name__)


class ProtocolError(Exception):
    """Exception raised for errors in the Debug Adapter Protocol."""


class ProtocolFactory:
    """Builds Debug Adapter Protocol messages.

    This class owns the sequencing for created messages and provides helpers
    for constructing requests, responses (including error responses), and
    events, as well as specialized convenience methods.
    """

    def __init__(self, *, seq_start: int = 1) -> None:
        self._seq_counter = itertools.count(seq_start)
        self._seq_lock = threading.Lock()

    # ---- Core constructors -------------------------------------------------

    def _next_seq(self) -> int:
        with self._seq_lock:
            return next(self._seq_counter)

    # Simplified constructor; callers should always provide a return_type
    # when they care about the concrete envelope type.  ``GenericRequest`` is
    # used as the default for backwards compatibility, but there is no
    # separate overload because the return-type type variable is unbounded
    # and therefore accepts any ``TypedDict``.
    def create_request(
        self,
        command: str,
        arguments: dict[str, Any] | None = None,
        *,
        return_type: type[RequestT] = GenericRequest,  # noqa: ARG002
    ) -> RequestT:
        request_dict: dict[str, Any] = dict(seq=self._next_seq(), type="request")
        request_dict["command"] = command
        if arguments is not None:
            request_dict["arguments"] = arguments
        result = cast("GenericRequest", request_dict)
        # ``return_type`` defaults to GenericRequest so this cast always works
        return cast("RequestT", result)

    # the request parameter is only used as a plain dictionary (we pull
    # `seq` and `command` out of it).  callers often have a more specific
    # TypedDict such as ``LaunchRequest`` which is **not** compatible with
    # ``GenericRequest`` from the type-checker's perspective, so loosen the
    # input type to avoid errors.
    @overload
    def create_response(
        self,
        request: RequestLike,
        success: bool,
        body: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> GenericResponse: ...

    @overload
    def create_response(
        self,
        request: RequestLike,
        success: bool,
        body: dict[str, Any] | None = None,
        error_message: str | None = None,
        *,
        return_type: type[ResponseT],
    ) -> ResponseT: ...

    def create_response(
        self,
        request: RequestLike,
        success: bool,
        body: dict[str, Any] | None = None,
        error_message: str | None = None,
        *,
        return_type: type[ResponseT] | None = None,
    ) -> ResponseT | GenericResponse:
        # construct basic response envelope.  ``req`` may not support
        # ``get`` (see RequestLike protocol) so look up ``command`` manually.
        # ``RequestLike`` may not support membership tests, so fetch
        # ``command`` with exception handling instead of ``in``.
        try:
            cmd = request["command"]
        except Exception:
            cmd = None

        response_dict: dict[str, Any] = {
            "seq": self._next_seq(),
            "type": "response",
            "request_seq": request["seq"],
            "success": success,
            "command": cmd,
        }

        if body is not None:
            response_dict["body"] = body

        if not success and error_message is not None:
            response_dict["message"] = error_message

        result = cast("GenericResponse", response_dict)
        return cast("ResponseT", result) if return_type else result

    @overload
    def create_error_response(
        self,
        request: RequestLike,
        error_message: str,
    ) -> ErrorResponse: ...

    @overload
    def create_error_response(
        self,
        request: RequestLike,
        error_message: str,
        *,
        return_type: type[ResponseT],
    ) -> ResponseT: ...

    def create_error_response(
        self,
        request: RequestLike,
        error_message: str,
        *,
        return_type: type[ResponseT] | None = None,
    ) -> ResponseT | ErrorResponse:
        # ``request`` may be any mapping; it may not support ``get`` so
        # index manually with a fallback of ``None``.
        # same defensive lookup for ``command`` as above
        try:
            cmd = request["command"]
        except Exception:
            cmd = None
        error_body = {
            "error": "ProtocolError",
            "details": {
                "command": cmd,
            },
        }
        # forward return_type through to create_response so callers can
        # request a more specific Response subtype if they have one.
        # mypy complains because each method has its own TypeVar instance
        # (`ResponseT` is bound separately in both signatures), so the
        # types are technically incompatible even though they line up at
        # runtime.  Ignore the error here.
        result = self.create_response(
            request,
            False,
            error_body,
            error_message,
            return_type=return_type,  # type: ignore[arg-type]
        )
        return cast("ResponseT", result) if return_type else cast("ErrorResponse", result)

    @overload
    def create_event(
        self,
        event_type: str,
        body: dict[str, Any] | None = None,
    ) -> GenericEvent: ...

    @overload
    def create_event(
        self,
        event_type: str,
        body: dict[str, Any] | None = None,
        *,
        return_type: type[EventT],
    ) -> EventT: ...

    def create_event(
        self,
        event_type: str,
        body: dict[str, Any] | None = None,
        *,
        return_type: type[EventT] | None = None,
    ) -> EventT | GenericEvent:
        event_dict: dict[str, Any] = {
            "seq": self._next_seq(),
            "type": "event",
            "event": event_type,
        }

        if body is not None:
            event_dict["body"] = body

        result = cast("GenericEvent", event_dict)
        return cast("EventT", result) if return_type else result

    # ---- Specialized request creators -------------------------------------

    def create_initialize_request(self, client_id: str, adapter_id: str) -> InitializeRequest:
        args = {
            "clientID": client_id,
            "adapterID": adapter_id,
            "linesStartAt1": True,
            "columnsStartAt1": True,
            "supportsVariableType": True,
            "supportsVariablePaging": True,
            "supportsRunInTerminalRequest": False,
        }
        return self.create_request("initialize", args, return_type=InitializeRequest)

    def create_launch_request(
        self,
        program: str,
        args: list | None = None,
        no_debug: bool = False,
    ) -> LaunchRequest:
        launch_args = {"program": program, "noDebug": no_debug}
        if args is not None:
            launch_args["args"] = args
        return self.create_request("launch", launch_args, return_type=LaunchRequest)

    def create_configuration_done_request(self) -> ConfigurationDoneRequest:
        return self.create_request("configurationDone", return_type=ConfigurationDoneRequest)

    def create_set_breakpoints_request(
        self,
        source: dict[str, Any],
        breakpoints: list,
    ) -> SetBreakpointsRequest:
        args = {"source": source, "breakpoints": breakpoints}
        return self.create_request("setBreakpoints", args, return_type=SetBreakpointsRequest)

    def create_continue_request(self, thread_id: int) -> ContinueRequest:
        args = {"threadId": thread_id}
        return self.create_request("continue", args, return_type=ContinueRequest)

    def create_next_request(self, thread_id: int, granularity: str = "line") -> NextRequest:
        """Create a DAP ``next`` (step-over) request.

        Args:
            thread_id: The thread to step.
            granularity: DAP stepGranularity — ``"line"``, ``"statement"``, or
                ``"instruction"`` (default ``"line"``).

        """
        args: dict[str, Any] = {"threadId": thread_id}
        if granularity != "line":
            args["granularity"] = granularity
        return self.create_request("next", args, return_type=NextRequest)

    def create_step_in_request(
        self,
        thread_id: int,
        target_id: int | None = None,
        granularity: str = "line",
    ) -> StepInRequest:
        """Create a DAP ``stepIn`` request.

        Args:
            thread_id: The thread to step into.
            target_id: Optional step-in target from ``stepInTargets``.
            granularity: DAP stepGranularity (default ``"line"``).

        """
        args: dict[str, Any] = {"threadId": thread_id}
        if target_id is not None:
            args["targetId"] = target_id
        if granularity != "line":
            args["granularity"] = granularity
        return self.create_request("stepIn", args, return_type=StepInRequest)

    def create_step_out_request(self, thread_id: int, granularity: str = "line") -> StepOutRequest:
        """Create a DAP ``stepOut`` request.

        Args:
            thread_id: The thread to step out from.
            granularity: DAP stepGranularity (default ``"line"``).

        """
        args: dict[str, Any] = {"threadId": thread_id}
        if granularity != "line":
            args["granularity"] = granularity
        return self.create_request("stepOut", args, return_type=StepOutRequest)

    def create_threads_request(self) -> ThreadsRequest:
        return self.create_request("threads", return_type=ThreadsRequest)

    def create_stack_trace_request(
        self,
        thread_id: int,
        start_frame: int = 0,
        levels: int = 20,
    ) -> StackTraceRequest:
        args = {"threadId": thread_id, "startFrame": start_frame, "levels": levels}
        return self.create_request("stackTrace", args, return_type=StackTraceRequest)

    def create_scopes_request(self, frame_id: int) -> ScopesRequest:
        args = {"frameId": frame_id}
        return self.create_request("scopes", args, return_type=ScopesRequest)

    def create_variables_request(self, variables_reference: int) -> VariablesRequest:
        args = {"variablesReference": variables_reference}
        return self.create_request("variables", args, return_type=VariablesRequest)

    def create_evaluate_request(
        self,
        expression: str,
        frame_id: int | None = None,
    ) -> EvaluateRequest:
        args = {"expression": expression}
        if frame_id is not None:
            args["frameId"] = cast("Any", frame_id)

        return self.create_request("evaluate", args, return_type=EvaluateRequest)

    # ---- Specialized event creators ---------------------------------------

    def create_initialized_event(self) -> InitializedEvent:
        return self.create_event("initialized", return_type=InitializedEvent)

    def create_stopped_event(
        self,
        reason: str,
        thread_id: int,
        text: str | None = None,
    ) -> StoppedEvent:
        body = {"reason": reason, "threadId": thread_id, "allThreadsStopped": False}
        if text is not None:
            body["text"] = text
        return self.create_event("stopped", body, return_type=StoppedEvent)

    def create_exited_event(self, exit_code: int) -> ExitedEvent:
        body = {"exitCode": exit_code}
        return self.create_event("exited", body, return_type=ExitedEvent)

    def create_terminated_event(self, restart: bool = False) -> TerminatedEvent:
        body: dict[str, Any] = {}
        if restart:
            body["restart"] = True
        return self.create_event("terminated", body or None, return_type=TerminatedEvent)

    def create_thread_event(self, reason: str, thread_id: int) -> ThreadEvent:
        body = {"reason": reason, "threadId": thread_id}
        return self.create_event("thread", body, return_type=ThreadEvent)

    def create_output_event(self, output: str, category: str = "console") -> OutputEvent:
        body = {"output": output, "category": category}
        return self.create_event("output", body, return_type=OutputEvent)

    def create_breakpoint_event(
        self,
        reason: str,
        breakpoint_info: dict[str, Any],
    ) -> BreakpointEvent:
        body = {"reason": reason, "breakpoint": breakpoint_info}
        return self.create_event("breakpoint", body, return_type=BreakpointEvent)

    # ---- Message parsing --------------------------------------------------

    def parse_message(self, message_json: str):
        # -> Union[Request, Response, Event]:
        """Parse a JSON message into a protocol message object.

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


# Backward-compatible alias — all callers can continue using ProtocolHandler.
ProtocolHandler = ProtocolFactory
