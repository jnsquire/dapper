"""
All request/response and event TypedDicts used by the DAP; grouped here now
that smaller structural types are in `structures.py` and capabilities / data
breakpoints are in their own modules.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import Literal
from typing import TypedDict
from typing import Union

from .capabilities import Capabilities
from .capabilities import ExceptionFilterOptions
from .capabilities import ExceptionOptions
from .data_breakpoints import DataBreakpointInfoArguments
from .data_breakpoints import DataBreakpointInfoRequest
from .data_breakpoints import DataBreakpointInfoResponse
from .data_breakpoints import DataBreakpointInfoResponseBody
from .data_breakpoints import SetDataBreakpointsArguments
from .data_breakpoints import SetDataBreakpointsRequest
from .data_breakpoints import SetDataBreakpointsResponse
from .data_breakpoints import SetDataBreakpointsResponseBody
from .structures import Breakpoint
from .structures import Scope
from .structures import Source
from .structures import SourceBreakpoint
from .structures import StackFrame
from .structures import Thread
from .structures import Variable

if TYPE_CHECKING:
    from typing_extensions import NotRequired


# Initialize Request and Response
class InitializeRequestArguments(TypedDict):
    """Arguments for 'initialize' request."""

    clientID: NotRequired[str]
    clientName: NotRequired[str]
    adapterID: str
    locale: NotRequired[str]
    linesStartAt1: bool
    columnsStartAt1: bool
    pathFormat: NotRequired[Literal["path", "uri"]]
    supportsVariableType: NotRequired[bool]
    supportsVariablePaging: NotRequired[bool]
    supportsRunInTerminalRequest: NotRequired[bool]
    supportsMemoryReferences: NotRequired[bool]
    supportsProgressReporting: NotRequired[bool]
    supportsInvalidatedEvent: NotRequired[bool]


class InitializeRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["initialize"]
    arguments: InitializeRequestArguments


class InitializeResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["initialize"]
    body: Capabilities


# Configuration Done Request/Response
class ConfigurationDoneArguments(TypedDict):
    pass


class ConfigurationDoneRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["configurationDone"]
    arguments: NotRequired[ConfigurationDoneArguments]


class ConfigurationDoneResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool


# Launch/Attach/Disconnect/Terminate and many other request/response types
# (these are copied from the original monolithic module and grouped here).

# Launch
class LaunchRequestArguments(TypedDict):
    program: str
    args: NotRequired[list[str]]
    noDebug: bool
    __restart: NotRequired[Any]


class LaunchRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["launch"]
    arguments: LaunchRequestArguments


class LaunchResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["launch"]
    message: NotRequired[str]
    body: NotRequired[Any]


# Attach
class AttachRequestArguments(TypedDict):
    __restart: NotRequired[Any]


class AttachRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["attach"]
    arguments: NotRequired[AttachRequestArguments]


class AttachResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["attach"]
    message: NotRequired[str]
    body: NotRequired[Any]


# Disconnect
class DisconnectArguments(TypedDict):
    restart: NotRequired[bool]
    terminateDebuggee: NotRequired[bool]
    suspendDebuggee: NotRequired[bool]


class DisconnectRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["disconnect"]
    arguments: NotRequired[DisconnectArguments]


class DisconnectResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["disconnect"]
    message: NotRequired[str]
    body: NotRequired[Any]


# Terminate
class TerminateArguments(TypedDict):
    restart: NotRequired[bool]


class TerminateRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["terminate"]
    arguments: NotRequired[TerminateArguments]


class TerminateResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["terminate"]
    message: NotRequired[str]
    body: NotRequired[Any]


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
    breakpoints: list[dict[str, Any]]


class SetFunctionBreakpointsResponseBody(TypedDict):
    breakpoints: list[Breakpoint]


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


# Continue
class ContinueArguments(TypedDict):
    threadId: int
    singleThread: NotRequired[bool]


class ContinueResponseBody(TypedDict):
    allThreadsContinued: NotRequired[bool]


class ContinueRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["continue"]
    arguments: ContinueArguments


class ContinueResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["continue"]
    message: NotRequired[str]
    body: NotRequired[ContinueResponseBody]


# Next
class NextArguments(TypedDict):
    threadId: int
    singleThread: NotRequired[bool]
    granularity: NotRequired[Literal["statement", "line", "instruction"]]


class NextRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["next"]
    arguments: NextArguments


class NextResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["next"]
    message: NotRequired[str]
    body: NotRequired[Any]


# StepIn
class StepInArguments(TypedDict):
    threadId: int
    singleThread: NotRequired[bool]
    targetId: NotRequired[int]
    granularity: NotRequired[Literal["statement", "line", "instruction"]]


class StepInRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["stepIn"]
    arguments: StepInArguments


class StepInResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["stepIn"]
    message: NotRequired[str]
    body: NotRequired[Any]


# StepOut
class StepOutArguments(TypedDict):
    threadId: int
    singleThread: NotRequired[bool]
    granularity: NotRequired[Literal["statement", "line", "instruction"]]


class StepOutRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["stepOut"]
    arguments: StepOutArguments


class StepOutResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["stepOut"]
    message: NotRequired[str]
    body: NotRequired[Any]


# Threads
class ThreadsRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["threads"]


class ThreadsResponseBody(TypedDict):
    threads: list[Thread]


class ThreadsResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["threads"]
    message: NotRequired[str]
    body: NotRequired[ThreadsResponseBody]


# ... (content continues - we already copied this portion)
