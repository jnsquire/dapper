"""Initialize and session-related request/response TypedDicts.

This module is auto-split from the monolithic ``requests`` file so that the
codebase remains navigable.  The public API remains the same; the
package-level ``__init__`` imports everything here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import Literal
from typing import TypedDict

# Bring in RequestLike so our request types can implement the protocol


if TYPE_CHECKING:
    from typing_extensions import NotRequired

    from dapper.protocol.capabilities import Capabilities


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
