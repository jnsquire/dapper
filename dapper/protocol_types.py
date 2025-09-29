"""
Type definitions for the Debug Adapter Protocol.

This module contains TypedDict definitions that match the Debug Adapter Protocol specification.
These types enable better type checking and auto-completion when working with the DAP.
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

    seq: int  # Sequence number of the message
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


# Capabilities and types
class ExceptionBreakpointsFilter(TypedDict):
    """An ExceptionBreakpointsFilter is shown in the UI as a filter option for configuring how exceptions are dealt with."""

    filter: str  # The internal ID of the filter option
    label: str  # The name of the filter option. This is shown in the UI.
    description: NotRequired[
        str
    ]  # A help text providing additional information about the exception filter
    default: NotRequired[
        bool
    ]  # Initial value of the filter option. If not specified a value false is assumed
    supportsCondition: NotRequired[
        bool
    ]  # Controls whether a condition can be specified for this filter option
    conditionDescription: NotRequired[str]  # A help text providing information about the condition


# Exception filter options as defined in the DAP schema.
class ExceptionFilterOptions(TypedDict):
    """An ExceptionFilterOptions is used to specify an exception filter together with a condition for setExceptionBreakpoints."""

    filterId: (
        str  # ID of an exception filter returned by the exceptionBreakpointFilters capability
    )
    condition: NotRequired[str]  # Expression for conditional exceptions
    mode: NotRequired[str]  # One of the breakpointModes advertised by the adapter


class ExceptionOptions(TypedDict):
    """Assigns configuration options to a set of exceptions."""

    # A path selecting exceptions (optional). Each segment is defined by
    # ExceptionPathSegment below.
    path: NotRequired[list[ExceptionPathSegment]]
    # breakMode is required per the DAP schema (one of ExceptionBreakMode)
    breakMode: str


class ExceptionPathSegment(TypedDict):
    """Represents a segment in an exception path used for matching."""

    negate: NotRequired[bool]
    names: list[str]


ExceptionBreakMode = Literal["never", "always", "unhandled", "userUnhandled"]


class Capabilities(TypedDict):
    """Information about the capabilities of a debug adapter."""

    supportsConfigurationDoneRequest: NotRequired[bool]
    supportsFunctionBreakpoints: NotRequired[bool]
    supportsConditionalBreakpoints: NotRequired[bool]
    supportsHitConditionalBreakpoints: NotRequired[bool]
    supportsEvaluateForHovers: NotRequired[bool]
    exceptionBreakpointFilters: NotRequired[list[ExceptionBreakpointsFilter]]
    supportsStepBack: NotRequired[bool]
    supportsSetVariable: NotRequired[bool]
    supportsRestartFrame: NotRequired[bool]
    supportsGotoTargetsRequest: NotRequired[bool]
    supportsStepInTargetsRequest: NotRequired[bool]
    supportsCompletionsRequest: NotRequired[bool]
    completionTriggerCharacters: NotRequired[list[str]]
    supportsModulesRequest: NotRequired[bool]
    supportsValueFormattingOptions: NotRequired[bool]
    supportsExceptionInfoRequest: NotRequired[bool]
    supportTerminateDebuggee: NotRequired[bool]
    supportSuspendDebuggee: NotRequired[bool]
    supportsDelayedStackTraceLoading: NotRequired[bool]
    supportsLoadedSourcesRequest: NotRequired[bool]
    supportsLogPoints: NotRequired[bool]
    supportsTerminateThreadsRequest: NotRequired[bool]
    supportsSetExpression: NotRequired[bool]
    supportsTerminateRequest: NotRequired[bool]
    supportsDataBreakpoints: NotRequired[bool]
    supportsReadMemoryRequest: NotRequired[bool]
    supportsWriteMemoryRequest: NotRequired[bool]
    supportsDisassembleRequest: NotRequired[bool]
    supportsCancelRequest: NotRequired[bool]
    supportsBreakpointLocationsRequest: NotRequired[bool]
    supportsClipboardContext: NotRequired[bool]
    supportsSteppingGranularity: NotRequired[bool]
    supportsInstructionBreakpoints: NotRequired[bool]
    supportsExceptionFilterOptions: NotRequired[bool]
    supportsSingleThreadExecutionRequests: NotRequired[bool]
    # Data breakpoint related capabilities (subset implemented)
    supportsDataBreakpointInfo: NotRequired[bool]
    # Additional/extended capability fields (kept optional and permissive)
    additionalModuleColumns: NotRequired[list[Any]]
    supportedChecksumAlgorithms: NotRequired[list[Any]]
    supportsRestartRequest: NotRequired[bool]
    supportsExceptionOptions: NotRequired[bool]
    supportsDataBreakpointBytes: NotRequired[bool]
    breakpointModes: NotRequired[list[Any]]
    supportsANSIStyling: NotRequired[bool]


"""Data Breakpoints (watchpoints) minimal protocol types.

