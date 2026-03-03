"""Event TypedDict definitions pulled out of the large requests module.

The package-level ``__init__`` imports everything here so client code can
continue using ``from dapper.protocol.requests import InitializedEvent`` etc.
"""

from __future__ import annotations

from typing import Any
from typing import Literal
from typing import TypedDict


class InitializedEvent(TypedDict):
    seq: int
    type: Literal["event"]
    event: Literal["initialized"]


class StoppedEventBody(TypedDict, total=False):
    reason: str
    threadId: int
    allThreadsStopped: bool
    text: str


class StoppedEvent(TypedDict):
    seq: int
    type: Literal["event"]
    event: Literal["stopped"]
    body: StoppedEventBody


class ExitedEvent(TypedDict):
    seq: int
    type: Literal["event"]
    event: Literal["exited"]
    body: dict[str, Any]


class TerminatedEvent(TypedDict, total=False):
    seq: int
    type: Literal["event"]
    event: Literal["terminated"]
    body: dict[str, Any]


class ThreadEvent(TypedDict):
    seq: int
    type: Literal["event"]
    event: Literal["thread"]
    body: dict[str, Any]


class OutputEvent(TypedDict):
    seq: int
    type: Literal["event"]
    event: Literal["output"]
    body: dict[str, Any]


class BreakpointEvent(TypedDict):
    seq: int
    type: Literal["event"]
    event: Literal["breakpoint"]
    body: dict[str, Any]


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
