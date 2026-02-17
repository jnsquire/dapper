"""Synchronous adapter for asyncio ConnectionBase objects.

This adapter runs a private asyncio event loop in a background thread and
exposes blocking methods that call into the async ConnectionBase methods.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from dapper.ipc.connections.base import ConnectionBase

logger = logging.getLogger(__name__)


class SyncConnectionAdapter:
    """Wrap a ConnectionBase and expose blocking accept/read/write/close.

    This creates a private event loop running in a background thread and
    uses asyncio.run_coroutine_threadsafe to execute ConnectionBase
    coroutines.
    """

    def __init__(self, conn: ConnectionBase) -> None:
        self._conn = conn
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._loop_ready = threading.Event()
        self._start_loop()

    def _start_loop(self) -> None:
        def _run() -> None:
            loop = asyncio.new_event_loop()
            self._loop = loop
            asyncio.set_event_loop(loop)
            self._loop_ready.set()
            loop.run_forever()

        self._thread = threading.Thread(target=_run, daemon=True, name="SyncConnAdapterLoop")
        self._thread.start()

        # Wait for loop to appear without busy-waiting.
        if not self._loop_ready.wait(timeout=1.0):
            raise RuntimeError("Timed out waiting for adapter event loop to start")

    def _run_coro(self, coro: Any) -> Any:
        if not self._loop:
            raise RuntimeError("Adapter loop not started")
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result()

    def accept(self) -> None:
        return self._run_coro(self._conn.accept())

    def read_message(self) -> dict | None:
        return self._run_coro(self._conn.read_message())

    def write_message(self, message: dict[str, Any]) -> None:
        return self._run_coro(self._conn.write_message(message))

    def close(self) -> None:
        try:
            if self._loop and self._conn:
                self._run_coro(self._conn.close())
        finally:
            if self._loop:
                loop = self._loop
                # Stop the loop from another thread
                loop.call_soon_threadsafe(loop.stop)
            if self._thread:
                self._thread.join(timeout=1.0)
