"""NamedPipeServerConnection implementation moved from dapper.ipc.connections."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
import sys
from typing import Any

from dapper.ipc.connections.base import ConnectionBase
from dapper.ipc.ipc_binary import HEADER_SIZE
from dapper.ipc.ipc_binary import pack_frame
from dapper.ipc.ipc_binary import unpack_header

logger = logging.getLogger(__name__)
traffic_logger = logging.getLogger("dapper.connection.traffic")


class NamedPipeServerConnection(ConnectionBase):
    """Named pipe server connection for DAP."""

    def __init__(self, pipe_name: str) -> None:
        super().__init__()
        self.pipe_name = pipe_name
        self.pipe_path = self._get_pipe_path(pipe_name)
        self.server = None
        self._awaiting_connection_event: asyncio.Event | None = None
        # For sync path we may create a low-level file descriptor wrapper
        # attached as pipe_file (set in accept()). Declare attribute here
        # for static analysis and clarity.
        self.pipe_file: Any | None = None
        # Whether DBGP frames are exchanged in binary mode (header+payload)
        self.use_binary = False

    def _get_pipe_path(self, name: str) -> str:
        return rf"\\.\pipe\{name}" if sys.platform == "win32" else f"/tmp/{name}"

    async def accept(self) -> None:
        logger.info("Creating named pipe at %s", self.pipe_path)
        self._awaiting_connection_event = asyncio.Event()

        if sys.platform == "win32":
            # FIXME On Windows, named pipes work differently - we need to use the proactor event loop
            # For now, we'll create a dummy server since the actual pipe handling is done differently
            # The real Windows named pipe implementation would use overlapped I/O
            logger.warning(
                "Windows named pipe server creation not fully implemented - using fallback"
            )
            self.server = None
            # Set up a mock connection state for compatibility
            self._is_connected = True
            if self._awaiting_connection_event:
                self._awaiting_connection_event.set()
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

            # Create read stream
            self.reader = asyncio.StreamReader()
            read_protocol = asyncio.StreamReaderProtocol(self.reader)
            _read_transport, _ = await loop.connect_read_pipe(
                lambda: read_protocol, self.pipe_file
            )  # type: ignore[arg-type]

            # Create write stream
            write_transport, write_protocol = await loop.connect_write_pipe(
                asyncio.Protocol, self.pipe_file
            )  # type: ignore[arg-type]
            self.writer = asyncio.StreamWriter(write_transport, write_protocol, self.reader, loop)

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
            try:
                await self.server.wait_closed()  # type: ignore[misc]
            except RuntimeError:
                # Server may not be properly initialized on Windows
                pass

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

    async def read_dbgp_message(self) -> str | None:
        """Read a DBGP-style message from the named pipe connection.

        For binary listeners, the pipe receives raw frames via the file-like
        interface; for text mode the implementation reads DBGP-prefixed strings.
        """
        # For the pipe implementation we expose similar behaviour as the
        # TCP connection. The implementation varies by platform and internal
        # state; use the existing reader when available.
        if not hasattr(self, "reader") or self.reader is None:
            return None

        try:
            line = await self.reader.readline()
        except Exception:
            return None

        if not line:
            return None

        message_text: str | None = None

        if isinstance(line, bytes):
            # Try parsing a binary header first (fast path checks magic)
            if len(line) >= HEADER_SIZE and line[:2] == b"DP":
                try:
                    kind, length = unpack_header(line[:HEADER_SIZE])
                    if kind == 1:
                        payload = line[HEADER_SIZE : HEADER_SIZE + length]
                        return payload.decode("utf-8")
                except Exception:
                    # fall through and attempt to decode whole buffer
                    pass

            # fallback: try to decode whole bytes
            try:
                message_text = line.decode("utf-8").strip()
            except Exception:
                message_text = None
        else:
            message_text = str(line).strip()

        if message_text and message_text.startswith("DBGP:"):
            return message_text[5:].strip()

        return None

    async def write_dbgp_message(self, message: str) -> None:
        """Write a DBGP-style message (text line or binary framed) to client."""
        if not getattr(self, "writer", None) and not getattr(self, "pipe_file", None):
            raise RuntimeError("No active connection")

        if self.use_binary:
            content = message.encode("utf-8")
            header = pack_frame(2, content)
            payload = header + content
            if getattr(self, "writer", None):
                self.writer.write(payload)
                await self.writer.drain()
            else:
                pf = self.pipe_file
                assert pf is not None
                pf.write(payload)
                pf.flush()
        else:
            data = f"DBGP: {message}\n".encode()
            if getattr(self, "writer", None):
                self.writer.write(data)
                await self.writer.drain()
            else:
                pf = self.pipe_file
                assert pf is not None
                pf.write(data)
                pf.flush()

    async def write_message(self, message: dict[str, Any]) -> None:
        """Write a DAP message to the named pipe connection."""
        if not getattr(self, "writer", None) and not getattr(self, "pipe_file", None):
            raise RuntimeError("No active connection")

        content = json.dumps(message).encode("utf-8")
        header = f"Content-Length: {len(content)}\r\n\r\n".encode()
        payload = header + content

        if getattr(self, "writer", None):
            self.writer.write(payload)
            await self.writer.drain()
        else:
            pf = self.pipe_file
            assert pf is not None
            pf.write(payload)
            pf.flush()

        logger.debug("Sent message: %s", message)
