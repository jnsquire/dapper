"""Breakpoint-related TypedDicts."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import Literal
from typing import TypedDict

if TYPE_CHECKING:
    from typing_extensions import NotRequired

    from dapper.protocol.structures import Breakpoint
    from dapper.protocol.structures import Source
    from dapper.protocol.structures import SourceBreakpoint


# BreakpointLocations
class BreakpointLocationsArguments(TypedDict):
    source: Source
    line: int
    column: NotRequired[int]
    endLine: NotRequired[int]
    endColumn: NotRequired[int]


class BreakpointLocation(TypedDict):
    line: int
    column: NotRequired[int]
    endLine: NotRequired[int]
    endColumn: NotRequired[int]


class BreakpointLocationsRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["breakpointLocations"]
    arguments: BreakpointLocationsArguments


class BreakpointLocationsResponseBody(TypedDict):
    breakpoints: list[BreakpointLocation]


class BreakpointLocationsResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["breakpointLocations"]
    message: NotRequired[str]
    body: NotRequired[BreakpointLocationsResponseBody]


# SetBreakpoints
class SetBreakpointsArguments(TypedDict):
    source: Source
    breakpoints: list[SourceBreakpoint]
    lines: NotRequired[list[int]]
    sourceModified: NotRequired[bool]


class SetBreakpointsResponseBody(TypedDict):
    breakpoints: list[Breakpoint]


class SetBreakpointsRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["setBreakpoints"]
    arguments: SetBreakpointsArguments


class SetBreakpointsResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["setBreakpoints"]
    message: NotRequired[str]
    body: NotRequired[SetBreakpointsResponseBody]


# SetFunctionBreakpoints
class SetFunctionBreakpointsArguments(TypedDict):
    breakpoints: list[FunctionBreakpoint]


class SetFunctionBreakpointsResponseBody(TypedDict):
    breakpoints: list[Breakpoint]


class SetExceptionBreakpointsResponseBody(TypedDict):
    breakpoints: list[Breakpoint]


class FunctionBreakpoint(TypedDict, total=False):
    name: str
    condition: NotRequired[str]
    hitCondition: NotRequired[str]
    verified: NotRequired[bool]


# Data breakpoint / watchpoint requests
class DataBreakpointInfoArguments(TypedDict, total=False):
    """Arguments for 'dataBreakpointInfo' request.

    Minimal subset: identify by variable name within a specific frame.
    """

    name: str
    frameId: int


class DataBreakpointInfoRequest(TypedDict):
    """Obtains information on a possible data breakpoint."""

    seq: int
    type: Literal["request"]
    command: Literal["dataBreakpointInfo"]
    arguments: DataBreakpointInfoArguments


class DataBreakpointInfoResponseBody(TypedDict, total=False):
    dataId: str | None  # Opaque ID used in setDataBreakpoints
    description: str
    accessTypes: list[str]  # Supported access types (currently only ['write'])
    canPersist: bool
    # Optional extra info provided by some adapters/debuggers
    type: NotRequired[str]
    value: NotRequired[str]


class DataBreakpointInfoResponse(TypedDict):
    """Response to 'dataBreakpointInfo' request."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["dataBreakpointInfo"]
    message: NotRequired[str]
    body: NotRequired[DataBreakpointInfoResponseBody]


class SetDataBreakpointsArguments(TypedDict):
    """Arguments for 'setDataBreakpoints' request.

    Each breakpoint: { dataId: str, accessType?: str, condition?: str, hitCondition?: str }
    Stored verbatim; adapter validates only dataId currently.
    """

    breakpoints: list[dict[str, Any]]


class SetDataBreakpointsRequest(TypedDict):
    """Replaces all existing data breakpoints with new data breakpoints."""

    seq: int
    type: Literal["request"]
    command: Literal["setDataBreakpoints"]
    arguments: SetDataBreakpointsArguments


class SetDataBreakpointsResponseBody(TypedDict):
    breakpoints: list[Breakpoint]


class SetDataBreakpointsResponse(TypedDict):
    """Response to 'setDataBreakpoints' request."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["setDataBreakpoints"]
    message: NotRequired[str]
    body: NotRequired[SetDataBreakpointsResponseBody]


class SetFunctionBreakpointsRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["setFunctionBreakpoints"]
    arguments: SetFunctionBreakpointsArguments


class SetFunctionBreakpointsResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["setFunctionBreakpoints"]
    message: NotRequired[str]
    body: NotRequired[SetFunctionBreakpointsResponseBody]
