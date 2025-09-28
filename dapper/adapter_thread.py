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
from typing import TYPE_CHECKING

from dapper.breakpoints_controller import BreakpointController
from dapper.connections.pipe import NamedPipeServerConnection
from dapper.connections.tcp import TCPServerConnection
from dapper.events import EventEmitter
from dapper.server import DebugAdapterServer

if TYPE_CHECKING:
    import concurrent.futures

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
        # Event used to signal when the adapter thread has stopped.
        self._stopped = threading.Event()

        # Event/future used to publish the bound port for TCP listeners.
        self.on_port_assigned = EventEmitter()

        # Future to deliver the assigned TCP port to callers. Created lazily.
        # Background task observing port; reference is kept to prevent garbage collection
        # before the task completes, ensuring port assignment notification is not interrupted.
        self._port_observer_task: asyncio.Task | None = None
        self._port_observer_task: asyncio.Task | None = None
        # Breakpoint controller (exposed after server is constructed)
        self.breakpoints: BreakpointController | None = None
        # Background task for stopping the server; kept to avoid GC
        self._stop_task: asyncio.Task | None = None
        # Server task (created when starting the server)
        self._server_task: asyncio.Task | None = None
        self._port_future: concurrent.futures.Future[int] | None = None

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

                # Expose a breakpoint controller bound to the adapter loop
                self.breakpoints = BreakpointController(loop, self._server.debugger)

                # For TCP connections we can call start_listening() to obtain
                # the bound ephemeral port immediately, before waiting for a
                # client in accept(). This avoids polling the socket.
                if isinstance(connection, TCPServerConnection):
                    # Schedule a coroutine on the adapter loop to call
                    # start_listening() and publish the bound port. We don't
                    # block here; start_listening will prepare the listening
                    # socket and allow us to observe the port before a client
                    # connects.
                    async def _start_listen_and_publish() -> None:
                        try:
                            await connection.start_listening()
                            port = getattr(connection, "port", None)
                            if port:
                                self.on_port_assigned.emit(port)
                        except Exception:
                            logger.exception("Error starting TCP listener to obtain port")

                    # keep a reference to avoid GC
                    self._port_observer_task = loop.create_task(_start_listen_and_publish())

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

        If the adapter thread is not started or already stopped, this method is a no-op.
        """
        loop = self._loop
        server = self._server

        if loop is not None:
            try:
                if server is not None:
                    # Schedule server.stop() coroutine on the loop from another thread.
                    # Use run_coroutine_threadsafe which returns a concurrent.futures.Future.
                    try:
                        fut = asyncio.run_coroutine_threadsafe(server.stop(), loop)
                        # Keep a reference to allow cancellation/inspection and avoid GC
                        self._stop_task = fut  # type: ignore[assignment]
                    except Exception:
                        logger.exception("Error scheduling server.stop()")

                # Schedule loop.stop() to run inside the loop thread after a short delay.
                # The short delay (0.05s) ensures any pending tasks (such as server.stop())
                # have a chance to complete before the loop is stopped.
                # call_soon_threadsafe is used to safely schedule loop.call_later from another thread,
                # ensuring the delayed stop is created on the loop's own thread.
                try:
                    loop.call_soon_threadsafe(loop.call_later, 0.05, loop.stop)
                except Exception:
                    logger.debug("Error scheduling loop stop")
            except Exception:
                logger.debug("Error scheduling loop stop")

        if join and self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
