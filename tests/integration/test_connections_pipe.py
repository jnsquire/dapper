import asyncio
import json
import sys

import pytest

from dapper.ipc.connections.pipe import NamedPipeServerConnection
from dapper.ipc.ipc_binary import pack_frame
from dapper.ipc.ipc_binary import unpack_header

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Non-Windows pipe tests")


class DummyReader:
    def __init__(self, lines, content=b""):
        # lines: iterable of bytes to return from readline
        self._lines = list(lines)
        self._content = content

    async def readline(self):
        if not self._lines:
            return b""
        return self._lines.pop(0)

    async def readexactly(self, n):
        # return exactly n bytes (or raise)
        if len(self._content) < n:
            raise asyncio.IncompleteReadError(partial=self._content, expected=n)
        return self._content[:n]


class DummyWriter:
    def __init__(self):
        self.buffer = bytearray()
        self.closed = False
        self._drained = 0

    def write(self, data: bytes):
        # accept bytes or memoryview
        self.buffer.extend(data)

    async def drain(self):
        self._drained += 1

    def close(self):
        self.closed = True

    async def wait_closed(self):
        return None


class DummyServer:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True

    async def wait_closed(self):
        return None


class DummyPipeFile:
    """Blocking file-like object used to emulate pipe_file writes in tests."""

    def __init__(self):
        self._buf = bytearray()

    def write(self, data: bytes):
        # emulate binary write
        self._buf.extend(data)

    def flush(self):
        # no-op for tests
        return None

    def getvalue(self) -> bytes:
        return bytes(self._buf)


"""

import sys
from pathlib import Path

# Add the project root to the Python path
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:

Async tests for pipe connection; all formerly sync coroutine calls are now async."""


def test_get_pipe_path_for_platforms(monkeypatch):
    conn = NamedPipeServerConnection("foo")
    monkeypatch.setattr(sys, "platform", "win32")
    assert conn._get_pipe_path("mypipe").startswith("\\\\.\\pipe\\")
    monkeypatch.setattr(sys, "platform", "linux")
    assert conn._get_pipe_path("mypipe").startswith("/tmp/")


@pytest.mark.asyncio
async def test_read_message_success():
    conn = NamedPipeServerConnection("x")
    message = {"hello": "world"}
    content = json.dumps(message).encode("utf-8")
    header = f"Content-Length: {len(content)}\r\n".encode()
    # readline must return bytes; include blank line afterwards
    conn.reader = DummyReader([header, b"\r\n"], content=content)

    out = await conn.read_message()
    assert out == message


@pytest.mark.asyncio
async def test_read_message_no_reader_raises():
    conn = NamedPipeServerConnection("y")
    conn.reader = None
    with pytest.raises(RuntimeError, match="No active connection"):
        await conn.read_message()


@pytest.mark.asyncio
async def test_read_message_missing_content_length():
    conn = NamedPipeServerConnection("z")
    # immediate blank line -> headers empty
    conn.reader = DummyReader([b"\r\n"], content=b"")
    with pytest.raises(RuntimeError, match="Content-Length header missing"):
        await conn.read_message()


@pytest.mark.asyncio
async def test_read_message_malformed_content_length():
    conn = NamedPipeServerConnection("m")
    conn.reader = DummyReader([b"Content-Length: nope\r\n", b"\r\n"], content=b"")
    with pytest.raises(RuntimeError, match="Malformed Content-Length header"):
        await conn.read_message()


@pytest.mark.asyncio
async def test_write_message_and_close():
    conn = NamedPipeServerConnection("w")
    writer = DummyWriter()
    server = DummyServer()
    conn.writer = writer
    # assign server bypassing static type checks used by ruff/pyright in tests
    object.__setattr__(conn, "server", server)
    conn._is_connected = True

    # write a message
    msg = {"x": 1}
    await conn.write_message(msg)

    # verify header and content are present in writer.buffer
    buf = bytes(writer.buffer)
    assert b"Content-Length:" in buf
    assert json.dumps(msg).encode() in buf

    # now close and ensure server and writer close paths are invoked
    await conn.close()
    assert writer.closed
    assert server.closed
    assert conn._is_connected is False


