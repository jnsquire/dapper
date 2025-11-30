from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from dapper.ipc.connections.base import ConnectionBase

# Expose names for import convenience in tests
__all__ = ["CodeLike", "FrameLike", "MockCode", "MockConnection", "MockFrame"]


class CodeLike(Protocol):
    co_filename: str
    co_firstlineno: int


class FrameLike(Protocol):
    f_code: CodeLike
    f_lineno: int
    f_back: FrameLike | None


@dataclass
class MockCode:
    co_filename: str
    co_firstlineno: int


@dataclass
class MockFrame:
    f_code: MockCode
    f_lineno: int
    f_back: MockFrame | None = None


# Reusable mock connection for server tests
class MockConnection(ConnectionBase):
    """Simple mock connection implementing the minimal ConnectionBase API
    used by tests. Stores incoming messages (queue) and written messages
    for assertions.
    """

    def __init__(self):
        self.messages: list[dict] = []
        self._is_connected = True
        self.closed = False
        self.written_messages: list[dict] = []

    async def accept(self):
        self._is_connected = True

    async def close(self):
        self._is_connected = False
        self.closed = True

    async def read_message(self):
        if not self.messages:
            return None
        return self.messages.pop(0)

    async def write_message(self, message):
        self.written_messages.append(message)

    async def read_dbgp_message(self) -> str | None:
        """Return a stringified version of the next DAP message for DBGP tests."""
        msg = await self.read_message()
        if msg is None:
            return None
        try:
            return json.dumps(msg)
        except Exception:
            return str(msg)

    async def write_dbgp_message(self, message: str) -> None:
        # Store raw DBGP writes separately so tests can assert
        self.written_messages.append({"dbgp": message})

    def add_request(self, command, arguments=None, seq=1):
        req = {"seq": seq, "type": "request", "command": command}
        if arguments:
            req["arguments"] = arguments
        self.messages.append(req)
