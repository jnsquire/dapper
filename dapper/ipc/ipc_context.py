"""IPC context container for debugger/server.

Encapsulates all inter-process communication state so that the main
`server.py` module isn't cluttered with a large collection of loosely
related `_ipc_*` attributes. The server continues to expose legacy
private attribute names through a property bridge for backward
compatibility with existing tests while the implementation keeps the
state here.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Any
from typing import Callable

from dapper.ipc.ipc_binary import HEADER_SIZE
from dapper.ipc.ipc_binary import read_exact
from dapper.ipc.ipc_binary import unpack_header

# NOTE: We deliberately import framing helpers lazily inside methods to avoid
# creating hard import cycles if server.py structure changes again.


@dataclass
class IPCContext:
    enabled: bool = False
    listen_sock: Any | None = None
    sock: Any | None = None
    rfile: Any | None = None
    wfile: Any | None = None
    pipe_listener: Any | None = None  # mp_conn.Listener | None
    pipe_conn: Any | None = None  # mp_conn.Connection | None
    unix_path: Any | None = None  # Path | None (kept Any to avoid runtime import)
    binary: bool = False

    # ------------------------------
    # Runtime helpers migrated from PyDebugger
    # ------------------------------
    def cleanup(self) -> None:
        """Close IPC resources quietly and clean up files.

        Mirrors previous PyDebugger._cleanup_ipc_resources implementation.
        """
        surpressed = contextlib.suppress(Exception)

        # Close r/w files
        for f in (self.rfile, self.wfile):
            with surpressed:
                if f is not None:
                    f.close()

        # Close sockets / listeners
        with surpressed:
            if self.sock is not None:
                self.sock.close()
        with surpressed:
            if self.listen_sock is not None:
                self.listen_sock.close()

        # Unlink unix path
        with surpressed:
            if self.unix_path:
                self.unix_path.unlink()

        # Close pipe endpoints
        with surpressed:
            if self.pipe_conn is not None:
                self.pipe_conn.close()
        with surpressed:
            if self.pipe_listener is not None:
                self.pipe_listener.close()

    # Pipe reading -------------------------------------------------
    def accept_and_read_pipe(self, handle_debug_message: Callable[[str], None]) -> None:
        """Accept and read from a named pipe connection (blocking loop)."""
        if self.pipe_listener is None:  # defensive
            return
        conn = self.pipe_listener.accept()  # type: ignore[union-attr]
        self.pipe_conn = conn
        self.enabled = True
        while True:
            try:
                if self.binary:
                    data = conn.recv_bytes()
                    if not data:
                        break
                    try:
                        kind, length = unpack_header(data[:HEADER_SIZE])
                    except Exception:
                        break
                    payload = data[HEADER_SIZE : HEADER_SIZE + length]
                    if kind == 1:
                        try:
                            handle_debug_message(payload.decode("utf-8"))
                        except Exception:
                            pass
                    continue
                msg = conn.recv()
            except (EOFError, OSError):
                break
            if isinstance(msg, str) and msg.startswith("DBGP:"):
                try:
                    handle_debug_message(msg[5:].strip())
                except Exception:
                    pass

    # Socket reading -----------------------------------------------
    def accept_and_read_socket(self, handle_debug_message: Callable[[str], None]) -> None:
        """Accept and read from a TCP/UNIX socket connection (blocking loop)."""
        if self.listen_sock is None:  # defensive
            return
        conn, _ = self.listen_sock.accept()
        self.sock = conn
        makefile_args = ("rb", "wb") if self.binary else ("r", "w")
        if self.binary:
            self.rfile = conn.makefile(makefile_args[0], buffering=0)  # type: ignore[arg-type]
            self.wfile = conn.makefile(makefile_args[1], buffering=0)  # type: ignore[arg-type]
        else:
            self.rfile = conn.makefile(makefile_args[0], encoding="utf-8", newline="")
            self.wfile = conn.makefile(makefile_args[1], encoding="utf-8", newline="")
        self.enabled = True
        if self.binary:
            self._read_binary_stream(handle_debug_message)
        else:
            self._read_text_stream(handle_debug_message)

    # Internal reading helpers to reduce branch complexity
    def _read_binary_stream(self, handle_debug_message: Callable[[str], None]) -> None:
        while True:
            header = read_exact(self.rfile, HEADER_SIZE)  # type: ignore[arg-type]
            if not header:
                break
            try:
                kind, length = unpack_header(header)
            except Exception:
                break
            payload = read_exact(self.rfile, length)  # type: ignore[arg-type]
            if not payload:
                break
            if kind == 1:
                try:
                    handle_debug_message(payload.decode("utf-8"))
                except Exception:
                    pass

    def _read_text_stream(self, handle_debug_message: Callable[[str], None]) -> None:
        while True:
            line = self.rfile.readline()  # type: ignore[union-attr]
            if not line:
                break
            if isinstance(line, str) and line.startswith("DBGP:"):
                try:
                    handle_debug_message(line[5:].strip())
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Configuration helpers (migrated from PyDebugger)
    # ------------------------------------------------------------------
    def enable_pipe_connection(self, conn: Any, *, binary: bool = False) -> None:
        """Enable IPC using an already-connected pipe connection.

        This centralizes the common assignments previously performed by
        callers which mutated the IPCContext directly (pipe_conn, binary,
        enabled, pipe_listener).
        """
        # Preserve any previously-registered listener so cleanup
        # can close it. Tests expect the listener.close() to be called during
        # cleanup even when a connection is active.
        self.pipe_conn = conn
        self.binary = bool(binary)
        self.enabled = True

    def enable_socket_from_connected(self, sock: Any, *, binary: bool = False) -> None:
        """Enable IPC using an already-connected socket.

        This will populate rfile/wfile appropriately for text or binary
        transports and mark the IPC context enabled.
        """
        self.sock = sock
        if binary:
            # binary sockets use buffering=0 for raw bytes
            self.rfile = sock.makefile("rb", buffering=0)  # type: ignore[arg-type]
            self.wfile = sock.makefile("wb", buffering=0)  # type: ignore[arg-type]
        else:
            self.rfile = sock.makefile("r", encoding="utf-8", newline="")
            self.wfile = sock.makefile("w", encoding="utf-8", newline="")
        self.binary = bool(binary)
        self.enabled = True

    def set_pipe_listener(self, listener: Any) -> None:
        """Register a pipe listener that will accept a single connection later."""
        self.pipe_listener = listener

    def set_listen_socket(self, listen_sock: Any, unix_path: Any | None = None) -> None:
        """Register a listening socket that will accept a single connection later."""
        self.listen_sock = listen_sock
        if unix_path is not None:
            self.unix_path = unix_path

    def set_binary(self, binary: bool) -> None:
        """Set the binary flag on the IPC context without enabling or disabling."""
        self.binary = bool(binary)

    def enable_wfile(self, wfile: Any, *, binary: bool = False) -> None:
        """Enable IPC using an already-created writer file-like object.

        This is a small helper used by tests to simulate an outgoing text/binary
        channel without creating full socket/pipe objects. It centralizes the
        common assignments so tests don't write into the context directly.
        """
        # Clear any listening/connection handles; this represents a connected
        # writer-only transport for tests.
        self.pipe_conn = None
        self.pipe_listener = None
        self.sock = None
        self.rfile = None
        self.wfile = wfile
        self.binary = bool(binary)
        self.enabled = True

    def disable(self) -> None:
        """Disable IPC and perform cleanup."""
        self.enabled = False
        self.cleanup()