We intentionally do NOT subclass Request/Response with Literal command overrides
to avoid TypedDict key redefinition issues under current lint settings. These
TypedDicts represent the argument and body payloads only. Generic `Request`
objects with command 'dataBreakpointInfo' or 'setDataBreakpoints' will carry
these shapes in their `arguments` / `body` fields when implemented.
"""


class DataBreakpointInfoArguments(TypedDict, total=False):  # type: ignore[misc]
    """Arguments for 'dataBreakpointInfo' request.

    Minimal subset: identify by variable name within a specific frame.
    """

    name: str
    frameId: int


class DataBreakpointInfoResponseBody(TypedDict, total=False):  # type: ignore[misc]
    dataId: str | None  # Opaque ID used in setDataBreakpoints
    description: str
    accessTypes: list[str]  # Supported access types (currently only ['write'])
    canPersist: bool


class SetDataBreakpointsArguments(TypedDict):  # type: ignore[misc]
    """Arguments for 'setDataBreakpoints' request.

    Each breakpoint: { dataId: str, accessType?: str, condition?: str, hitCondition?: str }
    Stored verbatim; adapter validates only dataId currently.
    """

    breakpoints: list[dict[str, Any]]


class SetDataBreakpointsResponseBody(TypedDict):  # type: ignore[misc]
    breakpoints: list[Breakpoint]


# Source related types
class Source(TypedDict):
    """A source is a descriptor for source code."""

    name: NotRequired[str]  # The short name of the source
    path: str  # The path of the source to be shown in the UI
    sourceReference: NotRequired[
        int
    ]  # If > 0, the contents must be retrieved through the source request
    presentationHint: NotRequired[Literal["normal", "emphasize", "deemphasize"]]
    origin: NotRequired[str]  # The origin of this source
    sources: NotRequired[list[Source]]  # List of sources that are related to this source
    adapterData: NotRequired[
        Any
    ]  # Additional data that a debug adapter might want to loop through the client
    checksums: NotRequired[list[Any]]  # The checksums associated with this file


# Breakpoint related types
class SourceBreakpoint(TypedDict):
    """Properties of a breakpoint or logpoint passed to the setBreakpoints request."""

    line: int  # The source line of the breakpoint or logpoint
    column: NotRequired[int]  # Start position within source line
    condition: NotRequired[str]  # The expression for conditional breakpoints
    hitCondition: NotRequired[
        str
    ]  # The expression that controls how many hits of the breakpoint are ignored
    logMessage: NotRequired[
        str
    ]  # If this exists and is non-empty, the adapter must not 'break' but log the message


class Breakpoint(TypedDict):
    """Information about a breakpoint created in setBreakpoints, setFunctionBreakpoints, etc."""

    verified: bool  # If true, the breakpoint could be set
    message: NotRequired[str]  # A message about the state of the breakpoint
    id: NotRequired[int]  # An identifier for the breakpoint
    source: NotRequired[Source]  # The source where the breakpoint is located
    line: NotRequired[int]  # The start line of the actual range covered by the breakpoint
    column: NotRequired[int]  # Start position of the source range covered by the breakpoint
    endLine: NotRequired[int]  # The end line of the actual range covered by the breakpoint
    endColumn: NotRequired[int]  # End position of the source range covered by the breakpoint
    instructionReference: NotRequired[str]  # A memory reference to where the breakpoint is set
    offset: NotRequired[int]  # The offset from the instruction reference


# Stack trace related types
class StackFrame(TypedDict):
    """A Stackframe contains the source location."""

    id: int  # An identifier for the stack frame
    name: str  # The name of the stack frame, typically a method name
    source: NotRequired[Source]  # The source of the frame
    line: int  # The line within the source of the frame
    column: int  # Start position of the range covered by the stack frame
    endLine: NotRequired[int]  # The end line of the range covered by the stack frame
    endColumn: NotRequired[int]  # End position of the range covered by the stack frame
    canRestart: NotRequired[bool]  # Indicates whether this frame can be restarted
    instructionPointerReference: NotRequired[
        str
    ]  # A memory reference for the current instruction pointer


class Scope(TypedDict):
    """A Scope is a named container for variables."""

    name: str  # Name of the scope such as 'Arguments', 'Locals'
    presentationHint: NotRequired[
        Literal["arguments", "locals", "registers"]
    ]  # A hint for how to present this scope
    variablesReference: (
        int  # The variables of this scope can be retrieved by passing this reference
    )
    namedVariables: NotRequired[int]  # The number of named variables in this scope
    indexedVariables: NotRequired[int]  # The number of indexed variables in this scope
    expensive: (
        bool  # If true, the number of variables in this scope is large or expensive to retrieve
    )
    source: NotRequired[Source]  # The source for this scope
    line: NotRequired[int]  # The start line of the range covered by this scope
    column: NotRequired[int]  # Start position of the range covered by the scope
    endLine: NotRequired[int]  # The end line of the range covered by this scope
    endColumn: NotRequired[int]  # End position of the range covered by the scope


class VariablePresentationHint(TypedDict):
    """Properties of a variable that can be used to determine how to render the variable in the UI."""

    kind: NotRequired[str]  # The kind of variable
    attributes: NotRequired[list[str]]  # Set of attributes represented as an array of strings
    visibility: NotRequired[str]  # Visibility of variable
    lazy: NotRequired[
        bool
    ]  # If true, clients can present the variable with a UI that supports a specific gesture


class Variable(TypedDict):
    """A Variable is a name/value pair."""

    name: str  # The variable's name
    value: str  # The variable's value
    type: NotRequired[str]  # The type of the variable's value
    presentationHint: NotRequired[
        VariablePresentationHint
    ]  # Properties of a variable to determine rendering
    evaluateName: NotRequired[str]  # The evaluatable name of this variable
    variablesReference: int  # If > 0, the variable is structured and its children can be retrieved
    namedVariables: NotRequired[int]  # The number of named child variables
    indexedVariables: NotRequired[int]  # The number of indexed child variables
    memoryReference: NotRequired[str]  # A memory reference associated with this variable


# Thread related types
class Thread(TypedDict):
    """A Thread."""

    id: int  # Unique identifier for the thread
    name: str  # The name of the thread


# Initialize Request and Response
class InitializeRequestArguments(TypedDict):
    """Arguments for 'initialize' request."""

    clientID: NotRequired[str]  # The ID of the client using this adapter
    clientName: NotRequired[str]  # The human readable name of the client
    adapterID: str  # The ID of the debug adapter
    locale: NotRequired[str]  # The ISO-639 locale of the client using this adapter
    linesStartAt1: bool  # If true all line numbers are 1-based
    columnsStartAt1: bool  # If true all column numbers are 1-based
    pathFormat: NotRequired[
        Literal["path", "uri"]
    ]  # Determines in what format paths are specified
    supportsVariableType: NotRequired[bool]  # Client supports the 'type' attribute for variables
    supportsVariablePaging: NotRequired[bool]  # Client supports the paging of variables
    supportsRunInTerminalRequest: NotRequired[bool]  # Client supports the runInTerminal request
    supportsMemoryReferences: NotRequired[bool]  # Client supports memory references
    supportsProgressReporting: NotRequired[bool]  # Client supports progress reporting
    supportsInvalidatedEvent: NotRequired[bool]  # Client supports the invalidated event


class InitializeRequest(TypedDict):
    """The 'initialize' request is sent as the first request to configure the adapter."""

    seq: int
    type: Literal["request"]
    command: Literal["initialize"]
    arguments: InitializeRequestArguments


class InitializeResponse(TypedDict):
    """Response to 'initialize' request."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["initialize"]
    body: Capabilities  # The capabilities of this debug adapter


