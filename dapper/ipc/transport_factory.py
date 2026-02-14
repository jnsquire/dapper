"""Transport factory for creating IPC transport instances.

This module provides a factory pattern for creating transport-specific
connections, separating transport creation logic from the main IPC context.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
import logging
from multiprocessing import connection as mp_conn
import os
from pathlib import Path
import socket as _socket
import tempfile
import time
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from dapper.ipc.connections.base import ConnectionBase

from dapper.ipc.connections.pipe import NamedPipeServerConnection
from dapper.ipc.connections.tcp import TCPServerConnection

logger = logging.getLogger(__name__)


@dataclass
class TransportConfig:
    """Configuration for IPC transport creation."""

    transport: str = "auto"  # "auto", "pipe", "unix", "tcp"
    host: str | None = None
    port: int | None = None
    path: str | None = None
    pipe_name: str | None = None
    use_binary: bool = True


class TransportFactory:
    """Factory for creating transport-specific connections."""

    @staticmethod
    def get_default_transport() -> str:
        """Get the default transport for the current platform."""
        return "pipe" if os.name == "nt" else "unix"

    @staticmethod
    def resolve_transport(transport: str | None) -> str:
        """Resolve transport type, handling 'auto' and defaults."""
        if transport is None or transport == "auto":
            return TransportFactory.get_default_transport()
        return transport.lower()

    @staticmethod
    def create_listener(config: TransportConfig) -> tuple[ConnectionBase, list[str]]:
        """Create a listener connection and launcher arguments.

        Args:
            config: Transport configuration

        Returns:
            Tuple of (connection, launcher_args)
        """
        transport = TransportFactory.resolve_transport(config.transport)

        if transport == "pipe":
            return TransportFactory._create_pipe_listener(config)
        if transport == "unix":
            return TransportFactory._create_unix_listener(config)
        if transport == "tcp":
            return TransportFactory._create_tcp_listener(config)

        msg = f"Unsupported transport: {transport}"
        raise ValueError(msg)

    @staticmethod
    def create_connection(config: TransportConfig) -> ConnectionBase:
        """Create a client connection to an existing endpoint.

        Args:
            config: Transport configuration

        Returns:
            Connection instance
        """
        transport = TransportFactory.resolve_transport(config.transport)

        if transport == "pipe":
            return TransportFactory._create_pipe_connection(config)
        if transport == "unix":
            return TransportFactory._create_unix_connection(config)
        if transport == "tcp":
            return TransportFactory._create_tcp_connection(config)

        msg = f"Unsupported transport: {transport}"
        raise ValueError(msg)

    @staticmethod
    def _create_pipe_listener(
        config: TransportConfig,
    ) -> tuple[NamedPipeServerConnection, list[str]]:
        """Create a named pipe listener (Windows only)."""
        if os.name != "nt":
            raise RuntimeError("Named pipes are only supported on Windows")

        name = config.pipe_name or f"dapper-{os.getpid()}-{int(time.time() * 1000)}"
        full_path = rf"\\.\pipe\{name}"

        try:
            listener = mp_conn.Listener(address=full_path, family="AF_PIPE")
            connection = NamedPipeServerConnection(pipe_name=name)
            connection.listener = listener  # keep reference so caller can close it
            args = ["--ipc", "pipe", "--ipc-pipe", full_path]
        except Exception as e:
            logger.exception("Failed to create named pipe listener")
            msg = "Failed to create pipe listener"
            raise RuntimeError(msg) from e
        else:
            return connection, args

    @staticmethod
    def _create_pipe_connection(config: TransportConfig) -> NamedPipeServerConnection:
        """Create a named pipe connection (Windows only)."""
        if os.name != "nt":
            raise RuntimeError("Named pipes are only supported on Windows")

        if not config.pipe_name:
            raise ValueError("pipe_name is required for pipe connections")

        try:
            client = mp_conn.Client(address=config.pipe_name, family="AF_PIPE")
            connection = NamedPipeServerConnection(pipe_name=config.pipe_name)
            connection.client = client  # keep reference so caller can close it
            return connection
        except Exception as exc:
            msg = "Failed to connect to pipe"
            raise RuntimeError(msg) from exc

    @staticmethod
    def _create_unix_listener(config: TransportConfig) -> tuple[TCPServerConnection, list[str]]:
        """Create a Unix socket listener."""
        af_unix = getattr(_socket, "AF_UNIX", None)
        if not af_unix:
            logger.warning("Unix sockets not supported, falling back to TCP")
            return TransportFactory._create_tcp_listener(config)

        try:
            sock_name = f"dapper-{os.getpid()}-{int(time.time() * 1000)}.sock"
            unix_path = Path(tempfile.gettempdir()) / sock_name

            # Clean up any existing socket file
            with contextlib.suppress(FileNotFoundError):
                unix_path.unlink()

            listen = _socket.socket(af_unix, _socket.SOCK_STREAM)
            listen.bind(str(unix_path))
            listen.listen(1)

            connection = TCPServerConnection(host="127.0.0.1", port=0)
            # For consumers that need the actual listen socket, expose it on
            # the connection for backward compatibility
            connection.socket = listen
            args = ["--ipc", "unix", "--ipc-path", str(unix_path)]
        except Exception:
            logger.exception("Failed to create Unix socket, falling back to TCP")
            return TransportFactory._create_tcp_listener(config)
        else:
            return connection, args

    @staticmethod
    def _create_unix_connection(config: TransportConfig) -> TCPServerConnection:
        """Create a Unix socket connection."""
        af_unix = getattr(_socket, "AF_UNIX", None)
        if not af_unix:
            raise RuntimeError("Unix sockets not supported on this platform")

        if not config.path:
            raise ValueError("path is required for Unix socket connections")

        try:
            sock = _socket.socket(af_unix, _socket.SOCK_STREAM)
            sock.connect(config.path)
            connection = TCPServerConnection(host="127.0.0.1", port=0)
            connection.socket = sock  # keep reference so caller can use/close it
            return connection
        except Exception as exc:
            msg = "Failed to connect to Unix socket"
            raise RuntimeError(msg) from exc

    @staticmethod
    def _create_tcp_listener(config: TransportConfig) -> tuple[TCPServerConnection, list[str]]:
        """Create a TCP socket listener."""
        host = config.host
        # Create an actual TCP listening socket (ephemeral port)
        listen, args = TransportFactory.create_tcp_listener_socket(host)
        _, port = listen.getsockname()

        effective_host = listen.getsockname()[0]
        connection = TCPServerConnection(host=effective_host, port=port)
        # Store the actual socket on the connection for backward compatibility
        connection.socket = listen
        # Store the use_binary flag for the connection to know how to read/write
        connection.use_binary = config.use_binary
        # args already returned by create_tcp_listener_socket contain the
        # resolved host and ephemeral port, reuse them
        return connection, args

    @staticmethod
    def create_tcp_listener_socket(host: str | None = None) -> tuple[_socket.socket, list[str]]:
        """Create a raw TCP listening socket and return (socket, launcher_args).

        This helper centralises the low level socket creation used by both
        the asynchronous Connection-based path and the legacy synchronous
        IPCContext. It binds an ephemeral port and returns the socket plus
        arguments for launching/debuggee invocation.
        """
        host = host or "127.0.0.1"
        listen = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        with contextlib.suppress(Exception):
            listen.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        listen.bind((host, 0))
        listen.listen(1)
        _, port = listen.getsockname()
        args = ["--ipc", "tcp", "--ipc-host", host, "--ipc-port", str(port)]
        return listen, args

    @staticmethod
    def create_tcp_client_socket(host: str | None, port: int | None) -> _socket.socket:
        """Create and connect a TCP client socket to (host, port).

        Returns a connected socket or raises the underlying socket error.
        """
        if not port:
            raise ValueError("port is required for TCP client sockets")
        sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        sock.connect((host or "127.0.0.1", int(port)))
        return sock

    @staticmethod
    def create_unix_listener_socket(
        path: str | None = None,
    ) -> tuple[_socket.socket, list[str], Path]:
        """Create a UNIX-domain listening socket and return (socket, args, path).

        The path is created in the system tempdir if not supplied. This mirrors
        the logic previously duplicated in IPCContext, centralising creation
        so both sync and async callers can reuse a single implementation.
        """
        af_unix = getattr(_socket, "AF_UNIX", None)
        if not af_unix:
            raise RuntimeError("Unix sockets not supported on this platform")

        sock_name = path or f"dapper-{os.getpid()}-{int(time.time() * 1000)}.sock"
        unix_path = Path(tempfile.gettempdir()) / sock_name

        # Clean up any existing socket file
        with contextlib.suppress(FileNotFoundError):
            unix_path.unlink()

        listen = _socket.socket(af_unix, _socket.SOCK_STREAM)
        listen.bind(str(unix_path))
        listen.listen(1)

        args = ["--ipc", "unix", "--ipc-path", str(unix_path)]
        return listen, args, unix_path

    @staticmethod
    def create_unix_client_socket(path: str) -> _socket.socket:
        """Create and connect a UNIX-domain socket client to the given path."""
        af_unix = getattr(_socket, "AF_UNIX", None)
        if not af_unix:
            raise RuntimeError("Unix sockets not supported on this platform")

        if not path:
            raise ValueError("path is required for unix client sockets")

        sock = _socket.socket(af_unix, _socket.SOCK_STREAM)
        sock.connect(path)
        return sock

    @staticmethod
    def create_pipe_listener_sync(
        pipe_name: str | None = None,
    ) -> tuple[mp_conn.Listener | None, list[str]]:
        """Create a synchronous named-pipe Listener for use by legacy code.

        Returns the raw mp_conn.Listener and launcher args. On non-windows
        platforms the pipe listener creation will raise (matching prior
        behaviour where pipes were Windows-only in the sync path).
        """
        if os.name != "nt":
            raise RuntimeError("Named pipes are only supported on Windows")

        name = pipe_name or f"dapper-{os.getpid()}-{int(time.time() * 1000)}"
        full_path = rf"\\.\pipe\{name}"
        listener = mp_conn.Listener(address=full_path, family="AF_PIPE")
        return listener, ["--ipc", "pipe", "--ipc-pipe", full_path]

    @staticmethod
    def create_pipe_client_sync(pipe_name: str) -> mp_conn.Connection:
        """Create a synchronous pipe client connection to the given pipe name."""
        if os.name != "nt":
            raise RuntimeError("Named pipes are only supported on Windows")

        if not pipe_name:
            raise ValueError("pipe_name is required for pipe connections")

        return mp_conn.Client(address=pipe_name, family="AF_PIPE")

    @staticmethod
    def create_sync_listener(config: TransportConfig) -> tuple[Any, list[str], Any | None]:
        """Create a blocking/synchronous listener for the given transport.

        Returns a tuple of (listener_obj, launcher_args, unix_path_or_None).
        listener_obj will be an mp_conn.Listener for pipe or a bound socket for
        unix/tcp. unix_path_or_None communicates the path when a UNIX listener
        is created so callers can remove the socket file on cleanup.
        """
        transport = TransportFactory.resolve_transport(config.transport)

        if transport == "pipe":
            listener, args = TransportFactory.create_pipe_listener_sync(config.pipe_name)
            return listener, args, None

        if transport == "unix":
            listen, args, unix_path = TransportFactory.create_unix_listener_socket(config.path)
            return listen, args, unix_path

        if transport == "tcp":
            listen, args = TransportFactory.create_tcp_listener_socket(config.host)
            return listen, args, None

        msg = f"Unsupported transport: {transport}"
        raise ValueError(msg)

    @staticmethod
    def create_sync_connection(config: TransportConfig) -> Any:
        """Create a blocking client connection for the given transport.

        Returns a connected object (mp_conn.Connection for pipe, socket for tcp/unix)
        """
        transport = TransportFactory.resolve_transport(config.transport)

        if transport == "pipe":
            if not config.pipe_name:
                raise ValueError("pipe_name is required for pipe connections")
            return TransportFactory.create_pipe_client_sync(config.pipe_name)

        if transport == "unix":
            if not config.path:
                raise ValueError("path is required for unix client sockets")
            return TransportFactory.create_unix_client_socket(config.path)

        if transport == "tcp":
            if not config.port:
                raise ValueError("port is required for tcp client sockets")
            return TransportFactory.create_tcp_client_socket(config.host, config.port)

        msg = f"Unsupported transport: {transport}"
        raise ValueError(msg)

    @staticmethod
    def _create_tcp_connection(config: TransportConfig) -> TCPServerConnection:
        """Create a TCP socket connection."""
        if not config.port:
            raise ValueError("port is required for TCP connections")

        try:
            sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            sock.connect((config.host, config.port))
            connection = TCPServerConnection(host=config.host, port=config.port)
            connection.socket = sock  # keep reference so caller can use/close it
            return connection
        except Exception as exc:
            msg = "Failed to connect to TCP socket"
            raise RuntimeError(msg) from exc
