from __future__ import annotations

import io

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