# Configuration Done Request and Response
class ConfigurationDoneArguments(TypedDict):
    """Arguments for 'configurationDone' request."""


class ConfigurationDoneRequest(TypedDict):
    """This request indicates that the client has finished initialization of the debug adapter."""

    seq: int
    type: Literal["request"]
    command: Literal["configurationDone"]
    arguments: NotRequired[ConfigurationDoneArguments]


class ConfigurationDoneResponse(TypedDict):
    """Response to 'configurationDone' request."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool


# Launch Request and Response
class LaunchRequestArguments(TypedDict):
    """Arguments for 'launch' request. Additional attributes are implementation specific."""

    program: str  # The program to launch
    args: NotRequired[list[str]]  # Optional program arguments
    noDebug: bool  # If true, the launch request should launch the program without debugging
    __restart: NotRequired[Any]  # Arbitrary data from the previous, restarted session


class LaunchRequest(TypedDict):
    """The request to launch the debuggee with or without debugging."""

    seq: int
    type: Literal["request"]
    command: Literal["launch"]
    arguments: LaunchRequestArguments


class LaunchResponse(TypedDict):
    """Response to 'launch' request."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["launch"]
    message: NotRequired[str]
    body: NotRequired[Any]


# Attach Request and Response
class AttachRequestArguments(TypedDict):
    """Arguments for 'attach' request. Additional attributes are implementation specific."""

    __restart: NotRequired[Any]  # Arbitrary data from the previous, restarted session


class AttachRequest(TypedDict):
    """The 'attach' request is sent to attach to a debuggee that is already running."""

    seq: int
    type: Literal["request"]
    command: Literal["attach"]
    arguments: NotRequired[AttachRequestArguments]


class AttachResponse(TypedDict):
    """Response to 'attach' request."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["attach"]
    message: NotRequired[str]
    body: NotRequired[Any]


# Disconnect Request and Response
class DisconnectArguments(TypedDict):
    """Arguments for 'disconnect' request."""

    restart: NotRequired[
        bool
    ]  # A value of true indicates that this 'disconnect' request is part of a restart
    terminateDebuggee: NotRequired[
        bool
    ]  # Indicates whether the debuggee should be terminated when disconnecting
    suspendDebuggee: NotRequired[
        bool
    ]  # Indicates whether the debuggee should stay suspended when disconnecting


class DisconnectRequest(TypedDict):
    """Request to disconnect from the debuggee."""

    seq: int
    type: Literal["request"]
    command: Literal["disconnect"]
    arguments: NotRequired[DisconnectArguments]


class DisconnectResponse(TypedDict):
    """Response to 'disconnect' request."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["disconnect"]
    message: NotRequired[str]
    body: NotRequired[Any]


# Terminate Request and Response
class TerminateArguments(TypedDict):
    """Arguments for 'terminate' request."""

    restart: NotRequired[
        bool
    ]  # A value of true indicates that this 'terminate' request is part of a restart


class TerminateRequest(TypedDict):
    """The 'terminate' request is sent from the client to the debug adapter to terminate the debuggee."""

    seq: int
    type: Literal["request"]
    command: Literal["terminate"]
    arguments: NotRequired[TerminateArguments]


class TerminateResponse(TypedDict):
    """Response to 'terminate' request."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["terminate"]
    message: NotRequired[str]
    body: NotRequired[Any]


# BreakpointLocations Request and Response
class BreakpointLocationsArguments(TypedDict):
    """Arguments for 'breakpointLocations' request."""

    source: Source  # The source location of the breakpoints
    line: int  # Start line of range to search possible breakpoint locations in
    column: NotRequired[int]  # Start position within line
    endLine: NotRequired[int]  # End line of range to search possible breakpoint locations in
    endColumn: NotRequired[int]  # End position within endLine


class BreakpointLocation(TypedDict):
    """Properties of a breakpoint location returned from the 'breakpointLocations' request."""

    line: int  # Start line of breakpoint location
    column: NotRequired[int]  # Start position within line
    endLine: NotRequired[int]  # End line of breakpoint location if it covers a range
    endColumn: NotRequired[int]  # End position within endLine


class BreakpointLocationsRequest(TypedDict):
    """The 'breakpointLocations' request returns all possible locations for source breakpoints in a given range."""

    seq: int
    type: Literal["request"]
    command: Literal["breakpointLocations"]
    arguments: BreakpointLocationsArguments


class BreakpointLocationsResponseBody(TypedDict):
    breakpoints: list[BreakpointLocation]


class BreakpointLocationsResponse(TypedDict):
    """Response to 'breakpointLocations' request."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["breakpointLocations"]
    message: NotRequired[str]
    body: NotRequired[BreakpointLocationsResponseBody]


