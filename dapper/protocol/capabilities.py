"""Adapter capability types and exception-related TypedDicts."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import Literal
from typing import TypedDict

if TYPE_CHECKING:
    from typing_extensions import NotRequired


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
