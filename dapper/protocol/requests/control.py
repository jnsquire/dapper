"""Execution-control requests (continue/step/goto) definitions."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import Literal
from typing import TypedDict

if TYPE_CHECKING:
    from typing_extensions import NotRequired

    from dapper.protocol.structures import Source


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
