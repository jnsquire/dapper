from __future__ import annotations

import io
from typing import Any
from typing import cast

from dapper import launcher_ipc
from dapper.debug_adapter_comm import state


def teardown_function(_fn):
    # reset state to avoid cross-test leakage
    state.ipc_enabled = False
    state.ipc_sock = None
    state.ipc_rfile = None
    state.ipc_wfile = None


def test_setup_ipc_pipe_success(monkeypatch):
    class FakeConn:
        def send(self, s):
            pass

        def recv(self):
            return "msg"

        def close(self):
            pass

    def fake_client(*_args, **_kwargs):
        return FakeConn()

    class M:
        Client = fake_client

    monkeypatch.setattr(launcher_ipc, "_mpc", M)

    ok = launcher_ipc._setup_ipc_pipe(r"\\.\pipe\test")
    assert ok is True
    assert state.ipc_enabled is True
    assert state.ipc_rfile is not None
    assert state.ipc_wfile is not None
    # exercise the read/write API
    assert hasattr(state.ipc_rfile, "readline")
    assert hasattr(state.ipc_wfile, "write")


def test_setup_ipc_pipe_failure(monkeypatch):
    def bad_client(*_args, **_kwargs):
        msg = "no pipe"
        raise RuntimeError(msg)

    class M:
        Client = bad_client

    monkeypatch.setattr(launcher_ipc, "_mpc", M)
    ok = launcher_ipc._setup_ipc_pipe(r"\\.\pipe\test")
    assert ok is False
    assert state.ipc_enabled is False


def test_connect_tcp_success(monkeypatch):
    created = {}

    class FakeSocket:
        def __init__(self):
            created["sock"] = True

        def connect(self, addr):
            # accept any address
            created["addr"] = addr

        def makefile(self, _mode):
            return io.StringIO()

        def close(self):
            created["closed"] = True

    def fake_socket(*_args, **_kwargs):
        return FakeSocket()

    monkeypatch.setattr(launcher_ipc.socket, "socket", fake_socket)

    sock = launcher_ipc._connect_tcp_socket("127.0.0.1", 12345)
    assert sock is not None


def test_connect_tcp_failure_bad_port():
    # None port should return None
    sock = launcher_ipc._connect_tcp_socket("127.0.0.1", None)
    assert sock is None


def test_connect_tcp_failure_bad_port_string():
    # non-numeric port should return None
    # cast to satisfy static type checkers; runtime will attempt int() and fail
    sock = launcher_ipc._connect_tcp_socket("127.0.0.1", cast("Any", "notanint"))
    assert sock is None


def test_connect_unix_no_af(monkeypatch):
    # Remove AF_UNIX attribute to simulate environment without unix sockets
    monkeypatch.delattr(launcher_ipc.os, "AF_UNIX", raising=False)
    sock = launcher_ipc._connect_unix_socket("/tmp/x")
    assert sock is None


def test_connect_unix_success(monkeypatch):
    class FakeSock:
        def __init__(self):
            self.connected = False

        def connect(self, path):  # noqa: ARG002
            self.connected = True

        def close(self):
            pass

    def fake_socket(*_args):
        return FakeSock()

    monkeypatch.setattr(launcher_ipc.socket, "socket", fake_socket)
    # Ensure AF_UNIX present for the test
    monkeypatch.setattr(launcher_ipc.os, "AF_UNIX", 1, raising=False)
    sock = launcher_ipc._connect_unix_socket("/tmp/x")
    assert sock is not None


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


def test_setup_ipc_socket_unix_and_tcp(monkeypatch):
    # Test unix path success via monkeypatching _connect_unix_socket
    class FakeSock:
        def makefile(self, mode, encoding=None, newline=None):  # noqa: ARG002
            return io.StringIO()

    def fake_unix(_p):
        return FakeSock()

    def fake_tcp(_h, _p):
        return None

    monkeypatch.setattr(launcher_ipc, "_connect_unix_socket", fake_unix)
    monkeypatch.setattr(launcher_ipc, "_connect_tcp_socket", fake_tcp)
    ok = launcher_ipc._setup_ipc_socket("unix", None, None, "/tmp/x")
    assert ok is True
    assert state.ipc_enabled is True
    # reset
    state.ipc_enabled = False
    state.ipc_sock = None
    state.ipc_rfile = None
    state.ipc_wfile = None

    # Test tcp path via _connect_tcp_socket
    def fake_unix_none(_p):
        return None

    def fake_tcp_sock(_h, _p):
        return FakeSock()

    monkeypatch.setattr(launcher_ipc, "_connect_unix_socket", fake_unix_none)
    monkeypatch.setattr(launcher_ipc, "_connect_tcp_socket", fake_tcp_sock)
    ok2 = launcher_ipc._setup_ipc_socket("tcp", "127.0.0.1", 12345, None)
    assert ok2 is True
    assert state.ipc_enabled is True
