"""Core protocol message types and generic runtime shapes.

This module contains the base Message/Request/Response/Event TypedDicts and
lightweight Generic* runtime-friendly shapes for the ProtocolHandler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import Literal
from typing import TypedDict
from typing import Union

if TYPE_CHECKING:
    from typing_extensions import NotRequired

# Type for the top-level 'type' field in protocol messages.
MessageType = Literal["request", "response", "event"]

# Union of the three top-level protocol message TypedDicts.
ProtocolMessageVariant = Union["Request", "Response", "Event"]


# Base protocol types
class ProtocolMessage(TypedDict):
    """Base class of requests, responses, and events."""

    seq: int
    # Include commonly accessed keys as NotRequired so that code operating on
    # unions of message types (Request|Response|Event) can safely index them
    # without spurious type-checker errors. Concrete subtypes will declare
    # more specific required keys where appropriate.
    type: NotRequired[MessageType]
    # Common runtime keys shared across messages (optional at the base level).
    command: NotRequired[str]
    arguments: NotRequired[Any]
    request_seq: NotRequired[int]
    success: NotRequired[bool]
    event: NotRequired[str]
    body: NotRequired[Any]
    message: NotRequired[str]


class Request(TypedDict):
    """A client or debug adapter initiated request."""

    seq: int
    type: Literal["request"]
    # Runtime keys that are expected on request objects. `command` is
    # required (all requests have a command). `arguments` may be absent for
    # some requests and is therefore NotRequired.
    command: str
    arguments: Any


class Response(TypedDict):
    """Response for a request."""

    seq: int
    type: Literal["response"]
    # Runtime keys for responses. These are required for normal responses;
    # `message` and `body` are optional.
    request_seq: int
    success: bool
    command: str
    message: NotRequired[str]
    body: Any


class Event(TypedDict):
    """A debug adapter initiated event."""

    seq: int
    type: Literal["event"]
    # Runtime keys for events. `event` is required; `body` is optional.
    event: str
    body: Any


# Generic runtime-friendly message shapes (non-inheriting) used by the
# ProtocolFactory and ProtocolHandler when constructing/parsing messages.


class GenericRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: str
    arguments: Any


class GenericResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: str
    message: NotRequired[str]
    body: Any


class GenericEvent(TypedDict):
    seq: int
    type: Literal["event"]
    event: str
    body: Any


class ErrorResponse(TypedDict):
    """On error (whenever success is false), the body can provide more details."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: str
    message: NotRequired[str]
    body: dict[str, Any]  # The body with error details
