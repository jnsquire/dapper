"""TCPServerConnection implementation for DAP protocol over TCP."""

from __future__ import annotations

import asyncio
import json
import logging
import socket
from typing import Any

from dapper.ipc.connections.base import ConnectionBase
from dapper.ipc.ipc_binary import pack_frame
from dapper.ipc.ipc_binary import unpack_header

logger = logging.getLogger(__name__)


class TCPServerConnection(ConnectionBase):
    """TCP server connection for DAP protocol.

    This class implements a TCP server that listens for incoming DAP client
    connections. It supports both normal operation and test scenarios where
    the bound port needs to be known before clients connect.
    """

    def __init__(self, host: str|None = None, port: int|None = None) -> None:
        """Initialize the TCP server connection.

        Args:
            host: The host address to bind to. Defaults to localhost.
            port: The port to bind to. Use 0 for an ephemeral port.
        """
        super().__init__()
        self.host = host or "localhost"
        self.port = 4711 if port is None else port
        self.server: asyncio.Server | None = None
        self._client_connected: asyncio.Future[bool] | None = None
        self.use_binary = False  # Default to regular DAP protocol
        self.socket: Any = None  # For backward compatibility

    async def accept(self) -> None:
        """Start listening and wait for the first client to connect.

        If start_listening() was already called, this method reuses the
        existing server socket and only waits for a client.
        """
        if self.server is None:
            await self.start_listening()
 
        await self.wait_for_client()

    async def start_listening(self) -> None:
        """Start the TCP server listening without waiting for a client.

        This allows tests to obtain the bound ephemeral port before a client
        connects (avoiding polling of internal state during a blocking accept).
        """
        if self.server is not None:
            logger.warning("Server already listening on %s:%s", self.host, self.port)
            return

        logger.info("Starting TCP server on %s:%s", self.host, self.port)
        
        # If we have a pre-created socket (from TransportFactory), use it
        if hasattr(self, "socket") and self.socket is not None:
            logger.debug("Using pre-created socket")
            self.server = await asyncio.start_server(
                self._handle_client, sock=self.socket, reuse_address=True
            )
        else:
            logger.debug("Creating new socket")
            self.server = await asyncio.start_server(
                self._handle_client, self.host, self.port, reuse_address=True
            )
        
        self._client_connected = asyncio.Future()
        self._update_bound_port()

    def _update_bound_port(self) -> None:
        """Update the bound port from the server socket.

        This is particularly useful when using an ephemeral port (port=0).
        """
        if self.server is None or not self.server.sockets:
            return

        try:
            sock = self.server.sockets[0]
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                _, port = sock.getsockname()[:2]
                if port != self.port:
                    logger.debug(
                        "Server bound to ephemeral port %d (requested: %d)", port, self.port
                    )
                    self.port = port
        except (IndexError, OSError) as e:
            logger.debug("Could not determine bound port: %s", e)

    async def wait_for_client(self, timeout: float | None = None) -> None:
        """Wait until a client connects (after start_listening).

        Args:
            timeout: Optional timeout in seconds to wait for a client connection.

        Raises:
            RuntimeError: If called before start_listening
            asyncio.TimeoutError: If timeout is reached before a client connects
        """
        logger.debug("wait_for_client() called, _client_connected=%s", self._client_connected)
        if self._client_connected is None:
            raise RuntimeError("wait_for_client called before start_listening")

        try:
            logger.debug("Starting wait for client connection...")
            await asyncio.wait_for(asyncio.shield(self._client_connected), timeout=timeout)
            logger.info("Client connected to TCP server on %s:%s", self.host, self.port)
            self._is_connected = True
        except asyncio.TimeoutError:
            logger.warning(
                "Timed out waiting for client connection on %s:%s", self.host, self.port
            )
            raise

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handle a new client connection."""
        logger.debug("TCP client connected")
        self.reader = reader
        self.writer = writer
        self._is_connected = True
        
        # Signal that client is connected
        if self._client_connected:
            self._client_connected.set_result(True)
            self._client_connected = None

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
        """Read a DAP message from the TCP connection."""
        if not self.reader:
            msg = "No active connection"
            raise RuntimeError(msg)

        if self.use_binary:
            return await self._read_binary_message()
        
        return await self._read_dap_message()

    async def _read_binary_message(self) -> dict[str, Any] | None:
        """Read a binary frame message."""
        logger.debug("Reading binary frame...")
        # Read header first
        header_data = await self.reader.readexactly(8)
        if not header_data:
            logger.debug("No header data received")
            return None  # Connection closed

        try:
            kind, length = unpack_header(header_data)
            logger.debug("Binary frame: kind=%d, length=%d", kind, length)
        except ValueError:
            logger.exception("Failed to unpack binary header")
            return None

        # Read payload
        if length == 0:
            payload = b""
        else:
            payload = await self.reader.readexactly(length)
            if not payload:
                logger.debug("No payload data received")
                return None

        # Parse JSON payload
        try:
            message = json.loads(payload.decode("utf-8"))
            logger.debug("Received binary message: %s", message)
        except json.JSONDecodeError:
            logger.exception("Failed to decode binary message JSON")
            return None
        else:
            return message

    async def read_dbgp_message(self) -> str | None:
        """Read a DBGP-style message from the TCP connection.

        For binary-mode, read the DBGP header and return payload decoded as UTF-8
        for frames with kind==1. For text-mode read a line and strip the DBGP
        prefix if present.
        """
        if not self.reader:
            raise RuntimeError("No active connection")

        result: str | None = None

        if self.use_binary:
            # Read header
            header_data = None
            try:
                header_data = await self.reader.readexactly(8)
            except Exception:
                header_data = None

            if header_data:
                try:
                    kind, length = unpack_header(header_data)
                except Exception:
                    kind = None
                    length = 0

                if kind is not None:
                    payload = None
                    try:
                        payload = await self.reader.readexactly(length)
                    except Exception:
                        payload = None

                    if payload and kind == 1:
                        try:
                            result = payload.decode("utf-8")
                        except Exception:
                            result = None

        else:
            # text-mode
            line = await self.reader.readline()
            if line:
                line = line.decode("utf-8").strip()
                if line.startswith("DBGP:"):
                    result = line[5:].strip()

        return result

    async def _read_dap_message(self) -> dict[str, Any] | None:
        """Read a regular DAP protocol message with Content-Length headers."""
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

    async def write_dbgp_message(self, message: str) -> None:
        """Write a DBGP-style message (text line or binary framed) to client."""
        if not self.writer:
            raise RuntimeError("No active connection")

        if self.use_binary:
            content = message.encode("utf-8")
            header = pack_frame(2, content)
            # write raw bytes
            self.writer.write(header + content)
            await self.writer.drain()
        else:
            # write DBGP line
            self.writer.write(f"DBGP: {message}\n".encode())
            await self.writer.drain()

    def __del__(self):  # pragma: no cover - best-effort cleanup
        # Ensure underlying server socket is closed if user forgot.
        try:
            srv = getattr(self, "server", None)
            if srv is not None:
                srv.close()
        except Exception:
            pass
