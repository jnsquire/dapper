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
from typing import Callable
from typing import Literal
from typing import Protocol
from typing import TypeVar
from typing import cast
from typing import overload

# ParamSpec arrived in 3.10; for 3.9 we fall back to the backport.
try:
    from typing import ParamSpec
except ImportError:  # pragma: no cover - very old interpreter
    from typing_extensions import ParamSpec  # type: ignore[assignment]

from dataclasses import dataclass
from typing import Generic

from dapper.protocol.messages import ErrorResponse
from dapper.protocol.messages import GenericEvent

# runtime imports for use in return_type arguments and casts
from dapper.protocol.messages import GenericRequest
from dapper.protocol.messages import GenericResponse
from dapper.protocol.requests import BreakpointEvent
from dapper.protocol.requests import ConfigurationDoneArguments
from dapper.protocol.requests import ConfigurationDoneRequest
from dapper.protocol.requests import ContinueArguments
from dapper.protocol.requests import ContinueRequest
from dapper.protocol.requests import EvaluateArguments
from dapper.protocol.requests import EvaluateRequest
from dapper.protocol.requests import ExitedEvent

# event TypedDicts used by convenience event helpers
from dapper.protocol.requests import InitializedEvent

# specific request/response TypedDicts used by convenience helpers and tests
from dapper.protocol.requests import InitializeRequest
from dapper.protocol.requests import InitializeRequestArguments
from dapper.protocol.requests import LaunchRequest
from dapper.protocol.requests import LaunchRequestArguments
from dapper.protocol.requests import NextArguments
from dapper.protocol.requests import NextRequest
from dapper.protocol.requests import OutputEvent
from dapper.protocol.requests import ScopesArguments
from dapper.protocol.requests import ScopesRequest
from dapper.protocol.requests import SetBreakpointsArguments
from dapper.protocol.requests import SetBreakpointsRequest
from dapper.protocol.requests import StackTraceArguments
from dapper.protocol.requests import StackTraceRequest
from dapper.protocol.requests import StepInArguments
from dapper.protocol.requests import StepInRequest
from dapper.protocol.requests import StepOutArguments
from dapper.protocol.requests import StepOutRequest
from dapper.protocol.requests import StoppedEvent
from dapper.protocol.requests import TerminatedEvent
from dapper.protocol.requests import ThreadEvent
from dapper.protocol.requests import ThreadsRequest
from dapper.protocol.requests import VariablesArguments
from dapper.protocol.requests import VariablesRequest

# Request descriptor constants mapping commands to their argument and return types.
# ArgsType represents the arguments object type for a request (used for type checking).
# RequestDescT represents the complete request envelope type.
ArgsType = TypeVar("ArgsType")
RequestDescT = TypeVar("RequestDescT")


@dataclass(frozen=True)
class RequestSpec(Generic[ArgsType, RequestDescT]):
    command: str
    args_type: type[ArgsType]
    return_type: type[RequestDescT]


INITIALIZE_SPEC: RequestSpec[InitializeRequestArguments, InitializeRequest] = RequestSpec(
    "initialize", InitializeRequestArguments, InitializeRequest
)
LAUNCH_SPEC: RequestSpec[LaunchRequestArguments, LaunchRequest] = RequestSpec(
    "launch", LaunchRequestArguments, LaunchRequest
)
CONFIG_DONE_SPEC: RequestSpec[ConfigurationDoneArguments, ConfigurationDoneRequest] = RequestSpec(
    "configurationDone", ConfigurationDoneArguments, ConfigurationDoneRequest
)
SET_BREAKPOINTS_SPEC: RequestSpec[SetBreakpointsArguments, SetBreakpointsRequest] = RequestSpec(
    "setBreakpoints", SetBreakpointsArguments, SetBreakpointsRequest
)
CONTINUE_SPEC: RequestSpec[ContinueArguments, ContinueRequest] = RequestSpec(
    "continue", ContinueArguments, ContinueRequest
)
NEXT_SPEC: RequestSpec[NextArguments, NextRequest] = RequestSpec(
    "next", NextArguments, NextRequest
)
STEP_IN_SPEC: RequestSpec[StepInArguments, StepInRequest] = RequestSpec(
    "stepIn", StepInArguments, StepInRequest
)
STEP_OUT_SPEC: RequestSpec[StepOutArguments, StepOutRequest] = RequestSpec(
    "stepOut", StepOutArguments, StepOutRequest
)
THREADS_SPEC: RequestSpec[dict[str, Any], ThreadsRequest] = RequestSpec(
    "threads", dict[str, Any], ThreadsRequest
)
STACK_TRACE_SPEC: RequestSpec[StackTraceArguments, StackTraceRequest] = RequestSpec(
    "stackTrace", StackTraceArguments, StackTraceRequest
)
SCOPES_SPEC: RequestSpec[ScopesArguments, ScopesRequest] = RequestSpec(
    "scopes", ScopesArguments, ScopesRequest
)
VARIABLES_SPEC: RequestSpec[VariablesArguments, VariablesRequest] = RequestSpec(
    "variables", VariablesArguments, VariablesRequest
)
EVALUATE_SPEC: RequestSpec[EvaluateArguments, EvaluateRequest] = RequestSpec(
    "evaluate", EvaluateArguments, EvaluateRequest
)

