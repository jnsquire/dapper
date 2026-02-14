import json
import sys

import pytest

from dapper.ipc.connections import pipe as pipe_mod
from dapper.ipc.connections.pipe import NamedPipeServerConnection
from dapper.ipc.ipc_binary import HEADER_SIZE
from dapper.ipc.ipc_binary import pack_frame
from dapper.ipc.ipc_binary import unpack_header

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only pipe tests")


class FakePipeConnection:
    def __init__(self) -> None:
        self.recv_bytes_values: list[object] = []
        self.recv_values: list[object] = []
        self.sent_bytes: list[bytes] = []
        self.sent_values: list[object] = []
        self.closed = False

    def recv_bytes(self):
        if not self.recv_bytes_values:
            raise EOFError
        value = self.recv_bytes_values.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def recv(self):
        if not self.recv_values:
            raise EOFError
        value = self.recv_values.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def send_bytes(self, payload: bytes) -> None:
        self.sent_bytes.append(payload)

    def send(self, value: object) -> None:
        self.sent_values.append(value)

    def close(self) -> None:
        self.closed = True


class FakeListener:
    def __init__(self, pipe_conn: FakePipeConnection) -> None:
        self.pipe_conn = pipe_conn
        self.closed = False
        self.accept_called = 0

    def accept(self):
        self.accept_called += 1
        return self.pipe_conn

    def close(self) -> None:
        self.closed = True


class FakeWriter:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


class FakeServer:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


@pytest.mark.asyncio
async def test_windows_accept_uses_listener(monkeypatch) -> None:
    monkeypatch.setattr(pipe_mod.sys, "platform", "win32")

    fake_conn = FakePipeConnection()
    fake_listener = FakeListener(fake_conn)

    monkeypatch.setattr(pipe_mod.mp_conn, "Listener", lambda _address, _family: fake_listener)

    conn = NamedPipeServerConnection("unit-pipe")
    await conn.accept()

    assert conn.is_connected is True
    assert conn._pipe_conn is fake_conn
    assert fake_listener.accept_called == 1


@pytest.mark.asyncio
async def test_windows_accept_uses_existing_client(monkeypatch) -> None:
    monkeypatch.setattr(pipe_mod.sys, "platform", "win32")

    client_conn = FakePipeConnection()
    conn = NamedPipeServerConnection("client-pipe")
    conn.client = client_conn

    await conn.accept()

    assert conn.is_connected is True
    assert conn._pipe_conn is client_conn


@pytest.mark.asyncio
async def test_windows_read_message_from_header_payload(monkeypatch) -> None:
    monkeypatch.setattr(pipe_mod.sys, "platform", "win32")

    conn = NamedPipeServerConnection("read-pipe")
    pipe_conn = FakePipeConnection()
    message = {"type": "request", "command": "initialize"}
    content = json.dumps(message).encode("utf-8")
    payload = f"Content-Length: {len(content)}\r\n\r\n".encode() + content
    pipe_conn.recv_bytes_values.append(payload)
    conn._pipe_conn = pipe_conn

    out = await conn.read_message()

    assert out == message


@pytest.mark.asyncio
async def test_windows_read_message_falls_back_to_recv_dict(monkeypatch) -> None:
    monkeypatch.setattr(pipe_mod.sys, "platform", "win32")

    conn = NamedPipeServerConnection("read-fallback")
    pipe_conn = FakePipeConnection()
    pipe_conn.recv_bytes_values.append(RuntimeError("use recv fallback"))
    pipe_conn.recv_values.append({"event": "stopped"})
    conn._pipe_conn = pipe_conn

    out = await conn.read_message()

    assert out == {"event": "stopped"}


@pytest.mark.asyncio
async def test_windows_read_dbgp_binary_and_text(monkeypatch) -> None:
    monkeypatch.setattr(pipe_mod.sys, "platform", "win32")

    conn = NamedPipeServerConnection("dbgp")
    pipe_conn = FakePipeConnection()

    pipe_conn.recv_bytes_values.append(pack_frame(1, b"bin-msg"))
    pipe_conn.recv_bytes_values.append(RuntimeError("use recv"))
    pipe_conn.recv_values.append("DBGP: txt-msg")

    conn._pipe_conn = pipe_conn

    first = await conn.read_dbgp_message()
    second = await conn.read_dbgp_message()

    assert first == "bin-msg"
    assert second == "txt-msg"


@pytest.mark.asyncio
async def test_windows_write_dbgp_and_message(monkeypatch) -> None:
    monkeypatch.setattr(pipe_mod.sys, "platform", "win32")

    conn = NamedPipeServerConnection("write-pipe")
    pipe_conn = FakePipeConnection()
    conn._pipe_conn = pipe_conn

    conn.use_binary = False
    await conn.write_dbgp_message("hello")
    assert pipe_conn.sent_values == ["DBGP: hello"]

    conn.use_binary = True
    await conn.write_dbgp_message("binary")
    frame = pipe_conn.sent_bytes[-1]
    kind, length = unpack_header(frame[:HEADER_SIZE])
    assert kind == 2
    assert frame[HEADER_SIZE : HEADER_SIZE + length] == b"binary"

    await conn.write_message({"seq": 1, "type": "event"})
    payload = pipe_conn.sent_bytes[-1]
    assert payload.startswith(b"Content-Length:")
    assert b'"seq": 1' in payload


@pytest.mark.asyncio
async def test_windows_close_cleans_pipe_resources(monkeypatch) -> None:
    monkeypatch.setattr(pipe_mod.sys, "platform", "win32")

    conn = NamedPipeServerConnection("close-pipe")
    conn._pipe_conn = FakePipeConnection()
    conn.client = FakePipeConnection()
    conn.listener = FakeListener(FakePipeConnection())
    conn.writer = FakeWriter()
    conn.server = FakeServer()
    conn._is_connected = True

    await conn.close()

    assert conn._is_connected is False
    assert conn._pipe_conn is None
    assert conn.client is None
    assert conn.listener is None
    assert conn.writer.closed is True
    assert conn.server.closed is True
