"""All request/response and event TypedDicts used by the DAP; grouped here now
that smaller structural types are in `structures.py` and capabilities / data
breakpoints are in their own modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import Literal
from typing import TypedDict

if TYPE_CHECKING:
    from typing_extensions import NotRequired

    from dapper.protocol.capabilities import Capabilities
    from dapper.protocol.capabilities import ExceptionBreakpointsFilter
    from dapper.protocol.capabilities import ExceptionFilterOptions
    from dapper.protocol.capabilities import ExceptionOptions
    from dapper.protocol.debugger_protocol import ExceptionDetails
    from dapper.protocol.structures import Breakpoint
    from dapper.protocol.structures import Scope
    from dapper.protocol.structures import Source
    from dapper.protocol.structures import SourceBreakpoint
    from dapper.protocol.structures import StackFrame
    from dapper.protocol.structures import Thread
    from dapper.protocol.structures import Variable
    from dapper.protocol.structures import VariablePresentationHint


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


class LaunchRequestArguments(TypedDict, total=False):
    """Arguments for the `launch` request.

    DAP spec allows implementation-specific fields; make the common fields
    optional so clients can supply only the subset they need. Also include
    commonly-used adapter-level extensions as NotRequired fields so tests / callers using either
    naming style type-check correctly.
    """

    program: str
    module: NotRequired[str]
    moduleSearchPaths: NotRequired[list[str]]
    venvPath: NotRequired[str]
    args: NotRequired[list[str]]
    noDebug: NotRequired[bool]
    __restart: NotRequired[Any]

    # adapter-specific optional fields (camelCase only)
    stopOnEntry: NotRequired[bool]
    inProcess: NotRequired[bool]
    useBinaryIpc: NotRequired[bool]
    ipcTransport: NotRequired[str]
    ipcPipeName: NotRequired[str]
    cwd: NotRequired[str]
    env: NotRequired[dict[str, str]]


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
class AttachRequestArguments(TypedDict, total=False):
    """Arguments for the `attach` request.

    DAP spec allows implementation-specific fields; adapter may include
    IPC configuration fields (all optional via total=False).
    """

    __restart: NotRequired[Any]

    # adapter-specific IPC fields (camelCase only)
    ipcTransport: NotRequired[str]
    ipcHost: NotRequired[str]
    ipcPort: NotRequired[int]
    ipcPath: NotRequired[str]
    ipcPipeName: NotRequired[str]
    useBinaryIpc: NotRequired[bool]


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


# Evaluate
class EvaluateArguments(TypedDict):
    expression: str
    frameId: NotRequired[int]
    context: NotRequired[str]


class EvaluateResponseBody(TypedDict, total=False):
    result: str
    type: NotRequired[str]
    variablesReference: NotRequired[int]
    presentationHint: NotRequired[VariablePresentationHint]
    namedVariables: NotRequired[int]
    indexedVariables: NotRequired[int]
    memoryReference: NotRequired[str]


class ExceptionInfoResponseBody(TypedDict, total=False):
    exceptionId: NotRequired[str]
    description: NotRequired[str]
    breakMode: NotRequired[str]
    details: NotRequired[ExceptionDetails]


# Evaluate request/response wrappers
class EvaluateRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["evaluate"]
    arguments: EvaluateArguments


class EvaluateResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["evaluate"]
    message: NotRequired[str]
    body: NotRequired[EvaluateResponseBody]


# Completions request/response
class CompletionsArguments(TypedDict):
    """Arguments for 'completions' request."""

    text: str  # The text to complete
    column: int  # Cursor position within text (UTF-16 code units)
    frameId: NotRequired[int]  # Optional frame for scope context
    line: NotRequired[int]  # Line number (defaults to 1 if multi-line text)


class CompletionItemType(TypedDict, total=False):
    """Type of completion item - used for icon hints in clients."""

    # Enum values are handled as string literals


# Literal alias for the completion item 'type' field so callers can import
# a reusable type instead of repeating the long Literal[...] expression.
CompletionItemKind = Literal[
    "method",
    "function",
    "constructor",
    "field",
    "variable",
    "class",
    "interface",
    "module",
    "property",
    "unit",
    "value",
    "enum",
    "keyword",
    "snippet",
    "text",
    "color",
    "file",
    "reference",
    "customcolor",
]


class CompletionItem(TypedDict, total=False):
    """A single completion suggestion."""

    label: str  # Required: display text (also inserted if no `text`)
    text: str  # Text to insert (if different from label)
    sortText: str  # Sort key (defaults to label)
    detail: str  # Additional info (e.g., type signature)
    type: Literal[
        "method",
        "function",
        "constructor",
        "field",
        "variable",
        "class",
        "interface",
        "module",
        "property",
        "unit",
        "value",
        "enum",
        "keyword",
        "snippet",
        "text",
        "color",
        "file",
        "reference",
        "customcolor",
    ]
    start: int  # Start position for replacement
    length: int  # Characters to replace


class CompletionsResponseBody(TypedDict):
    """Body of completions response."""

    targets: list[CompletionItem]


class CompletionsRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["completions"]
    arguments: CompletionsArguments


class CompletionsResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["completions"]
    message: NotRequired[str]
    body: NotRequired[CompletionsResponseBody]


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


# GotoTargets
class GotoTargetsArguments(TypedDict):
    source: Source
    line: int
    column: NotRequired[int]
    endLine: NotRequired[int]
    endColumn: NotRequired[int]
    frameId: NotRequired[int]


class GotoTarget(TypedDict):
    id: int
    label: str
    line: int
    column: NotRequired[int]
    endLine: NotRequired[int]
    endColumn: NotRequired[int]
    instructionPointerReference: NotRequired[str]


class GotoTargetsRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["gotoTargets"]
    arguments: GotoTargetsArguments


class GotoTargetsResponseBody(TypedDict):
    targets: list[GotoTarget]


class GotoTargetsResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["gotoTargets"]
    message: NotRequired[str]
    body: NotRequired[GotoTargetsResponseBody]


# Goto
class GotoArguments(TypedDict):
    threadId: int
    targetId: int


class GotoRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["goto"]
    arguments: GotoArguments


class GotoResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["goto"]
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


# Module representation used by modules/loadedSources responses
class Module(TypedDict):
    id: str
    name: str
    isUserCode: bool
    path: NotRequired[str]


# LoadedSources / Modules / ModuleSource
class LoadedSourcesRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["loadedSources"]


class LoadedSourcesResponseBody(TypedDict):
    sources: list[Source]


class LoadedSourcesResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["loadedSources"]
    message: NotRequired[str]
    body: NotRequired[LoadedSourcesResponseBody]


class ModulesRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["modules"]


class ModulesResponseBody(TypedDict):
    modules: list[Module]


class ModulesResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["modules"]
    message: NotRequired[str]
    body: NotRequired[ModulesResponseBody]


class ModuleSourceArguments(TypedDict):
    module_id: str


class ModuleSourceRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["moduleSource"]
    arguments: ModuleSourceArguments


class ModuleSourceResponseBody(TypedDict):
    content: str
    mimeType: NotRequired[str]


class ModuleSourceResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["moduleSource"]
    message: NotRequired[str]
    body: NotRequired[ModuleSourceResponseBody]


# Variables/Stack/Evaluate/SetVariable responses
class VariablesResponseBody(TypedDict):
    variables: list[Variable]
    totalVariables: NotRequired[int]


class SetVariableResponseBody(TypedDict):
    value: str
    type: NotRequired[str]
    variablesReference: NotRequired[int]


class SetExpressionResponseBody(TypedDict):
    value: str
    type: NotRequired[str]
    presentationHint: NotRequired[VariablePresentationHint]
    variablesReference: NotRequired[int]
    namedVariables: NotRequired[int]
    indexedVariables: NotRequired[int]


class StackTraceResponseBody(TypedDict):
    stackFrames: list[StackFrame]
    totalFrames: NotRequired[int]


class StackTraceArguments(TypedDict):
    threadId: int
    startFrame: NotRequired[int]
    levels: NotRequired[int]
    format: NotRequired[str]


# StackTrace requests
class StackTraceRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["stackTrace"]
    arguments: StackTraceArguments


class StackTraceResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["stackTrace"]
    message: NotRequired[str]
    body: NotRequired[StackTraceResponseBody]


class VariablesArguments(TypedDict):
    variablesReference: int
    filter: NotRequired[str]
    start: NotRequired[int]
    count: NotRequired[int]


# Variables
class VariablesRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["variables"]
    arguments: VariablesArguments


class VariablesResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["variables"]
    message: NotRequired[str]
    body: NotRequired[VariablesResponseBody]


class ScopesArguments(TypedDict):
    frameId: int


# Scopes
class ScopesRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["scopes"]
    arguments: ScopesArguments


class ScopesResponseBody(TypedDict):
    scopes: list[Scope]


class ScopesResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["scopes"]
    message: NotRequired[str]
    body: NotRequired[ScopesResponseBody]


class SetVariableArguments(TypedDict):
    variablesReference: int
    name: str
    value: str
    format: NotRequired[str]


# SetVariable
class SetVariableRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["setVariable"]
    arguments: SetVariableArguments


class SetVariableResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["setVariable"]
    message: NotRequired[str]
    body: NotRequired[SetVariableResponseBody]


class SetExpressionArguments(TypedDict):
    expression: str
    value: str
    frameId: NotRequired[int]
    format: NotRequired[str]


class SetExpressionRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["setExpression"]
    arguments: SetExpressionArguments


class SetExpressionResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["setExpression"]
    message: NotRequired[str]
    body: NotRequired[SetExpressionResponseBody]


class SourceArguments(TypedDict):
    source: NotRequired[Source]
    sourceReference: NotRequired[int]


# Source request/response
class SourceRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["source"]
    arguments: SourceArguments


class SourceResponseBody(TypedDict):
    content: str
    mimeType: NotRequired[str]


class SourceResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["source"]
    message: NotRequired[str]
    body: NotRequired[SourceResponseBody]


# Exception breakpoints (response wrapper)
class SetExceptionBreakpointsResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["setExceptionBreakpoints"]
    message: NotRequired[str]
    body: NotRequired[list[ExceptionBreakpointsFilter]]


# Arguments for setExceptionBreakpoints
class SetExceptionBreakpointsArguments(TypedDict):
    filters: list[str]
    filterOptions: NotRequired[list[ExceptionFilterOptions]]
    exceptionOptions: NotRequired[list[ExceptionOptions]]


class SetExceptionBreakpointsRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["setExceptionBreakpoints"]
    arguments: SetExceptionBreakpointsArguments


# Exception info request/response wrappers
class ExceptionInfoArguments(TypedDict):
    threadId: int


class ExceptionInfoRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["exceptionInfo"]
    arguments: ExceptionInfoArguments


class ExceptionInfoResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["exceptionInfo"]
    message: NotRequired[str]
    body: NotRequired[ExceptionInfoResponseBody]


# Pause / Restart request/response shapes
class PauseArguments(TypedDict):
    threadId: int


class PauseRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["pause"]
    arguments: PauseArguments


class PauseResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["pause"]
    message: NotRequired[str]


class RestartRequest(TypedDict):
    seq: int
    type: Literal["request"]
    command: Literal["restart"]


class RestartResponse(TypedDict):
    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["restart"]
    message: NotRequired[str]


# ---------------------------------------------------------------------------
# Hot Reload (custom extension: dapper/hotReload)
# ---------------------------------------------------------------------------


class HotReloadOptions(TypedDict, total=False):
    """Per-request behaviour overrides for the 'dapper/hotReload' request.

    All fields are optional; omitting the options block entirely is
    equivalent to accepting every default listed below.
    """

    rebindFrameLocals: bool
    # Default: True.
    # Scan every live stack frame on stopped threads and replace
    # references to old function objects with the reloaded versions.
    # Set to False to apply the reload for future calls only.

    updateFrameCode: bool
    # Default: True (CPython ≥ 3.12); silently ignored on older runtimes.
    # Attempt to assign frame.f_code when the new code object is
    # structurally compatible (same co_varnames, co_freevars, co_argcount).
    # A warning is added to the response for each incompatible frame.

    patchClassInstances: bool
    # Default: False.  Experimental.
    # For every live instance whose __class__.__module__ matches the
    # reloaded module, update __class__ to the new class object.
    # Skipped silently for classes that use __slots__.

    invalidatePycache: bool
    # Default: True.
    # Delete the matching __pycache__/*.pyc file before calling
    # importlib.reload() to guarantee that fresh bytecode is compiled.


class HotReloadArguments(TypedDict):
    """Arguments for the 'dapper/hotReload' request."""

    source: Source
    # The source file to reload.  The 'path' field is required;
    # 'sourceReference' is ignored (reload always uses the file system).

    options: NotRequired[HotReloadOptions]
    # Optional behaviour overrides.  Omit to accept all defaults.


class HotReloadRequest(TypedDict):
    """Request to reload a Python module during a paused debug session."""

    seq: int
    type: Literal["request"]
    command: Literal["dapper/hotReload"]
    arguments: HotReloadArguments


class HotReloadResponseBody(TypedDict, total=False):
    """Body of a successful 'dapper/hotReload' response."""

    reloadedModule: str
    # Fully-qualified name of the module that was reloaded
    # (e.g. "mypackage.utils").

    reloadedPath: str
    # Absolute path of the file that was reloaded.

    reboundFrames: int
    # Number of live stack frames whose locals were rebound.
    # 0 when rebindFrameLocals is False or no matching frames existed.

    updatedFrameCodes: int
    # Number of frames whose f_code was successfully reassigned.
    # Always 0 on CPython < 3.12.

    patchedInstances: int
    # Number of live instances whose __class__ was patched.
    # Always 0 when patchClassInstances is False.

    warnings: list[str]
    # Non-fatal diagnostic messages explaining skipped or degraded steps.


class HotReloadResponse(TypedDict):
    """Response to the 'dapper/hotReload' request."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["dapper/hotReload"]
    message: NotRequired[str]
    body: NotRequired[HotReloadResponseBody]


class HotReloadResultEventBody(TypedDict, total=False):
    """Body of the 'dapper/hotReloadResult' event.

    Emitted after a successful reload to let clients update the debug
    console, status bar, or telemetry without correlating request/response
    pairs.  Fields mirror HotReloadResponseBody plus a timing field.
    """

    module: str
    path: str
    reboundFrames: int
    updatedFrameCodes: int
    patchedInstances: int
    warnings: list[str]
    durationMs: float
    # Wall-clock duration of the entire reload operation in milliseconds.


class HotReloadResultEvent(TypedDict):
    """Event emitted after a successful hot reload."""

    seq: int
    type: Literal["event"]
    event: Literal["dapper/hotReloadResult"]
    body: HotReloadResultEventBody
