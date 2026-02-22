import contextlib
import os
from pathlib import Path
import socket
import threading
from unittest.mock import MagicMock

import pytest

from dapper.ipc.transport_factory import TransportConfig
from dapper.ipc.transport_factory import TransportFactory


def test_resolve_transport_none_auto_and_explicit(monkeypatch):
    monkeypatch.setattr(TransportFactory, "get_default_transport", staticmethod(lambda: "unix"))
    assert TransportFactory.resolve_transport(None) == "unix"
    assert TransportFactory.resolve_transport("auto") == "unix"
    assert TransportFactory.resolve_transport("TCP") == "tcp"


def test_create_listener_unsupported_transport_raises():
    cfg = TransportConfig(transport="bogus")
    with pytest.raises(ValueError, match="Unsupported transport"):
        TransportFactory.create_listener(cfg)


def test_create_connection_unsupported_transport_raises():
    cfg = TransportConfig(transport="bogus")
    with pytest.raises(ValueError, match="Unsupported transport"):
        TransportFactory.create_connection(cfg)


def test_create_tcp_listener_socket_returns_socket_and_args():
    listen, args = TransportFactory.create_tcp_listener_socket("127.0.0.1")
    try:
        assert isinstance(listen, socket.socket)
        # args should include the tcp host/port pair
        assert args[0:3] == ["--ipc", "tcp", "--ipc-host"] or args[0:2] == ["--ipc", "tcp"]
        # port should be an int parseable value
        assert any(arg.isdigit() for arg in args)
        # socket should be bound and listening
        addr = listen.getsockname()
        assert isinstance(addr, tuple)
        assert len(addr) >= 2
    finally:
        listen.close()


def _accept_one(sock: socket.socket, ready_event: threading.Event):
    # simple accept helper for tests
    ready_event.set()
    try:
        conn, _ = sock.accept()
        conn.close()
    except Exception:
        pass


def test_create_tcp_client_socket_connects_to_listener():
    # Create a listening socket and accept one connection in a background thread
    listen, _args = TransportFactory.create_tcp_listener_socket("127.0.0.1")
    try:
        addr = listen.getsockname()
        host, port = addr[0], addr[1]

        ready = threading.Event()
        thr = threading.Thread(target=_accept_one, args=(listen, ready), daemon=True)
        thr.start()

        # wait until accept thread is ready
        ready.wait(timeout=1.0)

        # Create client socket that connects to server
        client_sock = TransportFactory.create_tcp_client_socket(host, port)
        try:
            assert isinstance(client_sock, socket.socket)
        finally:
            client_sock.close()

        thr.join(timeout=1.0)
    finally:
        # Ensure socket is cleaned up
        listen.close()


def test_create_tcp_client_socket_requires_port():
    with pytest.raises(ValueError):  # noqa: PT011
        TransportFactory.create_tcp_client_socket("127.0.0.1", None)


def test_create_tcp_client_socket_invalid_port_raises():
    # ports > 65535 will generate an OverflowError on connect
    with pytest.raises(OverflowError):
        TransportFactory.create_tcp_client_socket("127.0.0.1", 99999)


def test_create_sync_connection_missing_required_fields():
    with pytest.raises(ValueError, match="path is required"):
        TransportFactory.create_sync_connection(TransportConfig(transport="unix"))
    with pytest.raises(ValueError, match="port is required"):
        TransportFactory.create_sync_connection(TransportConfig(transport="tcp"))


def test_create_sync_listener_unsupported_transport_raises():
    cfg = TransportConfig(transport="bogus")
    with pytest.raises(ValueError, match="Unsupported transport"):
        TransportFactory.create_sync_listener(cfg)


