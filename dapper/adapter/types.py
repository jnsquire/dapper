"""Type definitions for the debug adapter."""

from __future__ import annotations

from typing import Any
from typing import TypedDict

from typing_extensions import NotRequired  # noqa: TC002 - used at runtime in TypedDict


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
