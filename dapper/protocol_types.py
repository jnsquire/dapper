"""
Type definitions for the Debug Adapter Protocol.

This module contains TypedDict definitions that match the Debug Adapter Protocol specification.
These types enable better type checking and auto-completion when working with the DAP.
"""

from __future__ import annotations

from typing import Any
from typing import Literal
from typing import NotRequired
from typing import Self
from typing import TypedDict


# Base protocol types
class ProtocolMessage(TypedDict):
    """Base class of requests, responses, and events."""

    seq: int  # Sequence number of the message
    type: Literal["request", "response", "event"]  # Message type


class Request(ProtocolMessage):
    """A client or debug adapter initiated request."""

    type: Literal["request"]
    command: str  # The command to execute
    arguments: NotRequired[Any]  # Object containing arguments for the command


class Response(ProtocolMessage):
    """Response for a request."""

    type: Literal["response"]
    request_seq: int  # Sequence number of the corresponding request
    success: bool  # Outcome of the request
    command: str  # The command requested
    message: NotRequired[str]  # Contains the raw error in short form if success is false
    body: NotRequired[
        Any
    ]  # Contains request result if success is true and error details if success is false


class Event(ProtocolMessage):
    """A debug adapter initiated event."""

    type: Literal["event"]
    event: str  # Type of event
    body: NotRequired[Any]  # Event-specific information


class ErrorResponse(Response):
    """On error (whenever success is false), the body can provide more details."""

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


# Source related types
class Source(TypedDict):
    """A source is a descriptor for source code."""

    name: NotRequired[str]  # The short name of the source
    path: NotRequired[str]  # The path of the source to be shown in the UI
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


class FunctionBreakpoint(TypedDict):
    """Properties of a breakpoint passed to the setFunctionBreakpoints request."""

    name: str  # The name of the function
    condition: NotRequired[str]  # An expression for conditional breakpoints
    hitCondition: NotRequired[
        str
    ]  # An expression that controls how many hits of the breakpoint are ignored


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
    linesStartAt1: NotRequired[bool]  # If true all line numbers are 1-based
    columnsStartAt1: NotRequired[bool]  # If true all column numbers are 1-based
    pathFormat: NotRequired[
        Literal["path", "uri"]
    ]  # Determines in what format paths are specified
    supportsVariableType: NotRequired[bool]  # Client supports the 'type' attribute for variables
    supportsVariablePaging: NotRequired[bool]  # Client supports the paging of variables
    supportsRunInTerminalRequest: NotRequired[bool]  # Client supports the runInTerminal request
    supportsMemoryReferences: NotRequired[bool]  # Client supports memory references
    supportsProgressReporting: NotRequired[bool]  # Client supports progress reporting
    supportsInvalidatedEvent: NotRequired[bool]  # Client supports the invalidated event


class InitializeRequest(Request):
    """The 'initialize' request is sent as the first request to configure the adapter."""

    command: Literal["initialize"]
    arguments: InitializeRequestArguments


class InitializeResponse(Response):
    """Response to 'initialize' request."""

    body: Capabilities  # The capabilities of this debug adapter


# Configuration Done Request and Response
class ConfigurationDoneArguments(TypedDict):
    """Arguments for 'configurationDone' request."""


class ConfigurationDoneRequest(Request):
    """This request indicates that the client has finished initialization of the debug adapter."""

    command: Literal["configurationDone"]
    arguments: NotRequired[ConfigurationDoneArguments]


class ConfigurationDoneResponse(Response):
    """Response to 'configurationDone' request."""


# Launch Request and Response
class LaunchRequestArguments(TypedDict):
    """Arguments for 'launch' request. Additional attributes are implementation specific."""

    noDebug: NotRequired[
        bool
    ]  # If true, the launch request should launch the program without debugging
    __restart: NotRequired[Any]  # Arbitrary data from the previous, restarted session


class LaunchRequest(Request):
    """The request to launch the debuggee with or without debugging."""

    command: Literal["launch"]
    arguments: LaunchRequestArguments


class LaunchResponse(Response):
    """Response to 'launch' request."""