def test_create_sync_listener_and_connection_tcp():
    cfg = TransportConfig(transport="tcp", host="127.0.0.1")
    listen, args, _ = TransportFactory.create_sync_listener(cfg)
    try:
        assert isinstance(listen, socket.socket)
        # now connect synchronously using the factory helper
        port = int(args[-1])
        client_cfg = TransportConfig(transport="tcp", host="127.0.0.1", port=port)
        client = TransportFactory.create_sync_connection(client_cfg)
        try:
            assert isinstance(client, socket.socket)
        finally:
            client.close()
    finally:
        listen.close()


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="unix sockets not supported")
def test_create_sync_listener_and_connection_unix():
    cfg = TransportConfig(transport="unix")
    listen, _args, path = TransportFactory.create_sync_listener(cfg)
    try:
        assert isinstance(listen, socket.socket)
        assert path is not None

        client_cfg = TransportConfig(transport="unix", path=str(path))
        client = TransportFactory.create_sync_connection(client_cfg)
        try:
            assert isinstance(client, socket.socket)
        finally:
            with contextlib.suppress(Exception):
                Path(path).unlink()
            client.close()
    finally:
        listen.close()


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="unix sockets not supported")
def test_create_unix_listener_and_client_socket_connects():
    listen, _args, path = TransportFactory.create_unix_listener_socket()
    try:
        # Accept thread
        ready = threading.Event()

        def accept_once(s: socket.socket, ready_ev: threading.Event):
            ready_ev.set()
            try:
                conn, _ = s.accept()
                conn.close()
            except Exception:
                pass

        thr = threading.Thread(target=accept_once, args=(listen, ready), daemon=True)
        thr.start()
        ready.wait(timeout=1.0)

        client_sock = TransportFactory.create_unix_client_socket(str(path))
        try:
            assert isinstance(client_sock, socket.socket)
        finally:
            client_sock.close()

    finally:
        # cleanup socket file
        listen.close()
        Path(path).unlink()


@pytest.mark.skipif(os.name != "nt", reason="named pipe tests only run on Windows")
def test_create_pipe_listener_and_client_sync():
    # Create a named pipe listener and a client, send a message
    listener, args = TransportFactory.create_pipe_listener_sync(None)
    full_path = args[-1]

    received = {}

    def server_thread(listener_obj, received_dict):
        conn = listener_obj.accept()
        try:
            msg = conn.recv()
            received_dict["msg"] = msg
        finally:
            conn.close()

    thr = threading.Thread(target=server_thread, args=(listener, received), daemon=True)
    thr.start()

    # Connect client and send a message
    client = TransportFactory.create_pipe_client_sync(full_path)
    try:
        client.send("hello-pipe")
    finally:
        client.close()

    thr.join(timeout=1.0)
    if listener:
        listener.close()
    assert received.get("msg") == "hello-pipe"


def test_create_unix_listener_falls_back_when_af_unix_missing(monkeypatch):
    monkeypatch.setattr("dapper.ipc.transport_factory._socket.AF_UNIX", None, raising=False)
    called: dict[str, bool] = {"tcp": False}

    def fake_tcp_listener(_cfg):
        called["tcp"] = True
        return "tcp-conn", ["--ipc", "tcp"]

    monkeypatch.setattr(TransportFactory, "_create_tcp_listener", staticmethod(fake_tcp_listener))
    conn, args = TransportFactory._create_unix_listener(TransportConfig(transport="unix"))
    assert called["tcp"] is True
    assert conn == "tcp-conn"
    assert args == ["--ipc", "tcp"]


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="unix sockets not supported")
def test_create_unix_listener_falls_back_when_socket_creation_fails(monkeypatch):
    def explode_socket(*_args, **_kwargs):
        msg = "boom"
        raise OSError(msg)

    monkeypatch.setattr("dapper.ipc.transport_factory._socket.socket", explode_socket)
    called: dict[str, bool] = {"tcp": False}

    def fake_tcp_listener(_cfg):
        called["tcp"] = True
        return "tcp-conn", ["--ipc", "tcp"]

    monkeypatch.setattr(TransportFactory, "_create_tcp_listener", staticmethod(fake_tcp_listener))
    conn, args = TransportFactory._create_unix_listener(TransportConfig(transport="unix"))
    assert called["tcp"] is True
    assert conn == "tcp-conn"
    assert args == ["--ipc", "tcp"]


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="unix sockets not supported")
def test_create_unix_connection_wraps_connect_failures(monkeypatch):
    class BrokenSocket:
        def connect(self, _path):
            msg = "connect-fail"
            raise OSError(msg)

    monkeypatch.setattr(
        "dapper.ipc.transport_factory._socket.socket",
        lambda *_args, **_kwargs: BrokenSocket(),
    )
    cfg = TransportConfig(transport="unix", path="/tmp/missing.sock")
    with pytest.raises(RuntimeError, match="Failed to connect to Unix socket"):
        TransportFactory._create_unix_connection(cfg)


