"""Runtime-related requests:
threads, loaded sources, variables/stack/etc., exceptions, pause/restart,
hotReload extension.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Literal
from typing import TypedDict

# Exposing the evaluate ResponseBody type is only needed for type checking
if TYPE_CHECKING:
    from typing_extensions import NotRequired

    from dapper.protocol.capabilities import ExceptionBreakpointsFilter
    from dapper.protocol.capabilities import ExceptionFilterOptions
    from dapper.protocol.capabilities import ExceptionOptions
    from dapper.protocol.requests.evaluate import ExceptionInfoResponseBody
    from dapper.protocol.structures import Scope
    from dapper.protocol.structures import Source
    from dapper.protocol.structures import StackFrame
    from dapper.protocol.structures import Thread
    from dapper.protocol.structures import Variable
    from dapper.protocol.structures import VariablePresentationHint


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
    arguments: PauseArguments


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


# ---------------------------------------------------------------------------
# Agent Snapshot (custom extension: dapper/agentSnapshot)
# ---------------------------------------------------------------------------


class AgentSnapshotArguments(TypedDict, total=False):
    """Arguments for the 'dapper/agentSnapshot' request."""

    threadId: int
    # Thread to snapshot. Defaults to the first stopped thread.

    depth: int
    # Maximum number of stack frames to include. Default: 5.

    maxVariables: int
    # Maximum number of variables per scope. Default: 50.

    justMyCode: bool
    # Filter stack frames to user code only. Default: True.


class AgentSnapshotRequest(TypedDict):
    """Request a compact debug state snapshot optimised for LLM consumption."""

    seq: int
    type: Literal["request"]
    command: Literal["dapper/agentSnapshot"]
    arguments: NotRequired[AgentSnapshotArguments]


class AgentStackFrameSummary(TypedDict, total=False):
    """Compact representation of a single stack frame."""

    name: str
    file: str
    line: int
    locals: dict[str, str]
    # Variable name → repr value string, truncated for context efficiency.


class AgentSnapshotResponseBody(TypedDict, total=False):
    """Body of a successful 'dapper/agentSnapshot' response."""

    checkpoint: int
    stopReason: str
    location: str
    callStack: list[AgentStackFrameSummary]
    locals: dict[str, str]
    globals: dict[str, str]
    stoppedThreads: list[int]
    runningThreads: list[int]


class AgentSnapshotResponse(TypedDict):
    """Response to the 'dapper/agentSnapshot' request."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["dapper/agentSnapshot"]
    message: NotRequired[str]
    body: NotRequired[AgentSnapshotResponseBody]


# ---------------------------------------------------------------------------
# Agent Evaluate (custom extension: dapper/agentEval)
# ---------------------------------------------------------------------------


class AgentEvalArguments(TypedDict, total=False):
    """Arguments for the 'dapper/agentEval' request."""

    expression: str
    # A single expression to evaluate.

    expressions: list[str]
    # One or more expressions to evaluate.

    frameIndex: int
    # Stack frame index (0 = topmost). Default: 0.


class AgentEvalRequest(TypedDict):
    """Batch-evaluate expressions, returning compact results."""

    seq: int
    type: Literal["request"]
    command: Literal["dapper/agentEval"]
    arguments: AgentEvalArguments


class AgentEvalResult(TypedDict, total=False):
    """Result of evaluating a single expression."""

    expression: str
    result: str
    type: str
    error: str


class AgentEvalResponseBody(TypedDict):
    """Body of a successful 'dapper/agentEval' response."""

    results: list[AgentEvalResult]


class AgentEvalResponse(TypedDict):
    """Response to the 'dapper/agentEval' request."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["dapper/agentEval"]
    message: NotRequired[str]
    body: NotRequired[AgentEvalResponseBody]


# ---------------------------------------------------------------------------
# Agent Inspect (custom extension: dapper/agentInspect)
# ---------------------------------------------------------------------------


class AgentInspectArguments(TypedDict):
    """Arguments for the 'dapper/agentInspect' request."""

    expression: str
    # Expression to evaluate and deeply inspect.

    depth: NotRequired[int]
    # Max recursion depth for child expansion. Default: 2.

    maxItems: NotRequired[int]
    # Max items per collection/dict. Default: 20.

    frameIndex: NotRequired[int]
    # Stack frame index (0 = topmost). Default: 0.


class AgentInspectRequest(TypedDict):
    """Deep-inspect a variable or expression result."""

    seq: int
    type: Literal["request"]
    command: Literal["dapper/agentInspect"]
    arguments: AgentInspectArguments


class AgentInspectNode(TypedDict, total=False):
    """Recursive tree node for variable inspection."""

    name: str
    type: str
    value: str
    children: list[AgentInspectNode]


class AgentInspectResponseBody(TypedDict, total=False):
    """Body of a successful 'dapper/agentInspect' response."""

    root: AgentInspectNode


class AgentInspectResponse(TypedDict):
    """Response to the 'dapper/agentInspect' request."""

    seq: int
    type: Literal["response"]
    request_seq: int
    success: bool
    command: Literal["dapper/agentInspect"]
    message: NotRequired[str]
    body: NotRequired[AgentInspectResponseBody]
