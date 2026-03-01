import asyncio
import json
import sys
from unittest.mock import MagicMock

import pytest

from dapper.ipc.connections.pipe import NamedPipeServerConnection
from dapper.ipc.ipc_binary import HEADER_SIZE
from dapper.ipc.ipc_binary import pack_frame

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Non-Windows pipe tests")


class DummyReader:
    def __init__(self, exact_reads=None):
        # exact_reads: list of bytes to return from readexactly calls
        self._exact = list(exact_reads or [])

    async def readline(self):
        return b""

    async def readexactly(self, n):
        if not self._exact:
            raise asyncio.IncompleteReadError(partial=b"", expected=n)
        data = self._exact.pop(0)
        if len(data) < n:
            raise asyncio.IncompleteReadError(partial=data, expected=n)
        return data[:n]


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


@pytest.mark.asyncio
async def test_read_message_success():
    conn = NamedPipeServerConnection("x")
    message = {"hello": "world"}
    content = json.dumps(message).encode("utf-8")
    # Build a binary frame: 8-byte header + payload
    frame = pack_frame(2, content)  # kind=2 for commands
    header = frame[:HEADER_SIZE]
    payload = frame[HEADER_SIZE:]
    conn.reader = DummyReader(exact_reads=[header, payload])

    out = await conn.read_message()
    assert out == message


@pytest.mark.asyncio
async def test_read_message_no_reader_raises():
    conn = NamedPipeServerConnection("y")
    conn.reader = None
    with pytest.raises(RuntimeError, match="No active connection"):
        await conn.read_message()


@pytest.mark.asyncio
async def test_read_message_bad_header():
    conn = NamedPipeServerConnection("z")
    # Bad header (not a valid DP frame)
    conn.reader = DummyReader(exact_reads=[b"\x00" * HEADER_SIZE])
    out = await conn.read_message()
    assert out is None


@pytest.mark.asyncio
async def test_read_message_incomplete_header():
    conn = NamedPipeServerConnection("m")
    conn.reader = DummyReader(exact_reads=[])  # no data -> IncompleteReadError
    with pytest.raises(asyncio.IncompleteReadError):
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

    # verify binary frame is present in writer.buffer
    buf = bytes(writer.buffer)
    # Binary frame starts with magic "DP"
    assert buf[:2] == b"DP"
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
    # Binary frame starts with magic "DP"
    assert data[:2] == b"DP"
    assert json.dumps(msg).encode() in data


@pytest.mark.asyncio
async def test_read_message_eof_returns_none():
    conn = NamedPipeServerConnection("eof")
    # reader that immediately returns EOF on readexactly
    conn.reader = DummyReader(exact_reads=[])
    # readexactly with no data raises IncompleteReadError
    with pytest.raises(asyncio.IncompleteReadError):
        await conn.read_message()


@pytest.mark.asyncio
async def test_read_message_zero_length_payload():
    conn = NamedPipeServerConnection("zero")
    # Build a frame with 0-length payload
    frame = pack_frame(2, b"")
    header = frame[:HEADER_SIZE]
    conn.reader = DummyReader(exact_reads=[header])
    # Empty payload cannot be JSON-decoded, so it should raise or return None
    # json.loads(b"") raises JSONDecodeError
    with pytest.raises(json.JSONDecodeError):
        await conn.read_message()


@pytest.mark.asyncio
async def test_handle_client_sets_state():
    conn = NamedPipeServerConnection("hc")
    conn._awaiting_connection_event = asyncio.Event()
    reader = DummyReader(exact_reads=[])
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


def test_get_pipe_path_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    conn = NamedPipeServerConnection("mypipe")
    assert conn.pipe_path == "/tmp/mypipe"


