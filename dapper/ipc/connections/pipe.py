"""NamedPipeServerConnection implementation moved from dapper.ipc.connections."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from dapper.ipc.connections.base import ConnectionBase

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
