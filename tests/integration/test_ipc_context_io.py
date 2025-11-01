from __future__ import annotations

import io

import pytest

from dapper.ipc_binary import pack_frame
from dapper.ipc_context import IPCContext


class _PipeListener:
    def __init__(self, connection: object) -> None:
        self._connection = connection

    def accept(self):  # type: ignore[override]
        return self._connection


class _TextPipeConn:
    def __init__(self, messages: list[object]) -> None:
        self._messages = messages

    def recv(self):
        if not self._messages:
            raise EOFError
        return self._messages.pop(0)


class _BinaryPipeConn:
    def __init__(self, frames: list[bytes]) -> None:
        self._frames = frames

    def recv_bytes(self) -> bytes:
        if not self._frames:
            return b""
        return self._frames.pop(0)


class _SocketConn:
    def __init__(self, reader: object, writer: object) -> None:
        self._reader = reader
        self._writer = writer

    def makefile(self, mode: str, **_: object):  # type: ignore[override]
        return self._reader if "r" in mode else self._writer


class _SocketListener:
    def __init__(self, connection: _SocketConn) -> None:
        self._connection = connection

    def accept(self):  # type: ignore[override]
        return self._connection, ("127.0.0.1", 0)


@pytest.mark.parametrize(
    ("messages", "expected"),
    [
        (["DBGP: hello", "ignored", 42], ["hello"]),
        (["ignored", "DBGP: bye"], ["bye"]),
    ],
)
def test_accept_and_read_pipe_text(messages: list[object], expected: list[str]) -> None:
    ctx = IPCContext(binary=False)
    conn = _TextPipeConn(list(messages))
    ctx.pipe_listener = _PipeListener(conn)

    received: list[str] = []

    ctx.accept_and_read_pipe(received.append)

    assert received == expected
    assert ctx.pipe_conn is conn
    assert ctx.enabled is (expected != [])


def test_accept_and_read_pipe_binary() -> None:
    payloads = [pack_frame(1, b"hello"), pack_frame(1, b"world")]
    conn = _BinaryPipeConn([*payloads, b""])
    ctx = IPCContext(binary=True)
    ctx.pipe_listener = _PipeListener(conn)

    received: list[str] = []
    ctx.accept_and_read_pipe(received.append)

    assert received == ["hello", "world"]
    assert ctx.pipe_conn is conn
    assert ctx.enabled is True


def test_accept_and_read_socket_text() -> None:
    reader = io.StringIO("DBGP: ping\nother\n")
    writer = io.StringIO()
    conn = _SocketConn(reader, writer)
    ctx = IPCContext(binary=False)
    ctx.listen_sock = _SocketListener(conn)

    received: list[str] = []
    ctx.accept_and_read_socket(received.append)

    assert received == ["ping"]
    assert ctx.rfile is reader
    assert ctx.wfile is writer
    assert ctx.enabled is True


def test_accept_and_read_socket_binary() -> None:
    frames = pack_frame(1, b"alpha") + pack_frame(1, b"beta")
    reader = io.BytesIO(frames)
    writer = io.BytesIO()
    conn = _SocketConn(reader, writer)
    ctx = IPCContext(binary=True)
    ctx.listen_sock = _SocketListener(conn)

    received: list[str] = []
    ctx.accept_and_read_socket(received.append)

    assert received == ["alpha", "beta"]
    assert ctx.rfile is reader
    assert ctx.wfile is writer
    assert ctx.enabled is True