# Attach Request and Response
class AttachRequestArguments(TypedDict):
    """Arguments for 'attach' request. Additional attributes are implementation specific."""

    __restart: NotRequired[Any]  # Arbitrary data from the previous, restarted session


class AttachRequest(Request):
    """The 'attach' request is sent to attach to a debuggee that is already running."""

    command: Literal["attach"]
    arguments: AttachRequestArguments


class AttachResponse(Response):
    """Response to 'attach' request."""


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


class DisconnectRequest(Request):
    """Request to disconnect from the debuggee."""

    command: Literal["disconnect"]
    arguments: NotRequired[DisconnectArguments]


class DisconnectResponse(Response):
    """Response to 'disconnect' request."""


# Terminate Request and Response
class TerminateArguments(TypedDict):
    """Arguments for 'terminate' request."""

    restart: NotRequired[
        bool
    ]  # A value of true indicates that this 'terminate' request is part of a restart


class TerminateRequest(Request):
    """The 'terminate' request is sent from the client to the debug adapter to terminate the debuggee."""

    command: Literal["terminate"]
    arguments: NotRequired[TerminateArguments]


class TerminateResponse(Response):
    """Response to 'terminate' request."""


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


class BreakpointLocationsRequest(Request):
    """The 'breakpointLocations' request returns all possible locations for source breakpoints in a given range."""

    command: Literal["breakpointLocations"]
    arguments: BreakpointLocationsArguments


class BreakpointLocationsResponseBody(TypedDict):
    breakpoints: list[BreakpointLocation]


class BreakpointLocationsResponse(Response):
    """Response to 'breakpointLocations' request."""

    body: BreakpointLocationsResponseBody


# SetBreakpoints Request and Response
class SetBreakpointsArguments(TypedDict):
    """Arguments for 'setBreakpoints' request."""

    source: Source  # The source location of the breakpoints
    breakpoints: NotRequired[list[SourceBreakpoint]]  # The code locations of the breakpoints
    lines: NotRequired[list[int]]  # Deprecated: The code locations of the breakpoints
    sourceModified: NotRequired[
        bool
    ]  # A value of true indicates that the underlying source has been modified


class SetBreakpointsResponseBody(TypedDict):
    breakpoints: list[Breakpoint]  # Information about the breakpoints.


class SetBreakpointsRequest(Request):
    """Sets multiple breakpoints for a single source and clears all previous breakpoints in that source."""

    command: Literal["setBreakpoints"]
    arguments: SetBreakpointsArguments


class SetBreakpointsResponse(Response):
    """Response to 'setBreakpoints' request."""

    body: SetBreakpointsResponseBody


# SetFunctionBreakpoints Request and Response
class SetFunctionBreakpointsArguments(TypedDict):
    """Arguments for 'setFunctionBreakpoints' request."""

    breakpoints: list[FunctionBreakpoint]  # The function names of the breakpoints


class SetFunctionBreakpointsResponseBody(TypedDict):
    breakpoints: list[Breakpoint]  # Information about the breakpoints


class SetFunctionBreakpointsRequest(Request):
    """Replaces all existing function breakpoints with new function breakpoints."""

    command: Literal["setFunctionBreakpoints"]
    arguments: SetFunctionBreakpointsArguments


class SetFunctionBreakpointsResponse(Response):
    """Response to 'setFunctionBreakpoints' request."""

    body: SetFunctionBreakpointsResponseBody


# Continue Request and Response
class ContinueArguments(TypedDict):
    """Arguments for 'continue' request."""

    threadId: int  # Continue execution for the specified thread
    singleThread: NotRequired[
        bool
    ]  # If this flag is true, execution is resumed only for this thread


class ContinueResponseBody(TypedDict):
    allThreadsContinued: NotRequired[bool]  # If true, the continue request resumed all threads


class ContinueRequest(Request):
    """The request resumes execution of all threads."""

    command: Literal["continue"]
    arguments: ContinueArguments


class ContinueResponse(Response):
    """Response to 'continue' request."""

    body: ContinueResponseBody


