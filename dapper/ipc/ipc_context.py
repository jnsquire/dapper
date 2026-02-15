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

import asyncio
import contextlib
from dataclasses import dataclass
from dataclasses import field
import logging
import threading
from typing import IO
from typing import TYPE_CHECKING
from typing import Callable
from typing import Union

from dapper.ipc.ipc_binary import pack_frame
from dapper.ipc.reader_helpers import read_binary_stream
from dapper.ipc.reader_helpers import read_pipe_binary
from dapper.ipc.reader_helpers import read_pipe_text
from dapper.ipc.reader_helpers import read_text_stream
from dapper.ipc.sync_adapter import SyncConnectionAdapter
from dapper.ipc.transport_factory import TransportConfig
from dapper.ipc.transport_factory import TransportFactory

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from multiprocessing.connection import Connection
    from multiprocessing.connection import Listener
    from pathlib import Path
    from socket import socket

    SocketLike = socket | SyncConnectionAdapter
    PipeConnectionLike = Connection | SyncConnectionAdapter
    PipeListenerLike = Listener | SyncConnectionAdapter
    PathLike = Path | str
else:
    SocketLike = object
    PipeConnectionLike = object
    PipeListenerLike = object
    PathLike = object

ReaderLike = Union[IO[str], IO[bytes], SyncConnectionAdapter]
WriterLike = Union[IO[str], IO[bytes]]