# SetBreakpoints Request and Response
class SetBreakpointsArguments(TypedDict):
    """Arguments for 'setBreakpoints' request."""

    source: Source  # The source location of the breakpoints
    breakpoints: list[SourceBreakpoint]  # The code locations of the breakpoints
    lines: NotRequired[list[int]]  # Deprecated: The code locations of the breakpoints
    sourceModified: NotRequired[
        bool
    ]  # A value of true indicates that the underlying source has been modified


class SetBreakpointsResponseBody(TypedDict):
    breakpoints: list[Breakpoint]  # Information about the breakpoints.


class SetBreakpointsRequest(TypedDict):
    """Sets multiple breakpoints for a single source and clears all previous breakpoints in that source."""

    seq: int
    type: Literal["request"]
    command: Literal["setBreakpoints"]
    arguments: SetBreakpointsArguments


class SetBreakpointsResponse(TypedDict):
    """Response to 'setBreakpoints' request."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["setBreakpoints"]
    message: NotRequired[str]
    body: NotRequired[SetBreakpointsResponseBody]


# SetFunctionBreakpoints Request and Response
class SetFunctionBreakpointsArguments(TypedDict):
    """Arguments for 'setFunctionBreakpoints' request."""

    # Tests historically pass plain dicts here; accept either FunctionBreakpoint
    # TypedDict instances or plain dicts to reduce friction during runtime.
    breakpoints: list[dict[str, Any]]  # The function names of the breakpoints


class SetFunctionBreakpointsResponseBody(TypedDict):
    breakpoints: list[Breakpoint]  # Information about the breakpoints


class SetFunctionBreakpointsRequest(TypedDict):
    """Replaces all existing function breakpoints with new function breakpoints."""

    seq: int
    type: Literal["request"]
    command: Literal["setFunctionBreakpoints"]
    arguments: SetFunctionBreakpointsArguments


class SetFunctionBreakpointsResponse(TypedDict):
    """Response to 'setFunctionBreakpoints' request."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["setFunctionBreakpoints"]
    message: NotRequired[str]
    body: NotRequired[SetFunctionBreakpointsResponseBody]


# Continue Request and Response
class ContinueArguments(TypedDict):
    """Arguments for 'continue' request."""

    threadId: int  # Continue execution for the specified thread
    singleThread: NotRequired[
        bool
    ]  # If this flag is true, execution is resumed only for this thread


class ContinueResponseBody(TypedDict):
    allThreadsContinued: NotRequired[bool]  # If true, the continue request resumed all threads


class ContinueRequest(TypedDict):
    """The request resumes execution of all threads."""

    seq: int
    type: Literal["request"]
    command: Literal["continue"]
    arguments: ContinueArguments


class ContinueResponse(TypedDict):
    """Response to 'continue' request."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["continue"]
    message: NotRequired[str]
    body: NotRequired[ContinueResponseBody]


# Next (Step Over) Request and Response
class NextArguments(TypedDict):
    """Arguments for 'next' request."""

    threadId: int  # Execute 'next' for this thread
    singleThread: NotRequired[
        bool
    ]  # If this flag is true, all other threads are suspended during step execution
    granularity: NotRequired[Literal["statement", "line", "instruction"]]  # Step granularity


class NextRequest(TypedDict):
    """The request executes one step (over) for the specified thread."""

    seq: int
    type: Literal["request"]
    command: Literal["next"]
    arguments: NextArguments


class NextResponse(TypedDict):
    """Response to 'next' request."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["next"]
    message: NotRequired[str]
    body: NotRequired[Any]


# StepIn Request and Response
class StepInArguments(TypedDict):
    """Arguments for 'stepIn' request."""

    threadId: int  # Execute 'stepIn' for this thread
    singleThread: NotRequired[
        bool
    ]  # If this flag is true, all other threads are suspended during step execution
    targetId: NotRequired[int]  # Id of the target to step into
    granularity: NotRequired[Literal["statement", "line", "instruction"]]  # Step granularity


class StepInRequest(TypedDict):
    """The request resumes the given thread to step into a function/method."""

    seq: int
    type: Literal["request"]
    command: Literal["stepIn"]
    arguments: StepInArguments


class StepInResponse(TypedDict):
    """Response to 'stepIn' request."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["stepIn"]
    message: NotRequired[str]
    body: NotRequired[Any]


# StepOut Request and Response
class StepOutArguments(TypedDict):
    """Arguments for 'stepOut' request."""

    threadId: int  # Execute 'stepOut' for this thread
    singleThread: NotRequired[
        bool
    ]  # If this flag is true, all other threads are suspended during step execution
    granularity: NotRequired[Literal["statement", "line", "instruction"]]  # Step granularity


class StepOutRequest(TypedDict):
    """The request resumes the given thread to step out (return) from the current function/method."""

    seq: int
    type: Literal["request"]
    command: Literal["stepOut"]
    arguments: StepOutArguments


class StepOutResponse(TypedDict):
    """Response to 'stepOut' request."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["stepOut"]
    message: NotRequired[str]
    body: NotRequired[Any]


# Threads Request and Response
class ThreadsRequest(TypedDict):
    """The request retrieves a list of all threads."""

    seq: int
    type: Literal["request"]
    command: Literal["threads"]