def test_get_pipe_path_windows_format(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    conn = NamedPipeServerConnection("mypipe")
    assert conn.pipe_path == r"\\.\pipe\mypipe"


def test_is_connected_property():
    conn = NamedPipeServerConnection("prop")
    assert conn.is_connected is False
    conn.is_connected = True
    assert conn._is_connected is True
    conn.is_connected = False
    assert conn._is_connected is False


@pytest.mark.asyncio
async def test_close_noop_no_resources():
    """close() with no writer/server/listener/client must not raise."""
    conn = NamedPipeServerConnection("noop")
    conn._is_connected = True
    # pipe_path may not exist on disk - no-op on POSIX
    await conn.close()
    assert conn._is_connected is False


@pytest.mark.asyncio
async def test_close_pipe_path_already_absent(tmp_path):
    """close() must not raise when pipe file was already removed."""
    conn = NamedPipeServerConnection("absent")
    conn.pipe_path = str(tmp_path / "gone")
    conn._is_connected = True
    await conn.close()  # should not raise


@pytest.mark.asyncio
async def test_close_with_pipe_conn():
    """_pipe_conn.close() is called and reference is cleared."""
    conn = NamedPipeServerConnection("pc")
    mock_conn = MagicMock()
    conn._pipe_conn = mock_conn
    conn._is_connected = True

    await conn.close()

    mock_conn.close.assert_called_once()
    assert conn._pipe_conn is None


@pytest.mark.asyncio
async def test_close_with_client_and_listener():
    """client and listener are each closed exactly once."""
    conn = NamedPipeServerConnection("cl")
    mock_client = MagicMock()
    mock_listener = MagicMock()
    conn.client = mock_client
    conn.listener = mock_listener
    conn._is_connected = True

    await conn.close()

    mock_client.close.assert_called_once()
    mock_listener.close.assert_called_once()
    assert conn.client is None
    assert conn.listener is None


@pytest.mark.asyncio
async def test_close_pipe_conn_error_suppressed():
    """Exceptions from _pipe_conn.close() are suppressed."""
    conn = NamedPipeServerConnection("err")
    mock_conn = MagicMock()
    mock_conn.close.side_effect = OSError("boom")
    conn._pipe_conn = mock_conn
    conn._is_connected = True

    await conn.close()  # must not raise
    assert conn._is_connected is False


@pytest.mark.asyncio
async def test_handle_client_no_event_does_not_raise():
    """`_handle_client` must work when _awaiting_connection_event is None."""
    conn = NamedPipeServerConnection("noev")
    conn._awaiting_connection_event = None
    reader = DummyReader(exact_reads=[])
    writer = DummyWriter()

    await conn._handle_client(reader, writer)

    assert conn._is_connected is True
    assert conn.reader is reader
    assert conn.writer is writer


@pytest.mark.asyncio
async def test_handle_client_clears_event():
    """After `_handle_client` fires the event, the reference is cleared."""
    conn = NamedPipeServerConnection("clr")
    event = asyncio.Event()
    conn._awaiting_connection_event = event
    reader = DummyReader(exact_reads=[])
    writer = DummyWriter()

    await conn._handle_client(reader, writer)

    assert event.is_set()
    assert conn._awaiting_connection_event is None


@pytest.mark.asyncio
async def test_read_message_binary_frame_round_trip():
    """A binary-framed message must round-trip correctly through read_message."""
    conn = NamedPipeServerConnection("mh")
    message = {"seq": 1, "type": "request"}
    content = json.dumps(message).encode("utf-8")
    frame = pack_frame(2, content)
    header = frame[:HEADER_SIZE]
    payload = frame[HEADER_SIZE:]
    conn.reader = DummyReader(exact_reads=[header, payload])

    out = await conn.read_message()
    assert out == message


@pytest.mark.asyncio
async def test_read_message_invalid_json_raises():
    """A payload that is not valid JSON must raise json.JSONDecodeError."""
    conn = NamedPipeServerConnection("ij")
    bad_payload = b"not-json!!!"
    frame = pack_frame(2, bad_payload)
    header = frame[:HEADER_SIZE]
    payload = frame[HEADER_SIZE:]
    conn.reader = DummyReader(exact_reads=[header, payload])

    with pytest.raises(json.JSONDecodeError):
        await conn.read_message()


@pytest.mark.asyncio
async def test_write_message_drain_called():
    """write_message must call drain() exactly once when using a writer."""
    conn = NamedPipeServerConnection("d")
    writer = DummyWriter()
    conn.writer = writer

    await conn.write_message({"cmd": "continue"})

    assert writer._drained == 1
