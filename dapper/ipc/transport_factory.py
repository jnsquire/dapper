"""Transport factory for creating IPC transport instances.

This module provides a factory pattern for creating transport-specific
connections, separating transport creation logic from the main IPC context.
"""

from __future__ import annotations

import contextlib
import logging
import os
import socket as _socket
import tempfile
import time
from dataclasses import dataclass
from multiprocessing import connection as mp_conn
from pathlib import Path
from typing import TYPE_CHECKING

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
    def _create_pipe_listener(config: TransportConfig) -> tuple[NamedPipeServerConnection, list[str]]:
        """Create a named pipe listener (Windows only)."""
        if os.name != "nt":
            raise RuntimeError("Named pipes are only supported on Windows")
        
        name = config.pipe_name or f"dapper-{os.getpid()}-{int(time.time() * 1000)}"
        full_path = rf"\\.\pipe\{name}"
        
        try:
            mp_conn.Listener(address=full_path, family="AF_PIPE")
            connection = NamedPipeServerConnection(pipe_name=name)
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
            mp_conn.Client(address=config.pipe_name, family="AF_PIPE")
            return NamedPipeServerConnection(pipe_name=config.pipe_name)
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
            return TCPServerConnection(host="127.0.0.1", port=0)
        except Exception as exc:
            msg = "Failed to connect to Unix socket"
            raise RuntimeError(msg) from exc
    
    @staticmethod
    def _create_tcp_listener(config: TransportConfig) -> tuple[TCPServerConnection, list[str]]:
        """Create a TCP socket listener."""
        host = config.host
        listen = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        
        with contextlib.suppress(Exception):
            listen.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        
        listen.bind((host, 0))
        listen.listen(1)
        _, port = listen.getsockname()
        
        connection = TCPServerConnection(host=host, port=port)
        # Store the actual socket on the connection for backward compatibility
        connection.socket = listen
        # Store the use_binary flag for the connection to know how to read/write
        connection.use_binary = config.use_binary
        args = ["--ipc", "tcp", "--ipc-host", host, "--ipc-port", str(port)]
        return connection, args
    
    @staticmethod
    def _create_tcp_connection(config: TransportConfig) -> TCPServerConnection:
        """Create a TCP socket connection."""
        if not config.port:
            raise ValueError("port is required for TCP connections")
        
        try:
            sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            sock.connect((config.host, config.port))
            return TCPServerConnection(host=config.host, port=config.port)
        except Exception as exc:
            msg = "Failed to connect to TCP socket"
            raise RuntimeError(msg) from exc
