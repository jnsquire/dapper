"""Debug Adapter Protocol server core implementation."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING
from typing import Any
from typing import Callable
from typing import cast

from dapper.adapter.debugger.py_debugger import PyDebugger
from dapper.adapter.debugger.py_debugger import _acquire_event_loop
from dapper.adapter.request_handlers import RequestHandler
from dapper.protocol.protocol import ProtocolHandler

if TYPE_CHECKING:
    from dapper.adapter.types import DAPRequest
    from dapper.ipc.connections.base import ConnectionBase
    from dapper.protocol.messages import GenericRequest

logger = logging.getLogger(__name__)


class DebugAdapterServer:
    """Server implementation that handles DAP protocol communication.

    This class provides the server interface expected by PyDebugger and handles
    the Debug Adapter Protocol communication with the client.
    """

    def __init__(
        self,
        connection: ConnectionBase,
        loop: asyncio.AbstractEventLoop | None = None,
    ):
        self.connection = connection
        self.request_handler = RequestHandler(self)
        # Prefer caller-supplied or running loop; create one only if needed.
        self.loop, _ = _acquire_event_loop(loop)  # _owns unused here
        self._debugger = PyDebugger(self, self.loop)
        self.running = False
        self.sequence_number = 0
        self.protocol_handler = ProtocolHandler()

    @property
    def debugger(self):
        """Get the debugger instance."""
        return self._debugger

    def spawn_threadsafe(self, callback: Callable[[], Any]) -> None:
        """Schedule a callback to be run on the server's event loop.

        Args:
            callback: The function to call on the server's event loop
        """
        if not self.loop.is_running():
            logger.warning("Event loop is not running, cannot schedule callback")
            return

        def _wrapped() -> None:
            try:
                callback()
            except Exception:
                logger.exception("Error in spawn_threadsafe callback")

        self.loop.call_soon_threadsafe(_wrapped)

    @property
    def next_seq(self) -> int:
        """Get the next sequence number for messages"""
        self.sequence_number += 1
        return self.sequence_number

    async def start(self) -> None:
        """Start the debug adapter server"""
        try:
            await self.connection.accept()
            self.running = True
            await self._message_loop()
        except Exception:
            logger.exception("Error starting debug adapter")
            raise
        finally:
            await self._cleanup()

    async def stop(self) -> None:
        """Stop the debug adapter server"""
        logger.info("Stopping debug adapter server")
        self.running = False
        await self._cleanup()

    async def _cleanup(self) -> None:
        """Clean up resources"""
        if self.debugger:
            await self.debugger.shutdown()

        if self.connection and self.connection.is_connected:
            await self.connection.close()

    async def _message_loop(self) -> None:
        """Main message processing loop"""
        logger.info("Starting message processing loop")
        message: dict[str, Any] | None = None
        while self.running and self.connection.is_connected:
            try:
                message = await self.connection.read_message()
                if not message:
                    logger.info("Client disconnected")
                    break

                await self._process_message(message)
            except asyncio.CancelledError:
                logger.info("Message loop cancelled")
                break
            except Exception as e:
                logger.exception("Error processing message")
                # Send error response if this was a request
                if message is not None and ("type" in message and message["type"] == "request"):
                    await self.send_error_response(message, str(e))

        logger.info("Message loop ended")

    async def _process_message(self, message: dict[str, Any]) -> None:
        """Process an incoming DAP message"""
        if "type" not in message:
            logger.error("Invalid message, missing 'type': %s", message)
            return

        message_type = message["type"]

        if message_type == "request":
            await self._handle_request(message)
        elif message_type == "response":
            logger.warning("Received unexpected response: %s", message)
        elif message_type == "event":
            logger.warning("Received unexpected event: %s", message)
        else:
            logger.error("Unknown message type: %s", message_type)

    async def _handle_request(self, request: dict[str, Any]) -> None:
        """Handle an incoming DAP request"""
        if "command" not in request:
            logger.error("Invalid request, missing 'command': %s", request)
            return

        command = request["command"]
        logger.info("Handling request: %s (seq: %s)", command, request.get("seq", "?"))

        try:
            response = await self.request_handler.handle_request(cast("DAPRequest", request))
            if response:
                await self.send_message(cast("dict[str, Any]", response))
        except Exception as e:
            logger.exception("Error handling request %s", command)
            await self.send_error_response(request, str(e))

    async def send_message(self, message: dict[str, Any]) -> None:
        """Send a DAP message to the client"""
        if not self.connection or not self.connection.is_connected:
            logger.warning("Cannot send message: No active connection")
            return

        if "seq" not in message:
            message["seq"] = self.next_seq

        try:
            await self.connection.write_message(message)
        except Exception:
            logger.exception("Error sending message")

    async def send_response(
        self, request: dict[str, Any], body: dict[str, Any] | None = None
    ) -> None:
        """Send a success response to a request"""
        response = self.protocol_handler.create_response(
            cast("GenericRequest", request), True, body
        )
        await self.send_message(cast("dict[str, Any]", response))

    async def send_error_response(self, request: dict[str, Any], error_message: str) -> None:
        """Send an error response to a request"""
        response = self.protocol_handler.create_error_response(
            cast("GenericRequest", request), error_message
        )
        await self.send_message(cast("dict[str, Any]", response))

    async def send_event(self, event_name: str, body: dict[str, Any] | None = None) -> None:
        """Send an event to the client"""
        event = self.protocol_handler.create_event(event_name, body)
        await self.send_message(cast("dict[str, Any]", event))