@dataclass
class IPCContext:
    enabled: bool = False
    listen_sock: SocketLike | None = None
    sock: SocketLike | None = None
    rfile: ReaderLike | None = None
    wfile: WriterLike | None = None
    pipe_listener: PipeListenerLike | None = None
    pipe_conn: PipeConnectionLike | None = None
    connection_adapter: SyncConnectionAdapter | None = None
    unix_path: PathLike | None = None
    binary: bool = False

    # Reader thread management
    _reader_thread: threading.Thread | None = field(default=None, repr=False)
    _reader_lock: threading.Lock = field(
        default_factory=threading.Lock,
        repr=False,
        compare=False,
    )

    # ------------------------------
    # Runtime helpers migrated from PyDebugger
    # ------------------------------
    def cleanup(self) -> None:
        """Close IPC resources quietly and clean up files.

        Mirrors previous PyDebugger._cleanup_ipc_resources implementation.
        """
        suppressed = contextlib.suppress(Exception)

        # Close r/w files
        for f in (self.rfile, self.wfile):
            with suppressed:
                if f is not None:
                    f.close()

        # Close sockets / listeners
        with suppressed:
            if self.sock is not None:
                self.sock.close()
        with suppressed:
            if self.listen_sock is not None:
                self.listen_sock.close()

        # Unlink unix path
        with suppressed:
            if self.unix_path:
                self.unix_path.unlink()

        # Close pipe endpoints
        with suppressed:
            if self.pipe_conn is not None:
                self.pipe_conn.close()
        with suppressed:
            if self.pipe_listener is not None:
                # Handle both sync and async close methods
                if asyncio.iscoroutinefunction(self.pipe_listener.close):
                    # Run async close in a new event loop
                    loop = asyncio.new_event_loop()
                    try:
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(self.pipe_listener.close())
                    finally:
                        loop.close()
                else:
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
        # Our listener may be either a SyncConnectionAdapter (wrapping
        # an async ConnectionBase) or a legacy mp_conn.Listener.
        if hasattr(self.pipe_listener, "accept") and hasattr(
            self.pipe_listener, "read_dbgp_message"
        ):
            # SyncConnectionAdapter path
            self.pipe_listener.accept()
            self.pipe_conn = self.pipe_listener
            self.enabled = True
            # read until EOF
            conn = self.pipe_conn
            assert conn is not None
            while True:
                msg = conn.read_dbgp_message()
                if msg is None:
                    break
                try:
                    handle_debug_message(msg)
                except Exception:
                    logger.exception("Error handling debug message (pipe/adapter)")
            return

        # Legacy mp_conn.Listener path
        conn = self.pipe_listener.accept()  # type: ignore[union-attr]
        self.pipe_conn = conn
        self.enabled = True
        if self.binary:
            read_pipe_binary(conn, handle_debug_message)
        else:
            read_pipe_text(conn, handle_debug_message)

    # Socket reading -----------------------------------------------
    def accept_and_read_socket(self, handle_debug_message: Callable[[str], None]) -> None:
        """Accept and read from a TCP/UNIX socket connection (blocking loop)."""
        if self.listen_sock is None:  # defensive
            return
        # If listen_sock is an adapter (SyncConnectionAdapter), accept via it
        if hasattr(self.listen_sock, "accept") and hasattr(self.listen_sock, "read_dbgp_message"):
            self.listen_sock.accept()
            self.sock = self.listen_sock
            self.enabled = True
            while True:
                msg = self.listen_sock.read_dbgp_message()
                if msg is None:
                    break
                try:
                    handle_debug_message(msg)
                except Exception:
                    logger.exception("Error handling debug message (socket/adapter)")
            return

        # Legacy socket accept path
        conn, _ = self.listen_sock.accept()
        self.sock = conn
        # attach file-like rfile/wfile and set enabled/binary state
        self._setup_socket_files(conn, binary=self.binary)
        if self.binary:
            read_binary_stream(self.rfile, handle_debug_message)
        else:
            read_text_stream(self.rfile, handle_debug_message)

    # ------------------------------------------------------------------
    # Configuration helpers (migrated from PyDebugger)
    # ------------------------------------------------------------------
    def enable_pipe_connection(self, conn: PipeConnectionLike, *, binary: bool = False) -> None:
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

    def enable_socket_from_connected(self, sock: SocketLike, *, binary: bool = False) -> None:
        """Enable IPC using an already-connected socket.

        This will populate rfile/wfile appropriately for text or binary
        transports and mark the IPC context enabled.
        """
        self.sock = sock
        # If sock is an adapter (provides read_dbgp_message), don't create
        # file-like objects — the adapter will handle reads/writes.
        if hasattr(sock, "read_dbgp_message"):
            self.rfile = None
            self.wfile = None
            self.binary = bool(binary)
            self.enabled = True
            return

        # Otherwise assume a socket-like object and set up files
        self._setup_socket_files(sock, binary=binary)
        self.binary = bool(binary)
        self.enabled = True

    def set_pipe_listener(self, listener: PipeListenerLike) -> None:
        """Register a pipe listener that will accept a single connection later."""
        self.pipe_listener = listener

    def set_listen_socket(
        self, listen_sock: SocketLike, unix_path: PathLike | None = None
    ) -> None:
        """Register a listening socket that will accept a single connection later."""
        self.listen_sock = listen_sock
        if unix_path is not None:
            self.unix_path = unix_path

    def _setup_socket_files(self, sock: SocketLike, *, binary: bool = False) -> None:
        """Helper to attach file-like rfile/wfile objects for a socket.

        Centralises the creation of rfile/wfile used by both accept and
        attach paths so behaviour is consistent and code is easier to test.
        """
        if binary:
            # binary sockets use buffering=0 for raw bytes
            self.rfile = sock.makefile("rb", buffering=0)  # type: ignore[arg-type]
            self.wfile = sock.makefile("wb", buffering=0)  # type: ignore[arg-type]
        else:
            self.rfile = sock.makefile("r", encoding="utf-8", newline="")
            self.wfile = sock.makefile("w", encoding="utf-8", newline="")
        self.binary = bool(binary)
        self.enabled = True

    def set_binary(self, binary: bool) -> None:
        """Set the binary flag on the IPC context without enabling or disabling."""
        self.binary = bool(binary)

    def enable_wfile(self, wfile: WriterLike, *, binary: bool = False) -> None:
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
        with self._reader_lock:
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
        # Prefer the canonical transport resolution in TransportFactory
        transport = TransportFactory.resolve_transport(transport)

        # Create a synchronous listener using the TransportFactory to
        # centralise behaviour across pipe, unix and tcp transports.
        cfg = TransportConfig(transport=transport, pipe_name=pipe_name)
        try:
            conn, args = TransportFactory.create_listener(cfg)
        except Exception:
            logger.exception("Failed to create listener via factory; returning empty args")
            return []

        # Wrap async ConnectionBase with synchronous adapter for legacy path
        try:
            adapter = SyncConnectionAdapter(conn)
        except Exception:
            logger.exception("Failed to create SyncConnectionAdapter; returning empty args")
            return []

        # Attach to context depending on transport
        if transport == "pipe":
            self.set_pipe_listener(adapter)
            self.connection_adapter = adapter
        else:
            # For unix/tcp the adapter accepts and then reads messages
            self.set_listen_socket(adapter)
            # capture any unix path present in args for cleanup
            if "--ipc-path" in args:
                try:
                    idx = args.index("--ipc-path")
                    self.unix_path = args[idx + 1]
                except (ValueError, IndexError):
                    logger.debug("Could not extract --ipc-path from args", exc_info=True)
            self.connection_adapter = adapter

        return args

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
        # Use centralized resolution for 'auto' / defaults
        transport = TransportFactory.resolve_transport(transport)

        cfg = TransportConfig(
            transport=transport, pipe_name=pipe_name, path=unix_path, host=host, port=port
        )
        try:
            conn = TransportFactory.create_sync_connection(cfg)
        except Exception as exc:
            msg = "failed to connect IPC transport"
            raise RuntimeError(msg) from exc

        if transport == "pipe":
            self.enable_pipe_connection(conn, binary=False)
        else:
            # tcp/unix -> socket-like
            self.enable_socket_from_connected(conn, binary=False)

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

    def _read_socket_messages(self, handle_debug_message: Callable[[str], None]) -> None:
        """Read messages from an attached socket connection."""
        # If the attached reader is an adapter, use its read_dbgp_message
        if hasattr(self.rfile, "read_dbgp_message"):
            while True:
                msg = self.rfile.read_dbgp_message()  # type: ignore[attr-defined]
                if msg is None:
                    break
                try:
                    handle_debug_message(msg)
                except Exception:
                    logger.exception("Error handling debug message (socket reader/adapter)")
            return

        # Legacy behaviour for file-like rfile
        while True:
            line = self.rfile.readline()  # type: ignore[union-attr]
            if not line:
                break
            if isinstance(line, str) and line.startswith("DBGP:"):
                try:
                    handle_debug_message(line[5:].strip())
                except Exception:
                    logger.exception("Error handling debug message (socket reader/legacy)")

    def _read_pipe_messages(self, handle_debug_message: Callable[[str], None]) -> None:
        """Read messages from an attached pipe connection.

        Handles both synchronous adapters that implement `read_dbgp_message`
        and legacy pipe connection objects (binary/text).
        """
        # Defensive check
        if self.pipe_conn is None:
            return

        # Adapter path: connection provides read_dbgp_message
        if hasattr(self.pipe_conn, "read_dbgp_message"):
            conn = self.pipe_conn
            assert conn is not None
            while True:
                msg = conn.read_dbgp_message()
                if msg is None:
                    break
                try:
                    handle_debug_message(msg)
                except Exception:
                    logger.exception("Error handling debug message (pipe reader/adapter)")
            return

        # Legacy processing for pipe connection objects
        if self.binary:
            read_pipe_binary(self.pipe_conn, handle_debug_message)
        else:
            read_pipe_text(self.pipe_conn, handle_debug_message)
