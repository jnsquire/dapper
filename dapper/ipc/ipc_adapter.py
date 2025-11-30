"""Backward compatibility adapter for IPC.

This module provides a compatibility layer that allows existing code
to work with the new IPC architecture while we migrate gradually.
"""

from __future__ import annotations

import logging
from typing import Any

from dapper.ipc.ipc_manager import IPCManager
from dapper.ipc.transport_factory import TransportConfig

logger = logging.getLogger(__name__)


class IPCContextAdapter:
    """Adapter that provides the old IPCContext interface using the new IPCManager.
    
    This maintains backward compatibility while we transition to the cleaner architecture.
    """
    
    def __init__(self) -> None:
        self._manager = IPCManager()
        self._launcher_args: list[str] = []
        
        # Legacy attributes for compatibility
        self.enabled: bool = False
        self.binary: bool = False
        self.sock: Any = None
        self.rfile: Any = None
        self.wfile: Any = None
        self.pipe_listener: Any = None
        self.pipe_conn: Any = None
        self.unix_path: Any = None
        self.listen_sock: Any = None
    
    def create_listener(self, transport: str | None = None, pipe_name: str | None = None) -> list[str]:
        """Create a listener (legacy compatibility method)."""
        config = TransportConfig(
            transport=transport or "auto",
            pipe_name=pipe_name,
            use_binary=self.binary
        )
        
        try:
            self._launcher_args = self._manager.create_listener(config)
            self.enabled = True
            
            # Update legacy attributes for compatibility
            connection = self._manager.connection
            if connection and hasattr(connection, "listener"):
                self.pipe_listener = getattr(connection, "listener", None)
            if connection and hasattr(connection, "socket"):
                self.sock = getattr(connection, "socket", None)
                self.listen_sock = self.sock
        except Exception:
            logger.exception("Failed to create listener")
            return []
        else:
            return self._launcher_args
    
    def connect(self, transport: str | None = None, *, pipe_name: str | None = None,
                unix_path: str | None = None, host: str | None = None, port: int | None = None) -> None:
        """Connect to an endpoint (legacy compatibility method)."""
        config = TransportConfig(
            transport=transport or "auto",
            pipe_name=pipe_name,
            path=unix_path,
            host=host,
            port=port,
            use_binary=self.binary
        )
        
        self._manager.connect(config)
        self.enabled = True
        
        # Update legacy attributes for compatibility
        connection = self._manager.connection
        if connection:
            if hasattr(connection, "socket"):
                self.sock = getattr(connection, "socket", None)
            if hasattr(connection, "connection"):
                self.pipe_conn = getattr(connection, "connection", None)
    
    def start_reader(self, message_handler: Any, accept: bool = True) -> None:
        """Start the reader thread (legacy compatibility method)."""
        self._manager.start_reader(message_handler, accept)
    
    def write_command(self, cmd_str: str) -> None:
        """Write a command string (legacy compatibility method)."""
        # Convert string to DAP message format
        message = {"command": cmd_str}
        self._manager.send_message(message)
    
    def cleanup(self) -> None:
        """Clean up resources (legacy compatibility method)."""
        self._manager.cleanup()
        self.enabled = False
        
        # Clear legacy attributes
        self.sock = None
        self.rfile = None
        self.wfile = None
        self.pipe_listener = None
        self.pipe_conn = None
        self.unix_path = None
        self.listen_sock = None
    
    def set_binary(self, binary: bool) -> None:
        """Set binary flag (legacy compatibility method)."""
        self.binary = binary
    
    # Additional legacy compatibility methods
    def enable_pipe_connection(self, conn: Any, *, binary: bool = False) -> None:
        """Enable pipe connection (legacy compatibility method)."""
        self.pipe_conn = conn
        self.binary = binary
        self.enabled = True
    
    def enable_socket_from_connected(self, sock: Any, *, binary: bool = False) -> None:
        """Enable socket connection (legacy compatibility method)."""
        self.sock = sock
        self.binary = binary
        self.enabled = True
    
    def set_pipe_listener(self, listener: Any) -> None:
        """Set pipe listener (legacy compatibility method)."""
        self.pipe_listener = listener
    
    def set_listen_socket(self, listen_sock: Any, unix_path: Any | None = None) -> None:
        """Set listen socket (legacy compatibility method)."""
        self.listen_sock = listen_sock
        self.unix_path = unix_path
