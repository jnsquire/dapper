from __future__ import annotations

import io
import socket
from typing import Any
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from dapper.launcher import debug_launcher
from dapper.launcher import launcher_ipc
from dapper.shared import debug_shared


@pytest.fixture(autouse=True)
def use_debug_session():
    session = debug_shared.DebugSession()
    with debug_shared.use_session(session):
        yield session


def test_socket_connector_tcp_success():
    with patch("socket.socket") as mock_socket_cls:
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock

        connector = launcher_ipc.SocketConnector()
        sock = connector.connect_tcp("127.0.0.1", 12345)

        assert sock is mock_sock
        mock_sock.connect.assert_called_with(("127.0.0.1", 12345))


def test_socket_connector_tcp_failure_bad_port():
    connector = launcher_ipc.SocketConnector()
    # None port should return None
    sock = connector.connect_tcp("127.0.0.1", None)
    assert sock is None


def test_socket_connector_tcp_failure_bad_port_string():
    connector = launcher_ipc.SocketConnector()
    # non-numeric port should return None
    sock = connector.connect_tcp("127.0.0.1", cast("Any", "notanint"))
    assert sock is None


def test_socket_connector_unix_no_af():
    # Simulate environment without unix sockets
    # We patch 'socket' in launcher_ipc module
    with patch("dapper.launcher.launcher_ipc.socket") as mock_socket:
        del mock_socket.AF_UNIX
        connector = launcher_ipc.SocketConnector()
        sock = connector.connect_unix("/tmp/x")
        assert sock is None


def test_socket_connector_unix_no_path_returns_none():
    connector = launcher_ipc.SocketConnector()
    assert connector.connect_unix(None) is None


def test_socket_connector_unix_success():
    with patch("dapper.launcher.launcher_ipc.socket") as mock_socket:
        mock_socket.AF_UNIX = getattr(socket, "AF_UNIX", 1)
        mock_socket.SOCK_STREAM = socket.SOCK_STREAM
        mock_sock = MagicMock()
        mock_socket.socket.return_value = mock_sock

        connector = launcher_ipc.SocketConnector()
        sock = connector.connect_unix("/tmp/x")

        assert sock is mock_sock
        mock_sock.connect.assert_called_with("/tmp/x")


def test_pipeio_readline_and_write():
    class FakeConn:
        def __init__(self):
            self.sent = None

        def send(self, s):
            self.sent = s

        def recv(self):
            return "hello world"

        def close(self):
            pass

    c = FakeConn()
    p = launcher_ipc.PipeIO(cast("Any", c))
    n = p.write("abc")
    assert n == 3
    assert c.sent == "abc"
    # readline full
    assert p.readline() == "hello world"
    # readline with size
    assert p.readline(5) == "hello"


def test_pipeio_readline_eof_and_oserror():
    class EOFConn:
        def recv(self):
            raise EOFError

        def close(self):
            pass

    class OSErrorConn:
        def recv(self):
            raise OSError("read failed")

        def close(self):
            pass

    assert launcher_ipc.PipeIO(cast("Any", EOFConn())).readline() == ""
    assert launcher_ipc.PipeIO(cast("Any", OSErrorConn())).readline() == ""


def test_socket_connector_tcp_uses_default_host_and_closes_on_connect_failure():
    with patch("dapper.launcher.launcher_ipc.socket.socket") as socket_ctor:
        mock_sock = MagicMock()
        socket_ctor.return_value = mock_sock
        mock_sock.connect.side_effect = OSError("connect failed")

        connector = launcher_ipc.SocketConnector()
        sock = connector.connect_tcp(None, 12345)

        assert sock is None
        mock_sock.connect.assert_called_once_with(("127.0.0.1", 12345))
        mock_sock.close.assert_called_once()


def test_socket_connector_unix_closes_on_connect_failure():
    with patch("dapper.launcher.launcher_ipc.socket") as mock_socket:
        mock_socket.AF_UNIX = getattr(socket, "AF_UNIX", 1)
        mock_socket.SOCK_STREAM = socket.SOCK_STREAM
        mock_sock = MagicMock()
        mock_socket.socket.return_value = mock_sock
        mock_sock.connect.side_effect = OSError("connect failed")

        connector = launcher_ipc.SocketConnector()
        sock = connector.connect_unix("/tmp/x")

        assert sock is None
        mock_sock.close.assert_called_once()


def test_socket_connector_unix_socket_ctor_failure_returns_none():
    with patch("dapper.launcher.launcher_ipc.socket") as mock_socket:
        mock_socket.AF_UNIX = getattr(socket, "AF_UNIX", 1)
        mock_socket.SOCK_STREAM = socket.SOCK_STREAM
        mock_socket.socket.side_effect = OSError("ctor failed")

        connector = launcher_ipc.SocketConnector()
        sock = connector.connect_unix("/tmp/x")

        assert sock is None


def test_socket_connector_tcp_socket_ctor_failure_returns_none():
    with patch("dapper.launcher.launcher_ipc.socket.socket") as socket_ctor:
        socket_ctor.side_effect = OSError("ctor failed")

        connector = launcher_ipc.SocketConnector()
        sock = connector.connect_tcp("127.0.0.1", 12345)

        assert sock is None


def test_setup_ipc_socket_with_connector(use_debug_session):
    """Test that we can inject a mock connector into _setup_ipc_socket."""

    class FakeSock:
        def makefile(self, mode, encoding=None, newline=None):  # noqa: ARG002
            return io.StringIO()

        def close(self):
            pass

    class MockConnector:
        def connect_unix(self, _path):
            return FakeSock()

        def connect_tcp(self, _host, _port):
            return FakeSock()

    connector = MockConnector()
    session = use_debug_session

    # Test unix path
    debug_launcher._setup_ipc_socket(
        "unix",
        None,
        None,
        "/tmp/x",
        ipc_binary=False,
        connector=connector,
    )
    assert session.ipc_enabled is True

    # Reset IPC-related fields before testing the TCP path
    session.ipc_enabled = False
    session.ipc_sock = None
    session.ipc_rfile = None
    session.ipc_wfile = None

    # Test tcp path
    debug_launcher._setup_ipc_socket(
        "tcp",
        "127.0.0.1",
        12345,
        None,
        ipc_binary=False,
        connector=connector,
    )
    assert session.ipc_enabled is True
