"""Type definitions for the debug adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import Literal
from typing import Protocol
from typing import TypedDict

from dapper.protocol.requests import CompletionItem
from dapper.protocol.requests import CompletionsResponseBody

if TYPE_CHECKING:
    from typing_extensions import NotRequired

__all__ = [
    "BreakpointDict",
    "BreakpointResponse",
    "CompletionItem",
    "CompletionsResponseBody",
    "DAPErrorResponse",
    "DAPRequest",
    "DAPResponse",
    "DAPResponseBase",
    "DebuggerServerProtocol",
    "HandlerResult",
    "PyDebuggerThread",
    "SourceDict",
]

# ---------------------------------------------------------------------------
# DAP Response Types
# ---------------------------------------------------------------------------


class DAPResponseBase(TypedDict):
    """Base structure for all DAP responses."""

    type: Literal["response"]
    request_seq: int
    success: bool
    command: str


class DAPResponse(DAPResponseBase, total=False):
    """Full DAP response with optional body and message."""

    message: str
    body: dict[str, Any]


class DAPErrorResponse(DAPResponseBase):
    """DAP error response with standardized error body."""

    message: str
    body: dict[str, Any]


# Type alias for handler return values
HandlerResult = "DAPResponse | None"


class DebuggerServerProtocol(Protocol):
    """Protocol for server features used by PyDebugger.

    Implemented by DebugAdapterServer; extracted to avoid a concrete type
    dependency between the debugger facade and server core.
    """

    async def send_event(self, event_name: str, body: dict[str, Any] | None = None) -> None:
        """Send a DAP event to the connected client."""


# ---------------------------------------------------------------------------
# DAP Request Types
# ---------------------------------------------------------------------------


class DAPRequest(TypedDict):
    """Base structure for all DAP requests."""

    seq: int
    type: Literal["request"]
    command: str
    arguments: NotRequired[dict[str, Any]]


# ---------------------------------------------------------------------------
# Response Body Types (local definitions for types not in protocol module files)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Breakpoint Types
# ---------------------------------------------------------------------------


class BreakpointResponse(TypedDict, total=False):
    """DAP breakpoint response format.

    Used for responses to setBreakpoints requests. The `verified` field
    is required; all others are optional per the DAP specification.
    """

    verified: bool
    message: NotRequired[str]
    line: NotRequired[int]
    condition: NotRequired[str | None]
    hitCondition: NotRequired[str | None]
    logMessage: NotRequired[str | None]


class BreakpointDict(TypedDict, total=False):
    """Internal breakpoint storage format.

    Used for storing breakpoint state internally. All fields can be None
    to represent unset/unknown values.
    """

    verified: bool
    message: str | None
    line: int | None
    condition: str | None
    hitCondition: str | None
    logMessage: str | None


# Type aliases
SourceDict = dict[str, Any]  # Dictionary representing source file information


class PyDebuggerThread:
    """Lightweight thread model tracked by the debugger."""

    def __init__(self, thread_id: int, name: str):
        self.id = thread_id
        self.name = name
        self.frames: list[dict[str, Any]] = []
        self.is_stopped: bool = False
        self.stop_reason: str = ""
