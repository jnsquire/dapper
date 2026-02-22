"""
Log forwarding module for sending structured log messages from the Python
debugger backend to the VS Code extension via IPC events.

This module provides:
- A logging.Handler subclass that forwards log records as 'dapper/log' events
- A telemetry forwarder that periodically sends frame-eval telemetry snapshots
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING
from typing import Any

from dapper.utils.threadsafe_async import SendEvent
from dapper.utils.threadsafe_async import send_event_threadsafe

if TYPE_CHECKING:
    import asyncio

logger = logging.getLogger(__name__)


class IPCLoggingHandler(logging.Handler):
    """A logging handler that forwards log records to the VS Code extension
    via the IPC event channel as 'dapper/log' events.

    Only forwards records at or above the configured level, and only for
    loggers within the 'dapper' namespace to avoid noise.
    """

    def __init__(
        self,
        send_event: SendEvent[dict[str, Any]],
        loop: asyncio.AbstractEventLoop,
        level: int = logging.INFO,
        namespace: str = "dapper",
    ):
        super().__init__(level)
        self._send_event = send_event
        self._loop = loop
        self._namespace = namespace
        self._enabled = True

    def emit(self, record: logging.LogRecord) -> None:
        if not self._enabled:
            return

        # Only forward logs from the dapper namespace
        if not record.name.startswith(self._namespace):
            return

        try:
            message = self.format(record)
            category = "console"
            if record.levelno >= logging.ERROR:
                category = "stderr"
            elif record.levelno >= logging.WARNING:
                category = "important"

            body: dict[str, Any] = {
                "message": message,
                "category": category,
                "level": record.levelname.lower(),
                "logger": record.name,
                "timestamp": record.created,
            }
            send_event_threadsafe(self._send_event, self._loop, "dapper/log", body)
        except Exception:
            # Don't let logging errors crash the debugger
            self.handleError(record)

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False


class TelemetryForwarder:
    """Periodically forwards frame-eval telemetry snapshots to the VS Code
    extension as 'dapper/telemetry' events.
    """

    def __init__(
        self,
        send_event: SendEvent[dict[str, Any]],
        loop: asyncio.AbstractEventLoop,
        interval_seconds: float = 30.0,
    ):
        self._send_event = send_event
        self._loop = loop
        self._interval = interval_seconds
        self._timer: threading.Timer | None = None
        self._running = False

    def start(self) -> None:
        """Start periodic telemetry forwarding."""
        if self._running:
            return
        self._running = True
        self._schedule_next()

    def stop(self) -> None:
        """Stop periodic telemetry forwarding and send a final snapshot."""
        self._running = False
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        # Send final snapshot
        self._send_snapshot()

    def send_now(self) -> None:
        """Send a telemetry snapshot immediately."""
        self._send_snapshot()

    def _schedule_next(self) -> None:
        if not self._running:
            return
        self._timer = threading.Timer(self._interval, self._tick)
        self._timer.daemon = True
        self._timer.start()

    def _tick(self) -> None:
        if not self._running:
            return
        self._send_snapshot()
        self._schedule_next()

    def _send_snapshot(self) -> None:
        try:
            # Import here to avoid circular imports
            from dapper._frame_eval.telemetry import telemetry  # noqa: PLC0415

            snapshot = telemetry.snapshot()
            body: dict[str, Any] = {
                "snapshot": snapshot.as_dict(),
                "timestamp": time.time(),
            }
            send_event_threadsafe(self._send_event, self._loop, "dapper/telemetry", body)
        except Exception:
            # Don't let telemetry errors crash the debugger
            logger.debug("Failed to send telemetry snapshot", exc_info=True)


def install_log_forwarder(
    send_event: SendEvent[dict[str, Any]],
    loop: asyncio.AbstractEventLoop,
    level: int = logging.INFO,
) -> IPCLoggingHandler:
    """Install the IPC logging handler on the root 'dapper' logger.

    Args:
        send_event: Async callback to send IPC events (server.send_event)
        loop: The event loop used by the debug adapter server
        level: Minimum log level to forward

    Returns:
        The installed handler (can be used to enable/disable forwarding)

    """
    handler = IPCLoggingHandler(send_event, loop, level=level)
    handler.setFormatter(logging.Formatter("%(name)s [%(levelname)s] %(message)s"))

    dapper_logger = logging.getLogger("dapper")
    dapper_logger.addHandler(handler)

    return handler
