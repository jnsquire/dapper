"""Simplified IPC manager for better maintainability.

This module provides a cleaner, more focused IPC management interface
that delegates transport-specific logic to the factory pattern.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from typing import TYPE_CHECKING
from typing import Any
from typing import Callable
from typing import cast

from dapper.ipc.transport_factory import TransportConfig
from dapper.ipc.transport_factory import TransportFactory
from dapper.utils.logging_levels import TRACE

if TYPE_CHECKING:
    from typing_extensions import Self

    from dapper.ipc.connections.base import ConnectionBase

logger = logging.getLogger(__name__)


def _is_expected_loop_shutdown_error(exc: BaseException) -> bool:
    """Return whether an exception represents expected loop shutdown."""
    if isinstance(exc, (asyncio.CancelledError, SystemExit)):
        return True
    if not isinstance(exc, RuntimeError):
        return False
    message = str(exc)
    return "Event loop stopped before Future completed" in message


async def _await_close_result(close_result: object) -> None:
    await cast("Any", close_result)


class IPCManager:
    """IPC manager with clear separation of concerns.

    Delegates transport-specific logic to the factory pattern and
    provides lifecycle management for IPC connections.
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

    def start_reader(
        self,
        message_handler: Callable[[dict[str, Any]], None],
        accept: bool = True,
    ) -> None:
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
            name="IPC-Reader",
        )
        self._reader_thread.start()

    async def send_message(self, message: dict[str, Any]) -> None:
        """Send a message through the IPC connection.

        Args:
            message: Message to send

        """
        if not self._connection:
            raise RuntimeError("No IPC connection available")

        await self._connection.write_message(message)

    def cleanup(self) -> None:
        """Clean up IPC resources.

        Closes the connection synchronously.  When an asyncio event loop is
        already running we schedule the async close and **wait** for it to
        finish (via ``run_coroutine_threadsafe``) so that the connection is
        fully torn down before we null the reference.  Previously the task
        was fire-and-forget which caused a race where the connection was
        set to ``None`` before the close coroutine had finished.
        """
        # Stop reader thread
        if self._reader_thread and self._reader_thread.is_alive():
            # Reader thread will exit when connection is closed
            pass

        # Close connection
        if self._connection:
            # Handle both sync and async close methods
            close_method = getattr(self._connection, "close", None)
            if close_method:
                close_result = close_method()
                if inspect.isawaitable(close_result):
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        loop = None

                    if loop is not None and loop.is_running():
                        # Schedule on the running loop and wait for completion
                        # (with a timeout to avoid deadlocking shutdown).
                        future = asyncio.run_coroutine_threadsafe(
                            _await_close_result(close_result), loop
                        )
                        try:
                            future.result(timeout=5.0)
                        except Exception:
                            logger.debug(
                                "Timed out or failed waiting for async close", exc_info=True
                            )
                    else:
                        # No running loop — safe to create a throwaway one.
                        asyncio.run(_await_close_result(close_result))
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
                close_result = close_method()
                if inspect.isawaitable(close_result):
                    await close_result
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
            # Accept connection if needed (for listeners).
            # ``ConnectionBase`` guarantees an ``accept()`` method, so we
            # no longer need to guard with ``hasattr``.  The flag comes from
            # ``start_reader(accept=True)``, which is the normal path for a
            # listener; clients pass ``accept=False`` and the call is skipped.
            if self._should_accept:
                # Always call accept() - it will handle start_listening() if needed
                logger.debug("Accepting connection...")
                try:
                    loop.run_until_complete(self._connection.accept())
                except BaseException as exc:
                    if _is_expected_loop_shutdown_error(exc):
                        logger.debug("Reader thread exiting during accept() shutdown")
                        return
                    logger.exception("Error accepting IPC connection")
                    return
                logger.debug("Connection accepted")

            # Read messages in a loop
            while self._enabled and self._connection:
                try:
                    message = loop.run_until_complete(self._connection.read_message())
                    if message is None:
                        # EOF - connection closed
                        logger.debug("Connection closed, exiting reader loop")
                        break
                    logger.log(TRACE, "Received IPC message: %s", message)
                    self._message_handler(message)
                except BaseException as exc:
                    if _is_expected_loop_shutdown_error(exc):
                        logger.debug("Reader thread exiting during read_message() shutdown")
                        break
                    logger.exception("Error reading IPC message")
                    break
        finally:
            asyncio.set_event_loop(None)
            loop.close()

    def __enter__(self) -> Self:
        """Context manager entry."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Context manager exit - automatically cleanup."""
        self.cleanup()