class ThreadsResponseBody(TypedDict):
    threads: list[Thread]  # All threads


class ThreadsResponse(TypedDict):
    """Response to 'threads' request."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["threads"]
    message: NotRequired[str]
    body: NotRequired[ThreadsResponseBody]


# LoadedSources Request and Response
class LoadedSourcesRequest(TypedDict):
    """The request retrieves a list of all loaded sources."""

    seq: int
    type: Literal["request"]
    command: Literal["loadedSources"]


class LoadedSourcesResponseBody(TypedDict):
    sources: list[Source]  # Set of loaded sources


class LoadedSourcesResponse(TypedDict):
    """Response to 'loadedSources' request."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["loadedSources"]
    message: NotRequired[str]
    body: NotRequired[LoadedSourcesResponseBody]


# StackTrace Request and Response
class StackTraceArguments(TypedDict):
    """Arguments for 'stackTrace' request."""

    threadId: int  # Retrieve the stacktrace for this thread
    startFrame: int  # The index of the first frame to return
    levels: int  # The maximum number of frames to return
    format: NotRequired[dict[str, Any]]  # Specifies details on how to format the stack frames


class StackTraceResponseBody(TypedDict):
    stackFrames: list[StackFrame]  # The frames of the stack frame
    totalFrames: NotRequired[int]  # The total number of frames available


class StackTraceRequest(TypedDict):
    """The request returns a stacktrace from the current execution state of a given thread."""

    seq: int
    type: Literal["request"]
    command: Literal["stackTrace"]
    arguments: StackTraceArguments


class StackTraceResponse(TypedDict):
    """Response to 'stackTrace' request."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["stackTrace"]
    message: NotRequired[str]
    body: NotRequired[StackTraceResponseBody]


# Scopes Request and Response
class ScopesArguments(TypedDict):
    """Arguments for 'scopes' request."""

    frameId: int  # Retrieve the scopes for this stack frame


class ScopesResponseBody(TypedDict):
    scopes: list[Scope]  # The scopes of the stack frame


class ScopesRequest(TypedDict):
    """The request returns the variable scopes for a given stack frame ID."""

    seq: int
    type: Literal["request"]
    command: Literal["scopes"]
    arguments: ScopesArguments


class ScopesResponse(TypedDict):
    """Response to 'scopes' request."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["scopes"]
    message: NotRequired[str]
    body: NotRequired[ScopesResponseBody]


# Variables Request and Response
class VariablesArguments(TypedDict):
    """Arguments for 'variables' request."""

    variablesReference: int  # The Variables reference
    filter: NotRequired[
        Literal["indexed", "named"]
    ]  # Optional filter to limit the child variables
    start: NotRequired[int]  # The index of the first variable to return
    count: NotRequired[int]  # The number of variables to return
    format: NotRequired[dict[str, Any]]  # Specifies details on how to format the Variable values


class VariablesResponseBody(TypedDict):
    variables: list[Variable]  # All (or a range of) variables for the given reference


class VariablesRequest(TypedDict):
    """Retrieves all child variables for the given variable reference."""

    seq: int
    type: Literal["request"]
    command: Literal["variables"]
    arguments: VariablesArguments


class VariablesResponse(TypedDict):
    """Response to 'variables' request."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["variables"]
    message: NotRequired[str]
    body: NotRequired[VariablesResponseBody]


# SetVariable Request and Response
class SetVariableArguments(TypedDict):
    """Arguments for 'setVariable' request."""

    variablesReference: int  # The reference of the variable container
    name: str  # The name of the variable in the container
    value: str  # The value expression to assign to the variable
    format: NotRequired[dict[str, Any]]  # Specifies details on how to format the variable value


class SetVariableResponseBody(TypedDict):
    """Body of 'setVariable' response."""

    value: str  # The new value of the variable
    type: NotRequired[str]  # The type of the new value
    variablesReference: NotRequired[
        int
    ]  # If > 0, the new value is structured and has child variables
    namedVariables: NotRequired[int]  # The number of named child variables
    indexedVariables: NotRequired[int]  # The number of indexed child variables


class SetVariableRequest(TypedDict):
    """Set the variable with the given name in the variable container to a new value."""

    seq: int
    type: Literal["request"]
    command: Literal["setVariable"]
    arguments: SetVariableArguments


class SetVariableResponse(TypedDict):
    """Response to 'setVariable' request."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["setVariable"]
    message: NotRequired[str]
    body: NotRequired[SetVariableResponseBody]


# Evaluate Request and Response
class EvaluateArguments(TypedDict):
    """Arguments for 'evaluate' request."""

    expression: str  # The expression to evaluate
    frameId: NotRequired[int]  # Evaluate the expression in the scope of this stack frame
    context: NotRequired[str]  # The context in which the evaluate request is used
    format: NotRequired[dict[str, Any]]  # Specifies details on how to format the result


class EvaluateResponseBody(TypedDict):
    result: str  # The result of the evaluate request
    type: NotRequired[str]  # The type of the evaluate result
    presentationHint: NotRequired[VariablePresentationHint]  # Properties of the evaluate result
    variablesReference: int  # If > 0 the evaluate result is structured and has children
    namedVariables: NotRequired[int]  # The number of named child variables
    indexedVariables: NotRequired[int]  # The number of indexed child variables
    memoryReference: NotRequired[str]  # Memory reference to a location appropriate for this result


class EvaluateRequest(TypedDict):
    """Evaluates the given expression in the context of the top most frame."""

    seq: int
    type: Literal["request"]
    command: Literal["evaluate"]
    arguments: EvaluateArguments