# Next (Step Over) Request and Response
class NextArguments(TypedDict):
    """Arguments for 'next' request."""

    threadId: int  # Execute 'next' for this thread
    singleThread: NotRequired[
        bool
    ]  # If this flag is true, all other threads are suspended during step execution
    granularity: NotRequired[Literal["statement", "line", "instruction"]]  # Step granularity


class NextRequest(Request):
    """The request executes one step (over) for the specified thread."""

    command: Literal["next"]
    arguments: NextArguments


class NextResponse(Response):
    """Response to 'next' request."""


# StepIn Request and Response
class StepInArguments(TypedDict):
    """Arguments for 'stepIn' request."""

    threadId: int  # Execute 'stepIn' for this thread
    singleThread: NotRequired[
        bool
    ]  # If this flag is true, all other threads are suspended during step execution
    targetId: NotRequired[int]  # Id of the target to step into
    granularity: NotRequired[Literal["statement", "line", "instruction"]]  # Step granularity


class StepInRequest(Request):
    """The request resumes the given thread to step into a function/method."""

    command: Literal["stepIn"]
    arguments: StepInArguments


class StepInResponse(Response):
    """Response to 'stepIn' request."""


# StepOut Request and Response
class StepOutArguments(TypedDict):
    """Arguments for 'stepOut' request."""

    threadId: int  # Execute 'stepOut' for this thread
    singleThread: NotRequired[
        bool
    ]  # If this flag is true, all other threads are suspended during step execution
    granularity: NotRequired[Literal["statement", "line", "instruction"]]  # Step granularity


class StepOutRequest(Request):
    """The request resumes the given thread to step out (return) from the current function/method."""

    command: Literal["stepOut"]
    arguments: StepOutArguments


class StepOutResponse(Response):
    """Response to 'stepOut' request."""


# Threads Request and Response
class ThreadsRequest(Request):
    """The request retrieves a list of all threads."""

    command: Literal["threads"]


class ThreadsResponseBody(TypedDict):
    threads: list[Thread]  # All threads


class ThreadsResponse(Response):
    """Response to 'threads' request."""

    body: ThreadsResponseBody


# LoadedSources Request and Response
class LoadedSourcesRequest(Request):
    """The request retrieves a list of all loaded sources."""

    command: Literal["loadedSources"]


class LoadedSourcesResponseBody(TypedDict):
    sources: list[Source]  # Set of loaded sources


class LoadedSourcesResponse(Response):
    """Response to 'loadedSources' request."""

    body: LoadedSourcesResponseBody


# StackTrace Request and Response
class StackTraceArguments(TypedDict):
    """Arguments for 'stackTrace' request."""

    threadId: int  # Retrieve the stacktrace for this thread
    startFrame: NotRequired[int]  # The index of the first frame to return
    levels: NotRequired[int]  # The maximum number of frames to return
    format: NotRequired[dict[str, Any]]  # Specifies details on how to format the stack frames


class StackTraceResponseBody(TypedDict):
    stackFrames: list[StackFrame]  # The frames of the stack frame
    totalFrames: NotRequired[int]  # The total number of frames available


class StackTraceRequest(Request):
    """The request returns a stacktrace from the current execution state of a given thread."""

    command: Literal["stackTrace"]
    arguments: StackTraceArguments


class StackTraceResponse(Response):
    """Response to 'stackTrace' request."""

    body: StackTraceResponseBody


# Scopes Request and Response
class ScopesArguments(TypedDict):
    """Arguments for 'scopes' request."""

    frameId: int  # Retrieve the scopes for this stack frame


class ScopesResponseBody(TypedDict):
    scopes: list[Scope]  # The scopes of the stack frame


class ScopesRequest(Request):
    """The request returns the variable scopes for a given stack frame ID."""

    command: Literal["scopes"]
    arguments: ScopesArguments


class ScopesResponse(Response):
    """Response to 'scopes' request."""

    body: ScopesResponseBody


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


class VariablesRequest(Request):
    """Retrieves all child variables for the given variable reference."""

    command: Literal["variables"]
    arguments: VariablesArguments


class VariablesResponse(Response):
    """Response to 'variables' request."""

    body: VariablesResponseBody


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


class SetVariableRequest(Request):
    """Set the variable with the given name in the variable container to a new value."""

    command: Literal["setVariable"]
    arguments: SetVariableArguments


