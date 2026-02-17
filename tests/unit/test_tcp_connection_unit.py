from __future__ import annotations

import asyncio
import json

import pytest

from dapper.ipc.connections.tcp import TCPServerConnection


class _DummyReader:
    def __init__(self, *, lines: list[bytes] | None = None, exact: list[bytes] | None = None):
        self._lines = list(lines or [])
        self._exact = list(exact or [])

    async def readline(self) -> bytes:
        if not self._lines:
            return b""
        return self._lines.pop(0)

    async def readexactly(self, _n: int) -> bytes:
        if not self._exact:
            raise asyncio.IncompleteReadError(partial=b"", expected=1)
        return self._exact.pop(0)


class _DummyWriter:
    def __init__(self) -> None:
        self.data = bytearray()
        self.closed = False
        self.drains = 0

    def write(self, payload: bytes) -> None:
        self.data.extend(payload)

    async def drain(self) -> None:
        self.drains += 1

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


@pytest.mark.asyncio
async def test_wait_for_client_before_start_raises():
    conn = TCPServerConnection(host="127.0.0.1", port=0)
    with pytest.raises(RuntimeError, match="wait_for_client called before start_listening"):
        await conn.wait_for_client(timeout=0.01)


@pytest.mark.asyncio
async def test_wait_for_client_timeout_without_client():
    conn = TCPServerConnection(host="127.0.0.1", port=0)
    try:
        await conn.start_listening()
        with pytest.raises(asyncio.TimeoutError):
            await conn.wait_for_client(timeout=0.01)
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_read_message_without_reader_raises():
    conn = TCPServerConnection(host="127.0.0.1", port=0)
    conn.reader = None
    with pytest.raises(RuntimeError, match="No active connection"):
        await conn.read_message()


@pytest.mark.asyncio
async def test_read_dap_message_missing_content_length_raises():
    conn = TCPServerConnection(host="127.0.0.1", port=0)
    conn.reader = _DummyReader(lines=[b"Header: value\r\n", b"\r\n"])
    with pytest.raises(RuntimeError, match="Content-Length header missing"):
        await conn._read_dap_message()


@pytest.mark.asyncio
async def test_write_message():
    conn = TCPServerConnection(host="127.0.0.1", port=0)
    writer = _DummyWriter()
    conn.writer = writer

    await conn.write_message({"event": "ok"})
    assert b"Content-Length:" in bytes(writer.data)
    assert json.dumps({"event": "ok"}).encode("utf-8") in bytes(writer.data)