class EvaluateResponse(TypedDict):
    """Response to 'evaluate' request."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["evaluate"]
    message: NotRequired[str]
    body: NotRequired[EvaluateResponseBody]


# ExceptionInfo Request and Response
class ExceptionInfoArguments(TypedDict):
    """Arguments for 'exceptionInfo' request."""

    threadId: int  # Retrieve exception info for this thread


class ExceptionDetails(TypedDict):
    message: NotRequired[str]
    typeName: NotRequired[str]
    fullTypeName: NotRequired[str]
    evaluateName: NotRequired[str]
    stackTrace: NotRequired[str]
    innerException: NotRequired[list[ExceptionDetails]]


class ExceptionInfoResponseBody(TypedDict):
    exceptionId: str
    description: NotRequired[str]
    breakMode: Literal["always", "unhandled", "userUnhandled", "never"]
    details: NotRequired[ExceptionDetails]


class ExceptionInfoRequest(TypedDict):
    """Retrieves details of the current exception for a thread."""

    seq: int
    type: Literal["request"]
    command: Literal["exceptionInfo"]
    arguments: ExceptionInfoArguments


class ExceptionInfoResponse(TypedDict):
    """Response to 'exceptionInfo' request."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["exceptionInfo"]
    message: NotRequired[str]
    body: NotRequired[ExceptionInfoResponseBody]


# SetExceptionBreakpoints Request
class SetExceptionBreakpointsArguments(TypedDict):
    """Arguments for 'setExceptionBreakpoints' request."""

    filters: list[str]  # Set of exception filters specified by their ID
    filterOptions: NotRequired[
        list[ExceptionFilterOptions]
    ]  # Configuration options for selected exceptions (optional)
    exceptionOptions: NotRequired[
        list[ExceptionOptions]
    ]  # Configuration options for selected exceptions (optional)


# SetExceptionBreakpoints Response
class SetExceptionBreakpointsResponseBody(TypedDict):
    """Response body for 'setExceptionBreakpoints' request."""

    # Per the DAP schema the enclosing `body` and the `breakpoints`
    # array are optional for backward compatibility. Reflect that
    # by marking `breakpoints` as NotRequired here.
    breakpoints: NotRequired[list[Breakpoint]]


class SetExceptionBreakpointsRequest(TypedDict):
    """Request packet for 'setExceptionBreakpoints'."""

    seq: int
    type: Literal["request"]
    command: Literal["setExceptionBreakpoints"]
    arguments: SetExceptionBreakpointsArguments


