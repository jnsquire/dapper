"""IPC helper utilities extracted from launcher_main.

Contains a minimal Pipe IO wrapper and helpers to connect unix/tcp sockets
and wire `state.ipc_*` similarly to the original launcher logic.
"""
from __future__ import annotations

import contextlib
import io
import os
import socket
from multiprocessing import connection as _mpc

from dapper.debug_adapter_comm import state


class PipeIO(io.TextIOBase):
    def __init__(self, conn: _mpc.Connection) -> None:
        self.conn = conn

    def write(self, s: str) -> int:
        self.conn.send(s)
        return len(s)

    def flush(self) -> None:  # pragma: no cover - trivial
        return None

    def readline(self, size: int = -1) -> str:
        try:
            data = self.conn.recv()
        except (EOFError, OSError):
            return ""
        s = data
        if size is not None and size >= 0:
            return s[:size]
        return s

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.conn.close()


def _setup_ipc_pipe(pipe_name: str):
    try:
        conn = _mpc.Client(address=pipe_name, family="AF_PIPE")
    except Exception:
        return False
    state.ipc_rfile = PipeIO(conn)
    state.ipc_wfile = PipeIO(conn)
    state.ipc_enabled = True
    return True


def _connect_unix_socket(path: str | None):
    if not path:
        return None
    af_unix = getattr(os, "AF_UNIX", None)
    if not af_unix:
        return None
    sock = None
    try:
        sock = socket.socket(af_unix, socket.SOCK_STREAM)
        sock.connect(path)
    except Exception:
        if sock is not None:
            with contextlib.suppress(Exception):
                sock.close()
        return None
    else:
        return sock


def _connect_tcp_socket(host: str | None, port: int | None):
    if port is None:
        return None
    try:
        _host = host or "127.0.0.1"
        _port = int(port)
    except Exception:
        return None
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((_host, _port))
    except Exception:
        if sock is not None:
            sock.close()
        return None
    else:
        return sock


def _setup_ipc_socket(transport: str | None, host: str | None, port: int | None, path: str | None) -> bool:
    try:
        sock = None
        if transport == "unix":
            sock = _connect_unix_socket(path)
        else:
            sock = _connect_tcp_socket(host, port)
        if sock is not None:
            state.ipc_sock = sock
            state.ipc_rfile = sock.makefile("r", encoding="utf-8", newline="")
            state.ipc_wfile = sock.makefile("w", encoding="utf-8", newline="")
            state.ipc_enabled = True
            return True
    except Exception:
        return False
    return False
