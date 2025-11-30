"""Backward compatibility adapter for IPC.

This module provides a compatibility layer that allows existing code
to work with the new IPC architecture while we migrate gradually.
"""

from __future__ import annotations

import asyncio
import json
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
    
    def create_listener(self, transport_config: TransportConfig | None = None, transport: str | None = None, pipe_name: str | None = None) -> list[str]:
        """Create a listener (legacy compatibility method)."""
        if transport_config is None:
            transport_config = TransportConfig(
                transport=transport or "auto",
                pipe_name=pipe_name,
                use_binary=self.binary
            )
        
        try:
            self._launcher_args = self._manager.create_listener(transport_config)
            self.enabled = True
            
            # Update legacy attributes for compatibility
            connection = self._manager.connection
            
            if connection and hasattr(connection, "listener"):
                self.pipe_listener = getattr(connection, "listener", None)
            if connection and hasattr(connection, "socket"):
                self.sock = getattr(connection, "socket", None)
                self.listen_sock = self.sock
            elif connection and hasattr(connection, "server"):
                # For TCP and pipe connections, check if server is available
                server = getattr(connection, "server", None)
                if server:
                    if hasattr(server, "sockets") and server.sockets:
                        self.sock = server.sockets[0]
                    else:
                        self.sock = server
                    self.listen_sock = self.sock
                else:
                    # For pipe connections where server isn't set yet, use the connection itself
                    self.pipe_listener = connection
                    # Add address attribute for backward compatibility
                    pipe_path = getattr(connection, "pipe_path", None)
                    if pipe_path is not None:
                        self.pipe_listener.address = pipe_path
            else:
                # No compatible socket found, leave attributes as None
                pass
        except Exception:
            logger.exception("Failed to create listener")
            return []
        else:
            return self._launcher_args
    
    def connect(self, transport: str | None = None, *, pipe_name: str | None = None, unix_path: str | None = None, host: str | None = None, port: int | None = None) -> Any:
        """Connect to IPC (legacy compatibility method)."""
        transport_config = TransportConfig(
            transport=transport or "auto",
            pipe_name=pipe_name,
            path=unix_path,
            host=host,
            port=port,
            use_binary=self.binary
        )
        
        connection = self._manager.connect(transport_config)
        self.enabled = True
        
        # Set legacy attributes for backward compatibility
        if connection:
            if hasattr(connection, "listener"):
                self.pipe_listener = getattr(connection, "listener", None)
            if hasattr(connection, "socket"):
                self.sock = getattr(connection, "socket", None)
                self.listen_sock = self.sock
            elif hasattr(connection, "server"):
                # For TCP and pipe connections, check if server is available
                server = getattr(connection, "server", None)
                if server:
                    if hasattr(server, "sockets") and server.sockets:
                        self.sock = server.sockets[0]
                    else:
                        self.sock = server
                    self.listen_sock = self.sock
                else:
                    # For pipe connections where server isn't set yet, use the connection itself
                    self.pipe_listener = connection
            
            # Set connection-specific attributes
            if hasattr(connection, "connection"):
                self.pipe_conn = getattr(connection, "connection", None)
            pipe_path = getattr(connection, "pipe_path", None)
            if pipe_path is not None:
                self.unix_path = pipe_path
        
        return connection
    
    def start_reader(self, message_handler: Any, accept: bool = True) -> None:
        """Start the reader thread (legacy compatibility method)."""
        self._manager.start_reader(message_handler, accept)
    
    def write_command(self, cmd_str: str) -> None:
        """Write a command string (legacy compatibility method)."""
        if self.wfile:
            # Use legacy wfile for backward compatibility
            if self.binary:
                message = json.dumps({"command": cmd_str})
                self.wfile.write(message.encode("utf-8"))
            else:
                self.wfile.write(cmd_str)
            self.wfile.flush()
        elif self.pipe_conn:
            # Use pipe connection for backward compatibility
            if self.binary:
                message = json.dumps({"command": cmd_str})
                self.pipe_conn.send_bytes(message.encode("utf-8"))
            # For non-binary, use send method if available, otherwise send_bytes
            elif hasattr(self.pipe_conn, "send"):
                self.pipe_conn.send(cmd_str)
            else:
                self.pipe_conn.send_bytes(cmd_str.encode("utf-8"))
        else:
            # Use new IPC manager
            try:
                message = {"command": cmd_str}
                self._manager.send_message(message)
            except RuntimeError as e:
                # Convert error message to match expected pattern for tests
                if "No IPC connection available" in str(e):
                    raise RuntimeError("IPC is required") from e
                raise
    
    def cleanup(self) -> None:
        """Clean up resources (legacy compatibility method)."""
        self._manager.cleanup()
        self.enabled = False
        
        # Close legacy attributes if they have close methods
        if self.sock and hasattr(self.sock, "close"):
            self.sock.close()
        if self.pipe_listener and hasattr(self.pipe_listener, "close"):
            # Handle both sync and async close methods
            if asyncio.iscoroutinefunction(self.pipe_listener.close):
                try:
                    asyncio.get_running_loop()
                    asyncio.create_task(self.pipe_listener.close())
                except RuntimeError:
                    asyncio.run(self.pipe_listener.close())
            else:
                self.pipe_listener.close()
        if self.pipe_conn and hasattr(self.pipe_conn, "close"):
            self.pipe_conn.close()
        
        # Clear legacy attributes
        self.sock = None
        self.rfile = None
        self.wfile = None
        self.pipe_listener = None
        self.pipe_conn = None
        self.unix_path = None
        self.listen_sock = None

    async def acleanup(self) -> None:
        """Async version of cleanup for proper async contexts."""
        await self._manager.acleanup()
        self.enabled = False
        
        # Close legacy attributes if they have close methods
        if self.sock and hasattr(self.sock, "close"):
            self.sock.close()
        if self.pipe_listener and hasattr(self.pipe_listener, "close"):
            if asyncio.iscoroutinefunction(self.pipe_listener.close):
                await self.pipe_listener.close()
            else:
                self.pipe_listener.close()
        if self.pipe_conn and hasattr(self.pipe_conn, "close"):
            self.pipe_conn.close()
        
        # Clear legacy attributes
        self.sock = None
        self.rfile = None
        self.wfile = None
        self.pipe_listener = None
        self.pipe_conn = None
        self.unix_path = None
        self.listen_sock = None
    
    def disable(self) -> None:
        """Disable IPC (legacy compatibility method)."""
        self.cleanup()
    
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
    
    def enable_wfile(self, wfile: Any, *, binary: bool = False) -> None:
        """Enable wfile for writing (legacy compatibility method)."""
        self.wfile = wfile
        self.binary = binary
        self.enabled = True
