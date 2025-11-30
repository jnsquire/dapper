import contextlib
import os
import socket
import threading
from pathlib import Path

import pytest

from dapper.ipc.transport_factory import TransportConfig
from dapper.ipc.transport_factory import TransportFactory


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
    listen, args = TransportFactory.create_tcp_listener_socket("127.0.0.1")
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
    listen, args, path = TransportFactory.create_sync_listener(cfg)
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
    listen, args, path = TransportFactory.create_unix_listener_socket()
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
