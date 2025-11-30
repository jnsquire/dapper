"""Simplified IPC manager for better maintainability.

This module provides a cleaner, more focused IPC management interface
that delegates transport-specific logic to the factory pattern.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING
from typing import Any
from typing import Callable

from dapper.ipc.transport_factory import TransportConfig
from dapper.ipc.transport_factory import TransportFactory

if TYPE_CHECKING:
    from typing_extensions import Self

    from dapper.ipc.connections.base import ConnectionBase

logger = logging.getLogger(__name__)


class IPCManager:
    """Simplified IPC manager with clear separation of concerns.
    
    This class replaces the complex IPCContext with a cleaner interface
    that delegates transport-specific logic to the factory pattern.
    """
    
    def __init__(self) -> None:
        self._connection: ConnectionBase | None = None
        self._reader_thread: threading.Thread | None = None
        self._message_handler: Callable[[dict[str, Any]], None] | None = None
        self._enabled = False
        self._should_accept = False
    
    @property
    def is_enabled(self) -> bool:
        """Check if IPC is enabled."""
        return self._enabled and self._connection is not None
    
    @property
    def connection(self) -> ConnectionBase | None:
        """Get the active connection."""
        return self._connection
    
    def create_listener(self, config: TransportConfig) -> list[str]:
        """Create a listener and return launcher arguments.
        
        Args:
            config: Transport configuration
            
        Returns:
            List of command-line arguments for the launcher
        """
        if self._connection:
            raise RuntimeError("IPC connection already exists")
        
        self._connection, args = TransportFactory.create_listener(config)
        self._enabled = True
        return args
    
    def connect(self, config: TransportConfig) -> None:
        """Connect to an existing IPC endpoint.
        
        Args:
            config: Transport configuration
        """
        if self._connection:
            raise RuntimeError("IPC connection already exists")
        
        self._connection = TransportFactory.create_connection(config)
        self._enabled = True
    
    def start_reader(self, message_handler: Callable[[dict[str, Any]], None], accept: bool = True) -> None:
        """Start the reader thread for incoming messages.
        
        Args:
            message_handler: Function to handle incoming messages (expects dict)
            accept: Whether to accept a client connection (for listeners)
        """
        if not self._connection:
            raise RuntimeError("No IPC connection available")
        
        if self._reader_thread and self._reader_thread.is_alive():
            raise RuntimeError("Reader thread already running")
        
        self._message_handler = message_handler
        self._should_accept = accept
        
        # Start reader thread
        self._reader_thread = threading.Thread(
            target=self._read_messages,
            daemon=True,
            name="IPC-Reader"
        )
        self._reader_thread.start()
    
    def send_message(self, message: dict[str, Any]) -> None:
        """Send a message through the IPC connection.
        
        Args:
            message: Message to send
        """
        if not self._connection:
            raise RuntimeError("No IPC connection available")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._connection.write_message(message))
        finally:
            loop.close()

    def cleanup(self) -> None:
        """Clean up IPC resources."""
        # Stop reader thread
        if self._reader_thread and self._reader_thread.is_alive():
            # Reader thread will exit when connection is closed
            pass
        
        # Close connection
        if self._connection:
            # Handle both sync and async close methods
            close_method = getattr(self._connection, "close", None)
            if close_method:
                if asyncio.iscoroutinefunction(close_method):
                    # For sync cleanup, try to run async close
                    try:
                        asyncio.get_running_loop()
                        # If there's already a running loop, create a task but don't await
                        # This is for legacy sync cleanup calls
                        asyncio.create_task(close_method())
                    except RuntimeError:
                        # No running loop, safe to create new one
                        asyncio.run(close_method())
                else:
                    close_method()
            self._connection = None
        
        # Reset state
        self._enabled = False
        self._message_handler = None
        self._reader_thread = None

    async def acleanup(self) -> None:
        """Async version of cleanup for proper async contexts."""
        # Stop reader thread
        if self._reader_thread and self._reader_thread.is_alive():
            # Reader thread will exit when connection is closed
            pass
        
        # Close connection
        if self._connection:
            # Handle both sync and async close methods
            close_method = getattr(self._connection, "close", None)
            if close_method:
                if asyncio.iscoroutinefunction(close_method):
                    await close_method()
                else:
                    close_method()
            self._connection = None
        
        # Reset state
        self._enabled = False
        self._message_handler = None
        self._reader_thread = None
    
    def _read_messages(self) -> None:
        """Read messages from the connection in the reader thread."""
        if not self._connection or not self._message_handler:
            return
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            # Accept connection if needed (for listeners)
            if self._should_accept and hasattr(self._connection, "accept"):
                # Always call accept() - it will handle start_listening() if needed
                logger.debug("Accepting connection...")
                loop.run_until_complete(self._connection.accept())
                logger.debug("Connection accepted")
            
            # Read messages in a loop
            while self._enabled and self._connection:
                try:
                    message = loop.run_until_complete(self._connection.read_message())
                    if message is None:
                        # EOF - connection closed
                        logger.debug("Connection closed, exiting reader loop")
                        break
                    logger.debug("Received IPC message: %s", message)
                    self._message_handler(message)
                except Exception:
                    logger.exception("Error reading IPC message")
                    break
        finally:
            loop.close()
    
    def __enter__(self) -> Self:
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: object) -> None:
        """Context manager exit - automatically cleanup."""
        self.cleanup()
