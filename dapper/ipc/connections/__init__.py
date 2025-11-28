"""dapper.connections package

Expose ConnectionBase at package level; other connection implementations
live in submodules to keep a tidy layout.
"""

from __future__ import annotations

import logging
from abc import ABC
from abc import abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


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
    async def write_message(self, message: dict[str, Any]) -> None:
        """Write a DAP message to the connection."""


async def create_connection(
    connection_type: str,
    host: str = "localhost",
    port: int | None = None,
    pipe_name: str | None = None,
) -> ConnectionBase | None:
    """Factory function to create a connection based on type.

    Args:
        connection_type: Either "tcp" or "pipe"
        host: Host to connect to (for TCP connections)
        port: Port number (for TCP connections)
        pipe_name: Named pipe name (for pipe connections)

    Returns:
        A ConnectionBase instance or None if the connection type is unknown.
    """
    # Import here to avoid circular imports at module load time
    from dapper.ipc.connections.pipe import NamedPipeServerConnection
    from dapper.ipc.connections.tcp import TCPServerConnection

    if connection_type == "tcp":
        return TCPServerConnection(host=host, port=port or 4711)
    elif connection_type == "pipe":
        if pipe_name is None:
            pipe_name = "dapper_debug_pipe"
        return NamedPipeServerConnection(pipe_name=pipe_name)
    else:
        logger.error("Unknown connection type: %s", connection_type)
        return None