def test_create_tcp_connection_wraps_connect_failures(monkeypatch):
    class BrokenSocket:
        def connect(self, _addr):
            msg = "connect-fail"
            raise OSError(msg)

    monkeypatch.setattr(
        "dapper.ipc.transport_factory._socket.socket",
        lambda *_args, **_kwargs: BrokenSocket(),
    )
    cfg = TransportConfig(transport="tcp", host="127.0.0.1", port=4711)
    with pytest.raises(RuntimeError, match="Failed to connect to TCP socket"):
        TransportFactory._create_tcp_connection(cfg)


def test_create_pipe_listener_sync_mocked_windows(monkeypatch):
    fake_listener = MagicMock()
    monkeypatch.setattr("dapper.ipc.transport_factory._is_windows", lambda: True)
    monkeypatch.setattr(
        "dapper.ipc.transport_factory.mp_conn.Listener",
        lambda **_kw: fake_listener,
    )

    listener, args = TransportFactory.create_pipe_listener_sync("my-pipe")
    assert listener is fake_listener
    assert args == ["--ipc", "pipe", "--ipc-pipe", r"\\.\pipe\my-pipe"]


def test_create_pipe_client_sync_mocked_windows(monkeypatch):
    fake_client = MagicMock()
    monkeypatch.setattr("dapper.ipc.transport_factory._is_windows", lambda: True)
    monkeypatch.setattr("dapper.ipc.transport_factory.mp_conn.Client", lambda **_kw: fake_client)

    client = TransportFactory.create_pipe_client_sync(r"\\.\pipe\my-pipe")
    assert client is fake_client


def test_create_pipe_listener_and_connection_routes_mocked_windows(monkeypatch):
    monkeypatch.setattr("dapper.ipc.transport_factory._is_windows", lambda: True)

    fake_listener = MagicMock()
    fake_pipe_client = MagicMock()

    monkeypatch.setattr(
        "dapper.ipc.transport_factory.mp_conn.Listener",
        lambda **_kw: fake_listener,
    )
    monkeypatch.setattr(
        "dapper.ipc.transport_factory.mp_conn.Client",
        lambda **_kw: fake_pipe_client,
    )

    listener_conn, args = TransportFactory.create_listener(TransportConfig(transport="pipe"))
    assert args[:2] == ["--ipc", "pipe"]
    assert getattr(listener_conn, "listener", None) is fake_listener

    client_conn = TransportFactory.create_connection(
        TransportConfig(transport="pipe", pipe_name=r"\\.\pipe\my-pipe"),
    )
    assert getattr(client_conn, "client", None) is fake_pipe_client


def test_create_pipe_listener_sync_non_windows_raises(monkeypatch):
    monkeypatch.setattr("dapper.ipc.transport_factory._is_windows", lambda: False)
    with pytest.raises(RuntimeError, match="Named pipes are only supported on Windows"):
        TransportFactory.create_pipe_listener_sync("pipe-name")


def test_create_pipe_client_sync_non_windows_raises(monkeypatch):
    monkeypatch.setattr("dapper.ipc.transport_factory._is_windows", lambda: False)
    with pytest.raises(RuntimeError, match="Named pipes are only supported on Windows"):
        TransportFactory.create_pipe_client_sync(r"\\.\pipe\pipe-name")


def test_create_pipe_connection_wraps_client_exceptions(monkeypatch):
    def explode_client(**_kwargs):
        msg = "pipe connect failed"
        raise OSError(msg)

    monkeypatch.setattr("dapper.ipc.transport_factory._is_windows", lambda: True)
    monkeypatch.setattr("dapper.ipc.transport_factory.mp_conn.Client", explode_client)

    with pytest.raises(RuntimeError, match="Failed to connect to pipe"):
        TransportFactory._create_pipe_connection(
            TransportConfig(transport="pipe", pipe_name=r"\\.\pipe\missing"),
        )


def test_create_pipe_listener_wraps_listener_exceptions(monkeypatch):
    def explode_listener(**_kwargs):
        msg = "listener failed"
        raise OSError(msg)

    monkeypatch.setattr("dapper.ipc.transport_factory._is_windows", lambda: True)
    monkeypatch.setattr("dapper.ipc.transport_factory.mp_conn.Listener", explode_listener)

    with pytest.raises(RuntimeError, match="Failed to create pipe listener"):
        TransportFactory._create_pipe_listener(TransportConfig(transport="pipe"))
