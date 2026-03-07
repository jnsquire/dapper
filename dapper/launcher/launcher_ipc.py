"""IPC helper utilities.

Contains a minimal Pipe IO wrapper and helpers to connect unix/tcp sockets
and wire `state.ipc_*` similarly to the original launcher logic.
"""

from __future__ import annotations

import contextlib
import io
import socket
import time
from typing import TYPE_CHECKING

# Note: this module contains lightweight helpers used by tests and the
# launcher. It intentionally avoids heavy imports at module-level.

if TYPE_CHECKING:
    from multiprocessing import connection as _mpc


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


class SocketConnector:
    """Helper to connect sockets, allowing for easier testing via dependency injection."""

    def __init__(self, *, retry_attempts: int = 60, retry_delay_s: float = 0.05) -> None:
        self.retry_attempts = max(1, retry_attempts)
        self.retry_delay_s = max(0.0, retry_delay_s)

    def _connect_with_retry(
        self,
        create_socket: callable,
        connect: callable,
    ) -> socket.socket | None:
        last_error: Exception | None = None
        for attempt in range(self.retry_attempts):
            sock = None
            try:
                sock = create_socket()
                connect(sock)
            except Exception as exc:
                last_error = exc
                if sock is not None:
                    with contextlib.suppress(Exception):
                        sock.close()
                if attempt + 1 < self.retry_attempts and self.retry_delay_s > 0:
                    time.sleep(self.retry_delay_s)
                continue
            else:
                return sock

        return None

    def connect_unix(self, path: str | None) -> socket.socket | None:
        if not path:
            return None
        af_unix = getattr(socket, "AF_UNIX", None)
        if not af_unix:
            return None
        return self._connect_with_retry(
            lambda: socket.socket(af_unix, socket.SOCK_STREAM),
            lambda sock: sock.connect(path),
        )

    def connect_tcp(self, host: str | None, port: int | None) -> socket.socket | None:
        if port is None:
            return None
        try:
            _host = host or "127.0.0.1"
            _port = int(port)
        except Exception:
            return None
        return self._connect_with_retry(
            lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM),
            lambda sock: sock.connect((_host, _port)),
        )


# Default instance
connector = SocketConnector()
