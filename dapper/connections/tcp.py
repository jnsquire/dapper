"""TCPServerConnection implementation moved from dapper.connection."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from dapper.connections import ConnectionBase

logger = logging.getLogger(__name__)


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
