"""Base class for all connection types."""

from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from typing import Any


class ConnectionBase(ABC):
    """Base class for all connection types."""

    def __init__(self) -> None:
        self.reader = None
        self.writer = None
        self._is_connected = False

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    @is_connected.setter
    def is_connected(self, value: bool) -> None:
        self._is_connected = bool(value)

    @abstractmethod
    async def accept(self) -> None:
        """Accept a client connection."""

    @abstractmethod
    async def close(self) -> None:
        """Close the connection."""

    @abstractmethod
    async def read_message(self) -> dict[str, Any] | None:
        """Read a DAP message from the connection. May return None on EOF."""

    @abstractmethod
    async def read_dbgp_message(self) -> str | None:
        """Read a DBGP-style message from the connection.

        This returns a string payload (decoded UTF-8) for DBGP framed or
        text transports, or None on EOF.
        """

    @abstractmethod
    async def write_dbgp_message(self, message: str) -> None:
        """Write a DBGP-style message (text or binary frame) to the connection."""

    @abstractmethod
    async def write_message(self, message: dict[str, Any]) -> None:
        """Write a DAP message to the connection."""
