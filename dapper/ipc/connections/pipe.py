"""NamedPipeServerConnection implementation moved from dapper.ipc.connections."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from multiprocessing import connection as mp_conn
import os
from pathlib import Path
import sys
from typing import Any

from dapper.ipc.connections.base import ConnectionBase
from dapper.ipc.ipc_binary import pack_frame

# Binary frame kind for adapter→launcher commands
_KIND_COMMAND = 2

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
        # Windows named-pipe endpoints managed via multiprocessing.connection
        self.listener: mp_conn.Listener | None = None
        self.client: mp_conn.Connection | None = None
        self._pipe_conn: mp_conn.Connection | None = None

    def _get_pipe_path(self, name: str) -> str:
        return rf"\\.\pipe\{name}" if sys.platform == "win32" else f"/tmp/{name}"

    async def accept(self) -> None:
        logger.info("Creating named pipe at %s", self.pipe_path)
        self._awaiting_connection_event = asyncio.Event()

        if sys.platform == "win32":
            loop = asyncio.get_running_loop()

            if self.client is not None:
                self._pipe_conn = self.client
            else:
                if self.listener is None:
                    self.listener = mp_conn.Listener(address=self.pipe_path, family="AF_PIPE")
                self._pipe_conn = await loop.run_in_executor(None, self.listener.accept)

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
                lambda: read_protocol,
                self.pipe_file,
            )

            # Create write stream
            write_transport, write_protocol = await loop.connect_write_pipe(
                asyncio.Protocol,
                self.pipe_file,
            )
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
        if self._pipe_conn is not None:
            with contextlib.suppress(Exception):
                self._pipe_conn.close()
            self._pipe_conn = None

        if self.client is not None:
            with contextlib.suppress(Exception):
                self.client.close()
            self.client = None

        if self.listener is not None:
            with contextlib.suppress(Exception):
                self.listener.close()
            self.listener = None

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

    async def read_message(self) -> dict[str, Any] | None:  # noqa: PLR0911
        if sys.platform == "win32" and self._pipe_conn is not None:
            loop = asyncio.get_running_loop()
            pipe_conn = self._pipe_conn

            def _recv_for_dap() -> object | None:
                try:
                    return pipe_conn.recv_bytes()
                except (EOFError, OSError):
                    return None
                except Exception:
                    try:
                        return pipe_conn.recv()
                    except (EOFError, OSError):
                        return None

            incoming = await loop.run_in_executor(None, _recv_for_dap)
            if incoming is None:
                return None

            if isinstance(incoming, dict):
                return incoming

            if isinstance(incoming, (bytes, bytearray)):
                payload = bytes(incoming)
            else:
                payload = str(incoming).encode("utf-8")

            message = json.loads(payload.decode("utf-8"))
            traffic_logger.debug("Received message: %s", message)
            return message

        if not self.reader:
            msg = "No active connection"
            raise RuntimeError(msg)

        # Binary frame: read 8-byte header then payload
        from dapper.ipc.ipc_binary import HEADER_SIZE  # noqa: PLC0415
        from dapper.ipc.ipc_binary import unpack_header  # noqa: PLC0415

        header_data = await self.reader.readexactly(HEADER_SIZE)
        if not header_data:
            return None

        try:
            _kind, length = unpack_header(header_data)
        except ValueError:
            logger.exception("Failed to unpack binary header")
            return None

        if length == 0:
            payload_bytes = b""
        else:
            payload_bytes = await self.reader.readexactly(length)
            if not payload_bytes:
                return None

        message = json.loads(payload_bytes.decode("utf-8"))
        traffic_logger.debug("Received message: %s", message)
        return message

    async def write_message(self, message: dict[str, Any]) -> None:
        """Write a binary DAP message to the named pipe connection."""
        content = json.dumps(message).encode("utf-8")
        payload = pack_frame(_KIND_COMMAND, content)

        if sys.platform == "win32" and self._pipe_conn is not None:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._pipe_conn.send_bytes, payload)
            logger.debug("Sent message: %s", message)
            return

        if not getattr(self, "writer", None) and not getattr(self, "pipe_file", None):
            raise RuntimeError("No active connection")

        if getattr(self, "writer", None):
            self.writer.write(payload)
            await self.writer.drain()
        else:
            pf = self.pipe_file
            assert pf is not None
            pf.write(payload)
            pf.flush()

        logger.debug("Sent message: %s", message)