class SetExceptionBreakpointsResponse(TypedDict):
    """Response to 'setExceptionBreakpoints' request."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["setExceptionBreakpoints"]
    message: NotRequired[str]
    body: NotRequired[SetExceptionBreakpointsResponseBody]


# Pause Request
class PauseArguments(TypedDict):
    """Arguments for 'pause' request."""

    threadId: int  # Pause execution for this thread


class ModulesArguments(TypedDict):
    """Arguments for 'modules' request."""

    startModule: NotRequired[
        int
    ]  # The index of the first module to return; if omitted modules start at 0
    moduleCount: NotRequired[
        int
    ]  # The number of modules to return. If moduleCount is not specified or 0, all modules are returned


class Module(TypedDict):
    """A Module object represents a row in the modules view."""

    id: str | int  # Unique identifier for the module
    name: str  # A name of the module
    path: NotRequired[str]  # Logical full path to the module
    isOptimized: NotRequired[bool]  # True if the module is optimized
    isUserCode: NotRequired[bool]  # True if the module is considered 'user code'
    version: NotRequired[str]  # Version of Module
    symbolStatus: NotRequired[str]  # User-understandable description of symbol status
    symbolFilePath: NotRequired[str]  # Logical full path to the symbol file
    dateTimeStamp: NotRequired[str]  # Module created or modified, encoded as a RFC 3339 timestamp
    addressRange: NotRequired[str]  # Address range covered by this module


# Modules Request and Response
class ModulesRequest(TypedDict):
    """The request retrieves a list of all loaded modules."""

    command: Literal["modules"]
    arguments: NotRequired[ModulesArguments]


class ModulesResponseBody(TypedDict):
    modules: list[Module]  # The modules
    totalModules: NotRequired[int]  # The total number of modules available


class ModulesResponse(TypedDict):
    """Response to 'modules' request."""

    body: ModulesResponseBody


# Event types
class InitializedEvent(TypedDict):
    """This event indicates that the debug adapter is ready to accept configuration requests."""

    seq: int
    type: Literal["event"]
    event: Literal["initialized"]


class StoppedEventBody(TypedDict):
    reason: str  # The reason for the event
    description: NotRequired[str]  # The full reason for the event
    threadId: NotRequired[int]  # The thread which was stopped
    preserveFocusHint: NotRequired[
        bool
    ]  # A hint to the client that the focus should not be changed
    text: NotRequired[str]  # Additional information
    allThreadsStopped: NotRequired[bool]  # If true, all threads have stopped
    hitBreakpointIds: NotRequired[list[int]]  # Ids of the breakpoints that triggered the event


class StoppedEvent(TypedDict):
    """The event indicates that the execution of the debuggee has stopped."""

    seq: int
    type: Literal["event"]
    event: Literal["stopped"]
    body: StoppedEventBody


class ExitedEventBody(TypedDict):
    exitCode: int  # The exit code returned from the debuggee


class ExitedEvent(TypedDict):
    """The event indicates that the debuggee has exited."""

    seq: int
    type: Literal["event"]
    event: Literal["exited"]
    body: ExitedEventBody


class TerminatedEventBody(TypedDict):
    restart: NotRequired[
        Any
    ]  # A debug adapter may set this to true to request that the client restarts the session


class TerminatedEvent(TypedDict):
    """The event indicates that debugging of the debuggee has terminated."""

    seq: int
    type: Literal["event"]
    event: Literal["terminated"]
    body: NotRequired[TerminatedEventBody]


class ThreadEventBody(TypedDict):
    reason: str  # The reason for the event (started, exited)
    threadId: int  # The identifier of the thread


class ThreadEvent(TypedDict):
    """The event indicates that a thread has started or exited."""

    seq: int
    type: Literal["event"]
    event: Literal["thread"]
    body: ThreadEventBody


class OutputEventBody(TypedDict):
    category: NotRequired[str]  # The output category
    output: str  # The output to report
    variablesReference: NotRequired[int]  # If > 0, output contains objects which can be retrieved
    source: NotRequired[Source]  # The source location where the output was produced
    line: NotRequired[int]  # The line where the output was produced
    column: NotRequired[int]  # The column where the output was produced
    data: NotRequired[Any]  # Additional data to report. For telemetry or JSON output
    group: NotRequired[Literal["start", "startCollapsed", "end"]]
    locationReference: NotRequired[int]


class OutputEvent(TypedDict):
    """The event indicates that the target has produced some output."""

    seq: int
    type: Literal["event"]
    event: Literal["output"]
    body: OutputEventBody


class BreakpointEventBody(TypedDict):
    reason: str  # The reason for the event (changed, new, removed)
    breakpoint: Breakpoint  # The breakpoint


class BreakpointEvent(TypedDict):
    """The event indicates that some information about a breakpoint has changed."""

    seq: int
    type: Literal["event"]
    event: Literal["breakpoint"]
    body: BreakpointEventBody


# All request types dictionary for dispatching based on command
REQUEST_TYPES = {
    "initialize": InitializeRequest,
    "configurationDone": ConfigurationDoneRequest,
    "launch": LaunchRequest,
    "attach": AttachRequest,
    "disconnect": DisconnectRequest,
    "terminate": TerminateRequest,
    "breakpointLocations": BreakpointLocationsRequest,
    "setBreakpoints": SetBreakpointsRequest,
    "setFunctionBreakpoints": SetFunctionBreakpointsRequest,
    "continue": ContinueRequest,
    "next": NextRequest,
    "stepIn": StepInRequest,
    "stepOut": StepOutRequest,
    "threads": ThreadsRequest,
    "loadedSources": LoadedSourcesRequest,
    "modules": ModulesRequest,
    "stackTrace": StackTraceRequest,
    "scopes": ScopesRequest,
    "variables": VariablesRequest,
    "setVariable": SetVariableRequest,
    "evaluate": EvaluateRequest,
    "exceptionInfo": ExceptionInfoRequest,
}

# All response types dictionary for dispatching based on command
RESPONSE_TYPES = {
    "initialize": InitializeResponse,
    "configurationDone": ConfigurationDoneResponse,
    "launch": LaunchResponse,
    "attach": AttachResponse,
    "disconnect": DisconnectResponse,
    "terminate": TerminateResponse,
    "breakpointLocations": BreakpointLocationsResponse,
    "setBreakpoints": SetBreakpointsResponse,
    "setFunctionBreakpoints": SetFunctionBreakpointsResponse,
    "continue": ContinueResponse,
    "next": NextResponse,
    "stepIn": StepInResponse,
    "stepOut": StepOutResponse,
    "threads": ThreadsResponse,
    "loadedSources": LoadedSourcesResponse,
    "modules": ModulesResponse,
    "stackTrace": StackTraceResponse,
    "scopes": ScopesResponse,
    "variables": VariablesResponse,
    "setVariable": SetVariableResponse,
    "evaluate": EvaluateResponse,
    "exceptionInfo": ExceptionInfoResponse,
}

# All event types dictionary for dispatching based on event type
EVENT_TYPES = {
    "initialized": InitializedEvent,
    "stopped": StoppedEvent,
    "exited": ExitedEvent,
    "terminated": TerminatedEvent,
    "thread": ThreadEvent,
    "output": OutputEvent,
    "breakpoint": BreakpointEvent,
}


# Strong per-message TypedDicts (non-inheriting) that explicitly declare the
# top-level `type` literal plus the command/event literal. These are useful
# when you want a discriminated TypedDict for a specific protocol message.


# Requests
class InitializeProtocolRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["initialize"]
    arguments: NotRequired[InitializeRequestArguments]


class ConfigurationDoneProtocolRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["configurationDone"]
    arguments: NotRequired[ConfigurationDoneArguments]


class LaunchProtocolRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["launch"]
    arguments: NotRequired[LaunchRequestArguments]


class AttachProtocolRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["attach"]
    arguments: NotRequired[AttachRequestArguments]


class DisconnectProtocolRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["disconnect"]
    arguments: NotRequired[DisconnectArguments]


class TerminateProtocolRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["terminate"]
    arguments: NotRequired[TerminateArguments]


class BreakpointLocationsProtocolRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["breakpointLocations"]
    arguments: BreakpointLocationsArguments


class SetBreakpointsProtocolRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["setBreakpoints"]
    arguments: SetBreakpointsArguments


class SetFunctionBreakpointsProtocolRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["setFunctionBreakpoints"]
    arguments: SetFunctionBreakpointsArguments


class ContinueProtocolRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["continue"]
    arguments: ContinueArguments


class NextProtocolRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["next"]
    arguments: NextArguments


class StepInProtocolRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["stepIn"]
    arguments: StepInArguments


class StepOutProtocolRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["stepOut"]
    arguments: StepOutArguments


class ThreadsProtocolRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["threads"]


class LoadedSourcesProtocolRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["loadedSources"]


class ModulesProtocolRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["modules"]
    arguments: NotRequired[ModulesArguments]


class StackTraceProtocolRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["stackTrace"]
    arguments: StackTraceArguments


class ScopesProtocolRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["scopes"]
    arguments: ScopesArguments


class VariablesProtocolRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["variables"]
    arguments: VariablesArguments


class SetVariableProtocolRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["setVariable"]
    arguments: SetVariableArguments


class EvaluateProtocolRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["evaluate"]
    arguments: EvaluateArguments


class ExceptionInfoProtocolRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["exceptionInfo"]
    arguments: ExceptionInfoArguments


# Responses
class InitializeProtocolResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["initialize"]
    message: NotRequired[str]
    body: NotRequired[Capabilities]


class BreakpointLocationsProtocolResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["breakpointLocations"]
    message: NotRequired[str]
    body: NotRequired[BreakpointLocationsResponseBody]


class SetBreakpointsProtocolResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["setBreakpoints"]
    message: NotRequired[str]
    body: NotRequired[SetBreakpointsResponseBody]


class SetFunctionBreakpointsProtocolResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["setFunctionBreakpoints"]
    message: NotRequired[str]
    body: NotRequired[SetFunctionBreakpointsResponseBody]


class ContinueProtocolResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["continue"]
    message: NotRequired[str]
    body: NotRequired[ContinueResponseBody]


class ThreadsProtocolResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["threads"]
    message: NotRequired[str]
    body: NotRequired[ThreadsResponseBody]


class LoadedSourcesProtocolResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["loadedSources"]
    message: NotRequired[str]
    body: NotRequired[LoadedSourcesResponseBody]


class ModulesProtocolResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["modules"]
    message: NotRequired[str]
    body: NotRequired[ModulesResponseBody]


class StackTraceProtocolResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["stackTrace"]
    message: NotRequired[str]
    body: NotRequired[StackTraceResponseBody]


class ScopesProtocolResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["scopes"]
    message: NotRequired[str]
    body: NotRequired[ScopesResponseBody]


class VariablesProtocolResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["variables"]
    message: NotRequired[str]
    body: NotRequired[VariablesResponseBody]


class SetVariableProtocolResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["setVariable"]
    message: NotRequired[str]
    body: NotRequired[SetVariableResponseBody]


class EvaluateProtocolResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["evaluate"]
    message: NotRequired[str]
    body: NotRequired[EvaluateResponseBody]


class ExceptionInfoProtocolResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["exceptionInfo"]
    message: NotRequired[str]
    body: NotRequired[ExceptionInfoResponseBody]


# Events
class InitializedProtocolEvent(TypedDict):
    seq: int
    type: Literal["event"]
    event: Literal["initialized"]


class StoppedProtocolEvent(TypedDict):
    seq: int
    type: Literal["event"]
    event: Literal["stopped"]
    body: StoppedEventBody


class ExitedProtocolEvent(TypedDict):
    seq: int
    type: Literal["event"]
    event: Literal["exited"]
    body: ExitedEventBody


class TerminatedProtocolEvent(TypedDict):
    seq: int
    type: Literal["event"]
    event: Literal["terminated"]
    body: NotRequired[TerminatedEventBody]


class ThreadProtocolEvent(TypedDict):
    seq: int
    type: Literal["event"]
    event: Literal["thread"]
    body: ThreadEventBody


class OutputProtocolEvent(TypedDict):
    seq: int
    type: Literal["event"]
    event: Literal["output"]
    body: OutputEventBody


class BreakpointProtocolEvent(TypedDict):
    seq: int
    type: Literal["event"]
    event: Literal["breakpoint"]
    body: BreakpointEventBody


class FunctionBreakpoint(TypedDict, total=False):
    """TypedDict describing a function breakpoint entry from the client."""

    name: str
    condition: str | None
    hitCondition: str | None
    verified: bool


# Union of all strong protocol message variants
ProtocolMessageStrong = Union[
    InitializeProtocolRequest,
    ConfigurationDoneProtocolRequest,
    LaunchProtocolRequest,
    AttachProtocolRequest,
    DisconnectProtocolRequest,
    TerminateProtocolRequest,
    BreakpointLocationsProtocolRequest,
    SetBreakpointsProtocolRequest,
    SetFunctionBreakpointsProtocolRequest,
    ContinueProtocolRequest,
    NextProtocolRequest,
    StepInProtocolRequest,
    StepOutProtocolRequest,
    ThreadsProtocolRequest,
    LoadedSourcesProtocolRequest,
    ModulesProtocolRequest,
    StackTraceProtocolRequest,
    ScopesProtocolRequest,
    VariablesProtocolRequest,
    SetVariableProtocolRequest,
    EvaluateProtocolRequest,
    ExceptionInfoProtocolRequest,
    InitializeProtocolResponse,
    BreakpointLocationsProtocolResponse,
    SetBreakpointsProtocolResponse,
    SetFunctionBreakpointsProtocolResponse,
    ContinueProtocolResponse,
    ThreadsProtocolResponse,
    LoadedSourcesProtocolResponse,
    ModulesProtocolResponse,
    StackTraceProtocolResponse,
    ScopesProtocolResponse,
    VariablesProtocolResponse,
    SetVariableProtocolResponse,
    EvaluateProtocolResponse,
    ExceptionInfoProtocolResponse,
    InitializedProtocolEvent,
    StoppedProtocolEvent,
    ExitedProtocolEvent,
    TerminatedProtocolEvent,
    ThreadProtocolEvent,
    OutputProtocolEvent,
    BreakpointProtocolEvent,
]
