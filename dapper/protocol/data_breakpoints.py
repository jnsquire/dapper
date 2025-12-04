"""
Data breakpoints / watchpoints protocol types.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import Literal
from typing import TypedDict

if TYPE_CHECKING:
    from typing_extensions import NotRequired

    from dapper.protocol.structures import Breakpoint


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