"""IPC context container for debugger/server.

Encapsulates all inter-process communication state so that the main
`server.py` module isn't cluttered with a large collection of loosely
related `_ipc_*` attributes. The server continues to expose legacy
private attribute names through a property bridge for backward
compatibility with existing tests while the implementation keeps the
state here.

Threading Model:
- The reader thread is owned by IPCContext and started via start_reader().
- The thread runs as a daemon and reads messages until the connection closes.
- cleanup() will stop the reader if still running.
"""

from __future__ import annotations

import contextlib
import logging
import os
import socket as _socket
import tempfile
import threading
import time
from dataclasses import dataclass
from dataclasses import field
from multiprocessing import connection as mp_conn
from pathlib import Path
from typing import Any
from typing import Callable

from dapper.ipc.ipc_binary import HEADER_SIZE
from dapper.ipc.ipc_binary import pack_frame
from dapper.ipc.ipc_binary import read_exact
from dapper.ipc.ipc_binary import unpack_header

logger = logging.getLogger(__name__)


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

    # Reader thread management
    _reader_thread: threading.Thread | None = field(default=None, repr=False)

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

    def write_command(self, cmd_str: str) -> None:
        """Write a command string to the active IPC channel.

        Raises RuntimeError if no IPC channel is available.
        """
        if self.enabled and self.pipe_conn is not None:
            if self.binary:
                self.pipe_conn.send_bytes(pack_frame(2, cmd_str.encode("utf-8")))
            else:
                self.pipe_conn.send(cmd_str)
            return

        if self.enabled and self.wfile is not None:
            if self.binary:
                self.wfile.write(pack_frame(2, cmd_str.encode("utf-8")))  # type: ignore[arg-type]
                self.wfile.flush()  # type: ignore[call-arg]
            else:
                self.wfile.write(f"{cmd_str}\n")  # type: ignore[arg-type]
                self.wfile.flush()
            return

        msg = "IPC is required but no IPC channel is available. Cannot send command."
        raise RuntimeError(msg)

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

    def run_accept_and_read(self, handle_debug_message: Callable[[str], None]) -> None:
        """Accept one IPC connection then stream DBGP lines to handler.

        This is a blocking call that should be run in a background thread.
        It handles both pipe and socket transports, and ensures cleanup
        is performed when the connection ends.
        """
        try:
            if self.pipe_listener is not None:
                self.accept_and_read_pipe(handle_debug_message)
                return
            if self.listen_sock is not None:
                self.accept_and_read_socket(handle_debug_message)
        except Exception:
            logger.exception("IPC reader error")
        finally:
            # Ensure we clean up IPC resources before we exit
            self.disable()

    def start_reader(
        self,
        handle_debug_message: Callable[[str], None],
        *,
        accept: bool = True,
    ) -> None:
        """Start the IPC reader thread.

        This method spawns a daemon thread that reads messages from the IPC
        connection and passes them to the handler callback. The thread is
        owned by this IPCContext and will be cleaned up when cleanup() is called.

        Args:
            handle_debug_message: Callback to invoke with each received message.
            accept: If True, wait for an incoming connection before reading
                   (used after launch). If False, read from an already-connected
                   transport (used after attach).
        """
        if self._reader_thread is not None and self._reader_thread.is_alive():
            logger.warning("Reader thread already running")
            return

        target = self.run_accept_and_read if accept else self.run_attached_reader
        self._reader_thread = threading.Thread(
            target=target,
            args=(handle_debug_message,),
            daemon=True,
            name="IPCReaderThread",
        )
        self._reader_thread.start()

    def create_listener(
        self,
        transport: str | None = None,
        pipe_name: str | None = None,
    ) -> list[str]:
        """Create an IPC listener and return launcher arguments.

        Creates the appropriate listener (pipe, unix socket, or tcp socket)
        based on the transport type and platform. Returns the command-line
        arguments to pass to the debuggee launcher.

        Args:
            transport: Transport type ("pipe", "unix", or "tcp"). If None,
                      defaults to "pipe" on Windows, "unix" elsewhere.
            pipe_name: Optional pipe name for Windows named pipes.

        Returns:
            List of command-line arguments for the launcher (e.g.,
            ["--ipc", "pipe", "--ipc-pipe", "<name>"]).
        """
        default_transport = "pipe" if os.name == "nt" else "unix"
        transport = (transport or default_transport).lower()

        # Windows named pipe
        if os.name == "nt" and transport == "pipe":
            name = pipe_name or rf"\\.\pipe\dapper-{os.getpid()}-{int(time.time() * 1000)}"
            try:
                listener = mp_conn.Listener(address=name, family="AF_PIPE")
            except Exception:
                logger.exception("Failed to create named pipe listener")
                self.set_pipe_listener(None)
                return []
            self.set_pipe_listener(listener)
            return ["--ipc", "pipe", "--ipc-pipe", name]

        # Unix socket
        af_unix = getattr(_socket, "AF_UNIX", None)
        if transport == "unix" and af_unix:
            try:
                sock_name = f"dapper-{os.getpid()}-{int(time.time() * 1000)}.sock"
                unix_path = Path(tempfile.gettempdir()) / sock_name
                with contextlib.suppress(FileNotFoundError):
                    unix_path.unlink()
                listen = _socket.socket(af_unix, _socket.SOCK_STREAM)
                listen.bind(str(unix_path))
                listen.listen(1)
            except Exception:
                logger.exception("Failed to create UNIX socket; fallback to TCP")
            else:
                self.set_listen_socket(listen, unix_path)
                return ["--ipc", "unix", "--ipc-path", str(unix_path)]

        # TCP socket (fallback)
        host = "127.0.0.1"
        listen = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        with contextlib.suppress(Exception):
            listen.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        listen.bind((host, 0))
        listen.listen(1)
        _addr, port = listen.getsockname()
        self.set_listen_socket(listen)
        return ["--ipc", "tcp", "--ipc-host", host, "--ipc-port", str(port)]

    def connect(
        self,
        transport: str | None = None,
        *,
        pipe_name: str | None = None,
        unix_path: str | None = None,
        host: str | None = None,
        port: int | None = None,
    ) -> None:
        """Connect to an existing debuggee IPC endpoint.

        Args:
            transport: Transport type ("pipe", "unix", or "tcp"). If None,
                      defaults to "pipe" on Windows, "unix" elsewhere.
            pipe_name: Pipe name for Windows named pipes (required if transport="pipe").
            unix_path: Path for Unix socket (required if transport="unix").
            host: Host for TCP connection (default "127.0.0.1").
            port: Port for TCP connection (required if transport="tcp").

        Raises:
            RuntimeError: If required parameters are missing or connection fails.
        """
        default_transport = "pipe" if os.name == "nt" else "unix"
        transport = (transport or default_transport).lower()

        if os.name == "nt" and transport == "pipe":
            if not pipe_name:
                msg = "ipcPipeName required for pipe attach"
                raise RuntimeError(msg)
            try:
                conn = mp_conn.Client(address=pipe_name, family="AF_PIPE")
            except Exception as exc:
                msg = "failed to connect pipe"
                raise RuntimeError(msg) from exc
            self.enable_pipe_connection(conn, binary=False)
            return

        if transport == "unix":
            af_unix = getattr(_socket, "AF_UNIX", None)
            if not (af_unix and unix_path):
                msg = "ipcPath required for unix attach"
                raise RuntimeError(msg)
            try:
                sock = _socket.socket(af_unix, _socket.SOCK_STREAM)
                sock.connect(unix_path)
            except Exception as exc:
                msg = "failed to connect unix socket"
                raise RuntimeError(msg) from exc
            self.enable_socket_from_connected(sock, binary=False)
            return

        if transport == "tcp":
            tcp_host = host or "127.0.0.1"
            if not port:
                msg = "ipcPort required for tcp attach"
                raise RuntimeError(msg)
            try:
                sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
                sock.connect((tcp_host, int(port)))
            except Exception as exc:
                msg = "failed to connect tcp socket"
                raise RuntimeError(msg) from exc
            self.enable_socket_from_connected(sock, binary=False)
            return

        msg = f"unsupported attach transport: {transport}"
        raise RuntimeError(msg)

    def run_attached_reader(self, handle_debug_message: Callable[[str], None]) -> None:
        """Read from an attached IPC connection until closed.

        This is a blocking call that should be run in a background thread.
        It reads messages from either a pipe or socket connection and ensures
        cleanup is performed when the connection ends.
        """
        try:
            if self.pipe_conn is not None:
                self._read_pipe_messages(handle_debug_message)
            elif self.rfile is not None:
                self._read_socket_messages(handle_debug_message)
        except Exception:
            logger.exception("Attached IPC reader error")
        finally:
            self.disable()

    def _read_pipe_messages(self, handle_debug_message: Callable[[str], None]) -> None:
        """Read messages from an attached pipe connection."""
        while True:
            try:
                msg = self.pipe_conn.recv()  # type: ignore[union-attr]
            except (EOFError, OSError):
                break
            if isinstance(msg, str) and msg.startswith("DBGP:"):
                try:
                    handle_debug_message(msg[5:].strip())
                except Exception:
                    pass

    def _read_socket_messages(self, handle_debug_message: Callable[[str], None]) -> None:
        """Read messages from an attached socket connection."""
        while True:
            line = self.rfile.readline()  # type: ignore[union-attr]
            if not line:
                break
            if isinstance(line, str) and line.startswith("DBGP:"):
                try:
                    handle_debug_message(line[5:].strip())
                except Exception:
                    pass