if TYPE_CHECKING:
    # ProtocolMessage is only needed for typing, not used at runtime
    from dapper.protocol.messages import ProtocolMessage
    from dapper.protocol.structures import Source

# Type variables for generic message types
T = TypeVar("T", bound="ProtocolMessage")

# ``RequestT``/``ResponseT``/``EventT`` are only used for the return type of
# the factory helpers; they stay unbounded so callers can use any concrete
# TypedDict (including our ``*Request``/``*Response`` types) without hitting
# variance problems.
RequestT = TypeVar("RequestT")
ResponseT = TypeVar("ResponseT")
EventT = TypeVar("EventT")

# ---------------------------------------------------------------------------
# helpers for request-maker callables
# ---------------------------------------------------------------------------
# we want a type that expresses "a function taking the arguments object
# for a specific request and returning a fully-formed request envelope".
# `TypedDict` doesn't work as a bound in pylance/pyright, so use
# a looser type that still represents a mapping.  The type variables are
# not actually instantiated anywhere other than return types, so this
# limitation doesn't weaken safety in practice.
ReqT = TypeVar("ReqT", bound=dict[str, Any])
ArgsT = TypeVar("ArgsT", bound=dict[str, Any])
P = ParamSpec("P")

# two stylistic variants; the second uses ParamSpec so callers can invoke
# the returned callable with keyword arguments instead of bending a dict.
# ``RequestMaker`` is parameterized by ``ArgsType`` so that a spec's
# argument type flows through directly.
RequestMaker = Callable[[ArgsType], ReqT]
RequestMaker2 = Callable[P, ReqT]


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
    #
    # Overloads let the type checker know that when a ``RequestSpec`` is
    # passed the return type is the spec's ``return_type`` and the ``arguments``
    # parameter is typed according to the spec's ``args_type``.
    @overload
    def create_request(
        self,
        command_or_spec: RequestSpec[ArgsType, RequestT],
        arguments: ArgsType | None = None,
    ) -> RequestT: ...

    @overload
    def create_request(
        self,
        command_or_spec: str,
        arguments: dict[str, Any] | None = None,
        *,
        return_type: type[RequestT],
    ) -> RequestT: ...

    # New callers may pass a ``RequestSpec`` constant (see top-level
    # descriptors) instead of a raw command string and explicit return_type.
    # The specification also records the expected arguments type, allowing
    # the overload above to enforce that callers only supply an appropriate
    # dictionary.
    def create_request(  # type: ignore[override]
        self,
        command_or_spec: str | RequestSpec[Any, RequestT],
        arguments: dict[str, Any] | None = None,
        *,
        return_type: type[RequestT] = GenericRequest,
    ) -> RequestT:
        # support the new ``RequestSpec`` form for additional safety
        if isinstance(command_or_spec, RequestSpec):
            command = command_or_spec.command
            return_type = command_or_spec.return_type  # type: ignore[assignment]  # noqa: F841
        else:
            command = command_or_spec
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

    # legacy-style error helper for convenience.  the server core uses this
    # instead of building the body itself.
    @overload
    def create_error_response(
        self,
        request: dict[str, Any],
        error_message: str,
    ) -> ErrorResponse: ...

    @overload
    def create_error_response(
        self,
        request: dict[str, Any],
        error_message: str,
        *,
        return_type: type[ResponseT],
    ) -> ResponseT: ...

    def create_error_response(
        self,
        request: dict[str, Any],
        error_message: str,
        *,
        return_type: type[ResponseT] | None = None,
    ) -> ResponseT | ErrorResponse:
        # ``request`` may be any mapping; it may not support ``get`` so
        # index manually with a fallback of ``None``.
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
        args = InitializeRequestArguments(
            clientID=client_id,
            adapterID=adapter_id,
            linesStartAt1=True,
            columnsStartAt1=True,
            supportsVariableType=True,
            supportsVariablePaging=True,
            supportsRunInTerminalRequest=False,
        )
        return self.create_request(INITIALIZE_SPEC, args)

    def create_launch_request(
        self,
        program: str,
        args: list | None = None,
        no_debug: bool = False,
    ) -> LaunchRequest:
        launch_args = LaunchRequestArguments(program=program, noDebug=no_debug)
        if args is not None:
            launch_args["args"] = args
        return self.create_request(LAUNCH_SPEC, launch_args)

    def create_configuration_done_request(self) -> ConfigurationDoneRequest:
        # explicit ``None`` matches the overload's optional arguments
        return self.create_request(CONFIG_DONE_SPEC, None)

    def create_set_breakpoints_request(
        self,
        source: Source,
        breakpoints: list,
    ) -> SetBreakpointsRequest:
        args = SetBreakpointsArguments(source=source, breakpoints=breakpoints)
        return self.create_request(SET_BREAKPOINTS_SPEC, args)

    def create_continue_request(self, thread_id: int) -> ContinueRequest:
        args = ContinueArguments(threadId=thread_id)
        return self.create_request(CONTINUE_SPEC, args)

    def create_next_request(
        self,
        thread_id: int,
        granularity: Literal["line", "statement", "instruction"] = "line",
    ) -> NextRequest:
        """Create a DAP ``next`` (step-over) request.

        Args:
            thread_id: The thread to step.
            granularity: DAP stepGranularity — ``"line"``, ``"statement"``, or
                ``"instruction"`` (default ``"line"``).

        """
        args = NextArguments(threadId=thread_id)
        if granularity != "line":
            args["granularity"] = granularity
        return self.create_request(NEXT_SPEC, args)

    def create_step_in_request(
        self,
        thread_id: int,
        target_id: int | None = None,
        granularity: Literal["line", "statement", "instruction"] = "line",
    ) -> StepInRequest:
        """Create a DAP ``stepIn`` request.

        Args:
            thread_id: The thread to step into.
            target_id: Optional step-in target from ``stepInTargets``.
            granularity: DAP stepGranularity (default ``"line"``).

        """
        args = StepInArguments(threadId=thread_id)
        if target_id is not None:
            args["targetId"] = target_id
        if granularity != "line":
            args["granularity"] = granularity
        return self.create_request(STEP_IN_SPEC, args)

    def create_step_out_request(
        self,
        thread_id: int,
        granularity: Literal["line", "statement", "instruction"] = "line",
    ) -> StepOutRequest:
        """Create a DAP ``stepOut`` request.

        Args:
            thread_id: The thread to step out from.
            granularity: DAP stepGranularity (default ``"line"``).

        """
        args = StepOutArguments(threadId=thread_id)
        if granularity != "line":
            args["granularity"] = granularity
        return self.create_request(STEP_OUT_SPEC, args)

    def create_threads_request(self) -> ThreadsRequest:
        return self.create_request(THREADS_SPEC)

    def create_stack_trace_request(
        self,
        thread_id: int,
        start_frame: int = 0,
        levels: int = 20,
    ) -> StackTraceRequest:
        args = StackTraceArguments(threadId=thread_id, startFrame=start_frame, levels=levels)
        return self.create_request(STACK_TRACE_SPEC, args)

    def create_scopes_request(self, frame_id: int) -> ScopesRequest:
        args = ScopesArguments(frameId=frame_id)
        return self.create_request(SCOPES_SPEC, args)

    def create_variables_request(self, variables_reference: int) -> VariablesRequest:
        args = VariablesArguments(variablesReference=variables_reference)
        return self.create_request(VARIABLES_SPEC, args)

    def create_evaluate_request(
        self,
        expression: str,
        frame_id: int | None = None,
    ) -> EvaluateRequest:
        args = EvaluateArguments(expression=expression)
        if frame_id is not None:
            args["frameId"] = cast("Any", frame_id)

        return self.create_request(EVALUATE_SPEC, args)

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
