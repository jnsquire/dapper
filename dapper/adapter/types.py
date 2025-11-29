"""Type definitions for the debug adapter."""

from __future__ import annotations

from typing import Any
from typing import Literal
from typing import TypedDict

from typing_extensions import NotRequired  # noqa: TC002

__all__ = [
    "BreakpointDict",
    "BreakpointResponse",
    "CompletionsResponseBody",
    "DAPErrorResponse",
    "DAPRequest",
    "DAPResponse",
    "DAPResponseBase",
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
    """DAP error response - requires message, no body."""

    message: str


# Type alias for handler return values
HandlerResult = "DAPResponse | None"


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


class CompletionsResponseBody(TypedDict):
    """Body for completions response."""

    targets: list[dict[str, Any]]


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