class SetVariableResponse(Response):
    """Response to 'setVariable' request."""

    body: SetVariableResponseBody


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
    presentationHint: NotRequired[dict[str, Any]]  # Properties of the evaluate result
    variablesReference: int  # If > 0 the evaluate result is structured and has children
    namedVariables: NotRequired[int]  # The number of named child variables
    indexedVariables: NotRequired[int]  # The number of indexed child variables
    memoryReference: NotRequired[str]  # Memory reference to a location appropriate for this result


class EvaluateRequest(Request):
    """Evaluates the given expression in the context of the top most frame."""

    command: Literal["evaluate"]
    arguments: EvaluateArguments


class EvaluateResponse(Response):
    """Response to 'evaluate' request."""

    body: EvaluateResponseBody


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
    innerException: NotRequired[list[Self]]


class ExceptionInfoResponseBody(TypedDict):
    exceptionId: str
    description: NotRequired[str]
    breakMode: Literal["always", "unhandled", "userUnhandled", "never"]
    details: NotRequired[ExceptionDetails]


class ExceptionInfoRequest(Request):
    """Retrieves details of the current exception for a thread."""

    command: Literal["exceptionInfo"]
    arguments: ExceptionInfoArguments


class ExceptionInfoResponse(Response):
    """Response to 'exceptionInfo' request."""

    body: ExceptionInfoResponseBody


# SetExceptionBreakpoints Request
class SetExceptionBreakpointsArguments(TypedDict):
    """Arguments for 'setExceptionBreakpoints' request."""

    filters: list[str]  # Set of exception filters specified by their ID
    filterOptions: NotRequired[list[dict[str, Any]]]  # Configuration options for selected exceptions
    exceptionOptions: NotRequired[list[dict[str, Any]]]  # Configuration options for selected exceptions


# Pause Request
class PauseArguments(TypedDict):
    """Arguments for 'pause' request."""

    threadId: int  # Pause execution for this thread


class ModulesArguments(TypedDict):
    """Arguments for 'modules' request."""

    startModule: NotRequired[int]  # The index of the first module to return; if omitted modules start at 0
    moduleCount: NotRequired[int]  # The number of modules to return. If moduleCount is not specified or 0, all modules are returned


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


# Event types
class InitializedEvent(Event):
    """This event indicates that the debug adapter is ready to accept configuration requests."""

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


class StoppedEvent(Event):
    """The event indicates that the execution of the debuggee has stopped."""

    event: Literal["stopped"]
    body: StoppedEventBody


class ExitedEventBody(TypedDict):
    exitCode: int  # The exit code returned from the debuggee


class ExitedEvent(Event):
    """The event indicates that the debuggee has exited."""

    event: Literal["exited"]
    body: ExitedEventBody


class TerminatedEventBody(TypedDict):
    restart: NotRequired[
        Any
    ]  # A debug adapter may set this to true to request that the client restarts the session


class TerminatedEvent(Event):
    """The event indicates that debugging of the debuggee has terminated."""

    event: Literal["terminated"]
    body: NotRequired[TerminatedEventBody]


class ThreadEventBody(TypedDict):
    reason: str  # The reason for the event (started, exited)
    threadId: int  # The identifier of the thread


class ThreadEvent(Event):
    """The event indicates that a thread has started or exited."""

    event: Literal["thread"]
    body: ThreadEventBody


class OutputEventBody(TypedDict):
    category: NotRequired[str]  # The output category
    output: str  # The output to report
    variablesReference: NotRequired[int]  # If > 0, output contains objects which can be retrieved
    source: NotRequired[Source]  # The source location where the output was produced
    line: NotRequired[int]  # The line where the output was produced
    column: NotRequired[int]  # The column where the output was produced


class OutputEvent(Event):
    """The event indicates that the target has produced some output."""

    event: Literal["output"]
    body: OutputEventBody


class BreakpointEventBody(TypedDict):
    reason: str  # The reason for the event (changed, new, removed)
    breakpoint: Breakpoint  # The breakpoint


class BreakpointEvent(Event):
    """The event indicates that some information about a breakpoint has changed."""

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
