"""
Connection implementations for the debug adapter (TCP sockets, named pipes).

This module provides two server-side connection implementations used by the
debug adapter: TCPServerConnection and NamedPipeServerConnection. It uses
pathlib.Path for filesystem operations and lazy logging formatting for
better performance.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from abc import ABC
from abc import abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
traffic_logger = logging.getLogger("dapper.connection.traffic")


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


class TCPServerConnection(ConnectionBase):
    """TCP server connection for DAP."""

    def __init__(self, host: str = "localhost", port: int = 4711) -> None:
        super().__init__()
        self.host = host
        self.port = port
        self.server = None

    async def accept(self) -> None:
        logger.info("Starting TCP server on %s:%s", self.host, self.port)
        self.server = await asyncio.start_server(self._handle_client, self.host, self.port)

        # Update the port to the actual bound port in case an ephemeral port
        # (port=0) was requested. This makes the object reflect the real
        # listening port after start_server returns.
        srv = self.server
        if srv is not None and getattr(srv, "sockets", None):
            try:
                bound = srv.sockets[0].getsockname()
                # getsockname() typically returns (host, port)
                self.port = bound[1]
            except Exception:
                # Be conservative: if the socket shape is unexpected, leave
                # the configured port unchanged.
                logger.debug("Unable to determine bound port from server sockets")

        # Wait for the first client to connect; fulfilled in _handle_client
        self._client_connected = asyncio.Future()
        await self._client_connected

        logger.info(
            "Client connected to TCP server on %s:%s",
            self.host,
            self.port,
        )
        self._is_connected = True

    async def start_listening(self) -> None:
        """Start the TCP server listening without waiting for a client.

        This allows tests to obtain the bound ephemeral port before a client
        connects (avoiding polling of internal state during a blocking accept).
        """
        logger.info("Starting TCP server on %s:%s", self.host, self.port)
        self.server = await asyncio.start_server(self._handle_client, self.host, self.port)

        # Prepare future to be fulfilled when first client connects.
        self._client_connected = asyncio.Future()

        # Update self.port if an ephemeral port was chosen.
        srv = getattr(self, "server", None)
        if srv is not None and getattr(srv, "sockets", None):
            try:
                bound = srv.sockets[0].getsockname()
                self.port = bound[1]
            except Exception:  # pragma: no cover - defensive
                logger.debug("Unable to determine bound port from server sockets")

    async def wait_for_client(self) -> None:
        """Wait until a client connects (after start_listening)."""
        if not hasattr(self, "_client_connected"):
            msg = "wait_for_client called before start_listening"
            raise RuntimeError(msg)
        await self._client_connected
        logger.info(
            "Client connected to TCP server on %s:%s",
            self.host,
            self.port,
        )
        self._is_connected = True

    async def _handle_client(self, reader, writer) -> None:
        """Handle a new client connection."""
        self.reader = reader
        self.writer = writer
        if not self._client_connected.done():
            self._client_connected.set_result(True)

    async def close(self) -> None:
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()

        if self.server:
            self.server.close()
            await self.server.wait_closed()

        self._is_connected = False
        logger.info("TCP connection closed")

    async def read_message(self) -> dict[str, Any] | None:
        """Read a DAP message from the TCP connection using Content-Length."""
        if not self.reader:
            msg = "No active connection"
            raise RuntimeError(msg)

        headers: dict[str, str] = {}

        # Read headers
        while True:
            line = await self.reader.readline()
            if not line:
                return None  # Connection closed

            line = line.decode("utf-8").strip()
            if not line:
                break

            key, value = line.split(":", 1)
            headers[key.strip()] = value.strip()

        if "Content-Length" not in headers:
            msg = "Content-Length header missing"
            raise RuntimeError(msg)

        content_length = int(headers["Content-Length"])
        content = await self.reader.readexactly(content_length)
        if not content:
            return None

        message = json.loads(content.decode("utf-8"))
        logger.debug("Received message: %s", message)
        return message

    async def write_message(self, message: dict[str, Any]) -> None:
        """Write a DAP message to the TCP connection."""
        if not self.writer:
            msg = "No active connection"
            raise RuntimeError(msg)

        content = json.dumps(message).encode("utf-8")
        header = f"Content-Length: {len(content)}\r\n\r\n".encode()

        self.writer.write(header + content)
        await self.writer.drain()
        logger.debug("Sent message: %s", message)

    def __del__(self):  # pragma: no cover - best-effort cleanup
        # Ensure underlying server socket is closed if user forgot.
        try:
            srv = getattr(self, "server", None)
            if srv is not None:
                srv.close()
        except Exception:
            pass


class NamedPipeServerConnection(ConnectionBase):
    """Named pipe server connection for DAP."""

    def __init__(self, pipe_name: str) -> None:
        super().__init__()
        self.pipe_name = pipe_name
        self.pipe_path = self._get_pipe_path(pipe_name)
        self.server = None
        self._awaiting_connection_event: asyncio.Event | None = None

    def _get_pipe_path(self, name: str) -> str:
        return rf"\\.\pipe\{name}" if sys.platform == "win32" else f"/tmp/{name}"

    async def accept(self) -> None:
        logger.info("Creating named pipe at %s", self.pipe_path)
        self._awaiting_connection_event = asyncio.Event()

        if sys.platform == "win32":
            self.server = await asyncio.start_server(self._handle_client, path=self.pipe_path)
        else:
            # Ensure old pipe doesn't exist
            p = Path(self.pipe_path)
            if p.exists():
                p.unlink()

            os.mkfifo(self.pipe_path)

            loop = asyncio.get_event_loop()

            def open_pipe() -> object:
                fd = os.open(self.pipe_path, os.O_RDWR)
                return os.fdopen(fd, "r+b")

            self.pipe_file = await loop.run_in_executor(None, open_pipe)

            # Create streams from the file
            self.reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(self.reader)

            transport, _ = await loop.connect_read_pipe(lambda: protocol, self.pipe_file)
            self.writer = asyncio.StreamWriter(transport, protocol, self.reader, loop)

            self._is_connected = True
            self._awaiting_connection_event.set()

        await self._awaiting_connection_event.wait()
        logger.info("Client connected to named pipe at %s", self.pipe_path)

    async def _handle_client(self, reader, writer) -> None:
        self.reader = reader
        self.writer = writer
        self._is_connected = True
        if self._awaiting_connection_event:
            self._awaiting_connection_event.set()
            self._awaiting_connection_event = None

    async def close(self) -> None:
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()

        if self.server:
            self.server.close()
            await self.server.wait_closed()

        if sys.platform != "win32":
            p = Path(self.pipe_path)
            if p.exists():
                p.unlink()

        self._is_connected = False
        logger.info("Named pipe connection closed")

    async def read_message(self) -> dict[str, Any] | None:
        if not self.reader:
            msg = "No active connection"
            raise RuntimeError(msg)

        headers: dict[str, str] = {}
        while True:
            line = await self.reader.readline()
            if not line:
                return None

            line = line.decode("utf-8").strip()
            if not line:
                break

            key, value = line.split(":", 1)
            headers[key.strip()] = value.strip()

        content_len_header = headers.get("Content-Length")
        if content_len_header is None:
            msg = "Content-Length header missing"
            raise RuntimeError(msg)

        try:
            content_length = int(content_len_header)
        except ValueError as err:
            msg = f"Malformed Content-Length header: {content_len_header!r}"
            raise RuntimeError(msg) from err

        content = await self.reader.readexactly(content_length)
        if not content:
            return None

        message = json.loads(content.decode("utf-8"))
        traffic_logger.debug("Received message: %s", message)
        return message

    async def write_message(self, message: dict[str, Any]) -> None:
        if not self.writer:
            msg = "No active connection"
            raise RuntimeError(msg)

        content = json.dumps(message).encode("utf-8")
        self.writer.write(f"Content-Length: {len(content)}\r\n\r\n".encode())
        self.writer.write(content)
        await self.writer.drain()
        traffic_logger.debug("Sent message: %s", message)
