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
import concurrent.futures
import logging
import threading
from typing import Any

from dapper.adapter.server import DebugAdapterServer
from dapper.core.breakpoints_controller import BreakpointController
from dapper.ipc.connections.pipe import NamedPipeServerConnection
from dapper.ipc.connections.tcp import TCPServerConnection
from dapper.utils.events import EventEmitter

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

        # Track background asyncio tasks and cross-thread futures so they can
        # be cancelled or awaited during shutdown.
        self._loop_tasks: list[asyncio.Task[Any]] = []
        self._thread_futures: list[concurrent.futures.Future[Any]] = []
        # Breakpoint controller (exposed after server is constructed)
        self.breakpoints: BreakpointController | None = None

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
            # Keep a reference to the server start task to avoid GC
            self._loop_tasks.append(task)
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
                    t = loop.create_task(_start_listen_and_publish())
                    self._loop_tasks.append(t)

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

        if loop is None:
            # Nothing to do if thread/loop not started
            self._join_thread(join, timeout)
            return

        # Schedule server.stop() if available
        if server is not None:
            try:
                fut = asyncio.run_coroutine_threadsafe(server.stop(), loop)
            except Exception:
                logger.exception("Error scheduling server.stop()")
            else:
                # keep for potential cancellation/inspection
                self._thread_futures.append(fut)

        self._cancel_loop_tasks(loop, timeout)
        self._cancel_thread_futures(timeout)

        # Schedule loop.stop() after a short delay to allow pending callbacks
        try:
            loop.call_soon_threadsafe(loop.call_later, 0.05, loop.stop)
        except Exception:
            logger.debug("Error scheduling loop stop")

        self._join_thread(join, timeout)

    def _cancel_loop_tasks(
        self,
        loop: asyncio.AbstractEventLoop,
        timeout: float | None,
    ) -> None:
        if not self._loop_tasks:
            return

        tasks = list(self._loop_tasks)
        self._loop_tasks.clear()

        try:
            for task in tasks:
                loop.call_soon_threadsafe(task.cancel)
        except Exception:
            logger.debug("Error cancelling background tasks on loop")

        async def _wait_for_all() -> None:
            await asyncio.gather(*tasks, return_exceptions=True)

        try:
            waiter = asyncio.run_coroutine_threadsafe(_wait_for_all(), loop)
            waiter.result(timeout or 1.0)
        except Exception:
            logger.debug("Timeout or error waiting for background tasks to finish")

    def _cancel_thread_futures(self, timeout: float | None) -> None:
        if not self._thread_futures:
            return

        futures = list(self._thread_futures)
        self._thread_futures.clear()

        for future in futures:
            if not future.done():
                future.cancel()

        wait_timeout = timeout or 1.0
        done, not_done = concurrent.futures.wait(
            futures,
            timeout=wait_timeout,
            return_when=concurrent.futures.ALL_COMPLETED,
        )

        if not_done:
            logger.debug(
                "Timeout waiting for %d background future(s) to finish",
                len(not_done),
            )

        for future in done:
            exc = future.exception()
            if exc is None or isinstance(exc, concurrent.futures.CancelledError):
                continue
            logger.debug("Error waiting for background future to finish: %s", exc)

    def _join_thread(self, join: bool, timeout: float | None) -> None:
        if join and self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
