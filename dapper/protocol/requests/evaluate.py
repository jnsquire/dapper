"""Evaluation-related TypedDicts (evaluate, completions)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Literal
from typing import TypedDict

if TYPE_CHECKING:
    from typing_extensions import NotRequired

    from dapper.protocol.debugger_protocol import ExceptionDetails
    from dapper.protocol.structures import VariablePresentationHint


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


# literal alias and item structure --- kept with evaluation/completions
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
    type: CompletionItemKind
    start: int  # Start position for replacement
    length: int  # Characters to replace


# Completions response wrappers
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
