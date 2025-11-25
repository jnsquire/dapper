from __future__ import annotations

import io
import socket
from typing import Any
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch

from dapper.launcher import debug_launcher
from dapper.launcher import launcher_ipc
from dapper.shared.debug_shared import state


def teardown_function(_fn):
    # reset state to avoid cross-test leakage
    state.ipc_enabled = False
    state.ipc_sock = None
    state.ipc_rfile = None
    state.ipc_wfile = None


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
    # We patch 'os' in launcher_ipc module
    with patch("dapper.launcher.launcher_ipc.os") as mock_os:
        del mock_os.AF_UNIX
        connector = launcher_ipc.SocketConnector()
        sock = connector.connect_unix("/tmp/x")
        assert sock is None


def test_socket_connector_unix_success():
    with patch("socket.socket") as mock_socket_cls, \
            patch("dapper.launcher.launcher_ipc.os") as mock_os:

        mock_os.AF_UNIX = getattr(socket, "AF_UNIX", 1)
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock

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


def test_setup_ipc_socket_with_connector():
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

    # Test unix path
    debug_launcher._setup_ipc_socket(
        "unix", None, None, "/tmp/x", ipc_binary=False, connector=connector
    )
    assert state.ipc_enabled is True

    # reset
    state.ipc_enabled = False
    state.ipc_sock = None
    state.ipc_rfile = None
    state.ipc_wfile = None

    # Test tcp path
    debug_launcher._setup_ipc_socket(
        "tcp", "127.0.0.1", 12345, None, ipc_binary=False, connector=connector
    )
    assert state.ipc_enabled is True