"""
Run the Debug Adapter server on a background thread.

This helper lets an application (the debugee) remain the main
thread/process while the DAP adapter runs on its own asyncio event loop
in a daemon thread.

Usage:
        runner = AdapterThread(connection_type="tcp", host="localhost", port=0)
        runner.start()
        # ... later, to stop:
        runner.stop()

Notes:
- The underlying server uses `DebugAdapterServer` and the connection types
    from `dapper.connection`.
- `stop()` schedules a graceful shutdown on the adapter loop and joins the
    thread.
"""

from __future__ import annotations

import asyncio
import logging
import threading

from dapper.connection import NamedPipeServerConnection
from dapper.connection import TCPServerConnection
from dapper.server import DebugAdapterServer

logger = logging.getLogger(__name__)


class AdapterThread:
    """Spin up the DAP adapter server on a background thread.

    This class owns an event loop running in a dedicated daemon thread. It
    starts the adapter server and provides a `stop()` method to request a
    graceful shutdown.
    """

    def __init__(
        self,
        connection_type: str,
        host: str = "localhost",
        port: int | None = 4711,
        pipe_name: str | None = None,
    ) -> None:
        self.connection_type = connection_type
        self.host = host
        self.port = port
        self.pipe_name = pipe_name

        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: DebugAdapterServer | None = None
        self._started = threading.Event()
        self._stopped = threading.Event()

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        return self._loop

    @property
    def server(self) -> DebugAdapterServer | None:
        return self._server

    def start(self) -> None:  # noqa: PLR0915 - structured into nested helpers
        """Start the adapter thread and event loop."""

        if self._thread and self._thread.is_alive():
            return

        def _create_connection() -> TCPServerConnection | NamedPipeServerConnection:
            """Build connection in thread context"""
            if self.connection_type == "tcp":
                port = 0 if self.port is None else int(self.port)
                return TCPServerConnection(host=self.host, port=port)
            if self.connection_type == "pipe":
                name = self.pipe_name or "dapper_debug_pipe"
                return NamedPipeServerConnection(pipe_name=name)
            msg = f"Unknown connection type: {self.connection_type}"
            raise ValueError(msg)

        def _start_server_on_loop(loop: asyncio.AbstractEventLoop) -> None:
            async def _start_server() -> None:
                try:
                    server = self._server
                    if server is not None:
                        await server.start()
                finally:
                    self._stopped.set()

            task = loop.create_task(_start_server())
            self._server_task = task  # type: ignore[attr-defined]
            self._started.set()

        def _run() -> None:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._loop = loop

                # Build connection and server in this loop context
                connection = _create_connection()
                self._server = DebugAdapterServer(connection, loop)

                # Kick off server start and mark as started once queued
                _start_server_on_loop(loop)

                # Run the event loop until explicitly stopped
                loop.run_forever()

            except Exception:
                logger.exception("Adapter thread crashed")
            finally:
                try:
                    # Best-effort loop shutdown
                    if self._loop is not None and not self._loop.is_closed():
                        pending = asyncio.all_tasks(loop=self._loop)
                        for t in pending:
                            t.cancel()
                        try:
                            gathered = asyncio.gather(
                                *pending,
                                return_exceptions=True,
                            )
                            self._loop.run_until_complete(gathered)
                        except Exception:
                            pass
                        self._loop.stop()
                        self._loop.close()
                except Exception:
                    pass
                finally:
                    self._loop = None

        self._thread = threading.Thread(
            target=_run,
            name="DapperAdapterThread",
            daemon=True,
        )
        self._thread.start()
        self._started.wait(timeout=5.0)

    def stop(self, join: bool = True, timeout: float | None = 5.0) -> None:
        """Request a graceful shutdown of the adapter and stop the thread.

        Schedules `server.stop()` on the adapter loop (if available), then
        stops the loop. Optionally join the thread.
        """
        loop = self._loop
        server = self._server

        if loop is not None:
            try:
                if server is not None:
                    # Schedule server.stop() coroutine on the loop
                    def _schedule_stop() -> None:
                        async def _stop() -> None:
                            try:
                                await server.stop()
                            except Exception:
                                logger.exception("Error stopping server")

                        t = asyncio.create_task(_stop())
                        # Keep a reference to prevent GC
                        self._stop_task = t  # type: ignore[attr-defined]

                    loop.call_soon_threadsafe(_schedule_stop)

                # Stop the loop itself after giving server.stop a chance
                loop.call_later(0.05, loop.stop)  # type: ignore[attr-defined]
            except Exception:
                logger.debug("Error scheduling loop stop")

        if join and self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