@pytest.mark.asyncio
async def test_write_message_no_writer_raises():
    conn = NamedPipeServerConnection("no")
    conn.writer = None
    with pytest.raises(RuntimeError, match="No active connection"):
        await conn.write_message({})


@pytest.mark.asyncio
async def test_write_message_pipe_file():
    conn = NamedPipeServerConnection("pf")
    pf = DummyPipeFile()
    conn.writer = None
    conn.pipe_file = pf
    msg = {"k": "v"}
    await conn.write_message(msg)

    data = pf.getvalue()
    assert b"Content-Length:" in data
    assert json.dumps(msg).encode() in data


@pytest.mark.asyncio
async def test_read_message_eof_returns_none():
    conn = NamedPipeServerConnection("eof")
    # reader that immediately returns EOF
    conn.reader = DummyReader([])
    out = await conn.read_message()
    assert out is None


@pytest.mark.asyncio
async def test_read_message_zero_length_returns_none():
    conn = NamedPipeServerConnection("zero")
    conn.reader = DummyReader([b"Content-Length: 0\r\n", b"\r\n"], content=b"")
    out = await conn.read_message()
    assert out is None


@pytest.mark.asyncio
async def test_handle_client_sets_state():
    conn = NamedPipeServerConnection("hc")
    conn._awaiting_connection_event = asyncio.Event()
    reader = DummyReader([b"\r\n"], content=b"")
    writer = DummyWriter()

    await conn._handle_client(reader, writer)

    assert conn.reader is reader
    assert conn.writer is writer
    assert conn._is_connected is True


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="UNIX socket not on Windows")
async def test_close_unlinks_pipe(tmp_path):
    conn = NamedPipeServerConnection("up")
    # create a dummy file at the pipe path
    p = tmp_path / "mypipe"
    p.write_text("x")
    conn.pipe_path = str(p)
    conn.writer = DummyWriter()
    # assign server bypassing static typing
    object.__setattr__(conn, "server", None)
    conn._is_connected = True

    await conn.close()

    assert not p.exists()


@pytest.mark.asyncio
async def test_read_dbgp_message_text_and_bytes():
    conn = NamedPipeServerConnection("tx")

    # text form
    conn.reader = DummyReader([b"DBGP: text-val\n"])
    out = await conn.read_dbgp_message()
    assert out == "text-val"

    # bytes that are DBGP prefixed
    conn.reader = DummyReader([b"DBGP: bytes-val\n"])
    out = await conn.read_dbgp_message()
    assert out == "bytes-val"


@pytest.mark.asyncio
async def test_read_dbgp_message_binary_frame():

    conn = NamedPipeServerConnection("bf")
    payload = b"hello-binary"
    # pack as kind==1 (DBGP event payload)
    frame = pack_frame(1, payload)
    conn.reader = DummyReader([frame])
    out = await conn.read_dbgp_message()
    assert out == payload.decode("utf-8")


@pytest.mark.asyncio
async def test_write_dbgp_text_and_binary_writer_and_pipefile():
    # Text writer path
    conn = NamedPipeServerConnection("wdbg")
    w = DummyWriter()
    conn.writer = w
    conn.use_binary = False
    await conn.write_dbgp_message("msg-text")
    assert b"DBGP: msg-text\n" in bytes(w.buffer)

    # Text pipe_file path
    pf = DummyPipeFile()
    conn.writer = None
    conn.pipe_file = pf
    await conn.write_dbgp_message("msg-sync")
    assert b"DBGP: msg-sync\n" in pf.getvalue()

    # Binary writer path
    conn = NamedPipeServerConnection("wbin")
    w = DummyWriter()
    conn.writer = w
    conn.use_binary = True
    await conn.write_dbgp_message("bin-msg")
    buf = bytes(w.buffer)
    # check header + payload
    hdr = buf[:8]
    kind, length = unpack_header(hdr)
    assert kind == 2
    payload = buf[8 : 8 + length]
    assert payload.decode("utf-8") == "bin-msg"

    # Binary pipe_file path
    pf = DummyPipeFile()
    conn.writer = None
    conn.pipe_file = pf
    await conn.write_dbgp_message("bin-sync")
    data = pf.getvalue()
    hdr = data[:8]
    kind, length = unpack_header(hdr)
    assert kind == 2
    payload = data[8 : 8 + length]
    assert payload.decode("utf-8") == "bin-sync"
