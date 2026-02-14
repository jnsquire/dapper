import contextlib
import os
from pathlib import Path
import socket
import threading
import time

import pytest

from dapper.ipc.ipc_context import IPCContext
from dapper.ipc.transport_factory import TransportFactory


def test_create_listener_tcp_sets_listen_socket_and_args():
    ctx = IPCContext()
    args = ctx.create_listener(transport="tcp")
    try:
        # the listener may be adapted via SyncConnectionAdapter and therefore
        # won't be a raw socket; check that it exposes an accept() method.
        assert hasattr(ctx.listen_sock, "accept")
        assert args[:3] == ["--ipc", "tcp", "--ipc-host"]
        assert any(part.isdigit() for part in args)
    finally:
        assert ctx.listen_sock is not None
        ctx.listen_sock.close()


def test_connect_tcp_establishes_client_socket_and_enables():
    # Create listening socket and accept a client in background
    listen, _args = TransportFactory.create_tcp_listener_socket("127.0.0.1")
    try:
        addr = listen.getsockname()
        host, port = addr[0], addr[1]

        accepted = {}

        def server_accept(sock, result):
            try:
                conn, _ = sock.accept()
                # hold the connection for a short while
                result["conn"] = conn
                time.sleep(0.1)
                conn.close()
            except Exception:
                pass

        thr = threading.Thread(target=server_accept, args=(listen, accepted), daemon=True)
        thr.start()

        ctx = IPCContext()
        ctx.connect(transport="tcp", host=host, port=port)

        # After connect the context should be enabled and have rfile/wfile
        assert ctx.enabled is True
        assert ctx.sock is not None
        assert ctx.rfile is not None
        assert ctx.wfile is not None

        thr.join(timeout=1.0)
    finally:
        listen.close()


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="unix sockets not supported")
def test_create_listener_unix_sets_listen_socket_and_unix_path():
    # Use TransportFactory to create unix socket arguments and let IPCContext reuse it
    ctx = IPCContext()
    args = ctx.create_listener(transport="unix")
    try:
        # listener may be an adapter exposing accept()
        assert hasattr(ctx.listen_sock, "accept")
        assert "--ipc" in args
        assert "unix" in args
        assert ctx.unix_path is not None
    finally:
        # cleanup
        if ctx.listen_sock:
            ctx.listen_sock.close()
        with contextlib.suppress(Exception):
            Path(str(ctx.unix_path)).unlink(missing_ok=True)


@pytest.mark.skipif(os.name != "nt", reason="named pipe tests only on Windows")
def test_create_listener_pipe_sets_pipe_listener_and_args():
    ctx = IPCContext()
    args = ctx.create_listener(transport="pipe")
    assert ctx.pipe_listener is not None
    assert args[:3] == ["--ipc", "pipe", "--ipc-pipe"]


@pytest.mark.skipif(os.name != "nt", reason="named pipe attach tests only on Windows")
def test_connect_pipe_attaches_and_enables():
    # Create a pipe listener and then attach using IPCContext.connect
    listener, args = TransportFactory.create_pipe_listener_sync(None)
    try:
        _, pipe_name = args[2], args[3]
        ctx = IPCContext()

        # start accept in background
        accepted = {}

        def server_accept(lis, store):
            conn = lis.accept()
            store["conn"] = conn
            # wait for client to send then close
            try:
                with contextlib.suppress(Exception):
                    _msg = conn.recv()
            finally:
                conn.close()

        thr = threading.Thread(target=server_accept, args=(listener, accepted), daemon=True)
        thr.start()

        ctx.connect(transport="pipe", pipe_name=pipe_name)
        assert ctx.enabled is True
        assert ctx.pipe_conn is not None
        thr.join(timeout=1.0)
    finally:
        if listener:
            listener.close()
