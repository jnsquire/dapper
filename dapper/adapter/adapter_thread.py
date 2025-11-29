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

Threading Model:
- The adapter runs on a dedicated daemon thread with its own asyncio event loop.
- Shared state (_server, _loop, _loop_tasks, _thread_futures) is protected by _lock.
- Cross-thread communication uses threading.Event and asyncio.run_coroutine_threadsafe.
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

# Timeout for waiting on thread start/stop operations
DEFAULT_THREAD_TIMEOUT = 5.0
# Short delay before stopping the loop to allow pending callbacks to complete
LOOP_STOP_DELAY = 0.05


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

        # Lock to protect shared state accessed from multiple threads
        self._lock = threading.Lock()

        # Event/future used to publish the bound port for TCP listeners.
        self.on_port_assigned = EventEmitter()

        # Track background asyncio tasks and cross-thread futures so they can
        # be cancelled or awaited during shutdown.
        self._loop_tasks: list[asyncio.Task[Any]] = []
        self._thread_futures: list[concurrent.futures.Future[Any]] = []
        # Breakpoint controller (exposed after server is constructed)
        self.breakpoints: BreakpointController | None = None

    def _create_connection(self) -> TCPServerConnection | NamedPipeServerConnection:
        """Build connection based on configured connection type.
        
        Must be called from the adapter thread context.
        """
        if self.connection_type == "tcp":
            port = 0 if self.port is None else int(self.port)
            return TCPServerConnection(host=self.host, port=port)
        if self.connection_type == "pipe":
            name = self.pipe_name or "dapper_debug_pipe"
            return NamedPipeServerConnection(pipe_name=name)
        msg = f"Unknown connection type: {self.connection_type}"
        raise ValueError(msg)

    def _start_server_on_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Schedule the server start coroutine and mark thread as started."""
        async def _start_server() -> None:
            try:
                with self._lock:
                    server = self._server
                if server is not None:
                    await server.start()
            finally:
                self._stopped.set()

        task = loop.create_task(_start_server())
        with self._lock:
            self._loop_tasks.append(task)
        self._started.set()

    async def _start_listening_and_publish_port(
        self, connection: TCPServerConnection
    ) -> None:
        """Start TCP listener and emit the bound port."""
        try:
            await connection.start_listening()
            port = getattr(connection, "port", None)
            if port:
                self.on_port_assigned.emit(port)
        except Exception:
            logger.exception("Error starting TCP listener to obtain port")

    def _run_adapter_loop(self) -> None:
        """Main entry point for the adapter thread.
        
        Creates the event loop, initializes the server, and runs until stopped.
        """
        loop: asyncio.AbstractEventLoop | None = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            with self._lock:
                self._loop = loop

            # Build connection and server in this loop context
            connection = self._create_connection()
            server = DebugAdapterServer(connection, loop)
            with self._lock:
                self._server = server

            # Expose a breakpoint controller bound to the adapter loop
            self.breakpoints = BreakpointController(loop, server.debugger)

            # For TCP connections, start listening to obtain the bound port
            if isinstance(connection, TCPServerConnection):
                task = loop.create_task(
                    self._start_listening_and_publish_port(connection)
                )
                with self._lock:
                    self._loop_tasks.append(task)

            # Kick off server start and mark as started once queued
            self._start_server_on_loop(loop)

            # Run the event loop until explicitly stopped
            loop.run_forever()

        except Exception:
            logger.exception("Adapter thread crashed")
        finally:
            self._cleanup_loop(loop)

    def _cleanup_loop(self, loop: asyncio.AbstractEventLoop | None) -> None:
        """Clean up the event loop during shutdown."""
        if loop is None or loop.is_closed():
            with self._lock:
                self._loop = None
            return

        try:
            pending = asyncio.all_tasks(loop=loop)
            for task in pending:
                task.cancel()
            if pending:
                gathered = asyncio.gather(*pending, return_exceptions=True)
                loop.run_until_complete(gathered)
            loop.stop()
            loop.close()
        except Exception:
            logger.debug("Error during loop cleanup", exc_info=True)
        finally:
            with self._lock:
                self._loop = None

    def start(self) -> None:
        """Start the adapter thread and event loop."""
        if self._thread and self._thread.is_alive():
            return

        self._thread = threading.Thread(
            target=self._run_adapter_loop,
            name="DapperAdapterThread",
            daemon=True,
        )
        self._thread.start()
        self._started.wait(timeout=DEFAULT_THREAD_TIMEOUT)

    def stop(self, join: bool = True, timeout: float | None = DEFAULT_THREAD_TIMEOUT) -> None:
        """Request a graceful shutdown of the adapter and stop the thread.

        Schedules `server.stop()` on the adapter loop (if available), then
        stops the loop. Optionally join the thread.

        If the adapter thread is not started or already stopped, this method is a no-op.
        """
        with self._lock:
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
                with self._lock:
                    self._thread_futures.append(fut)

        self._cancel_loop_tasks(loop, timeout)
        self._cancel_thread_futures(timeout)

        # Schedule loop.stop() after a short delay to allow pending callbacks
        try:
            loop.call_soon_threadsafe(loop.call_later, LOOP_STOP_DELAY, loop.stop)
        except Exception:
            logger.debug("Error scheduling loop stop", exc_info=True)

        self._join_thread(join, timeout)

    def _cancel_loop_tasks(
        self,
        loop: asyncio.AbstractEventLoop,
        timeout: float | None,
    ) -> None:
        """Cancel all tracked asyncio tasks on the adapter loop."""
        with self._lock:
            if not self._loop_tasks:
                return
            tasks = list(self._loop_tasks)
            self._loop_tasks.clear()

        try:
            for task in tasks:
                loop.call_soon_threadsafe(task.cancel)
        except Exception:
            logger.debug("Error cancelling background tasks on loop", exc_info=True)

        async def _wait_for_all() -> None:
            await asyncio.gather(*tasks, return_exceptions=True)

        try:
            waiter = asyncio.run_coroutine_threadsafe(_wait_for_all(), loop)
            waiter.result(timeout or 1.0)
        except Exception:
            logger.debug("Timeout or error waiting for background tasks to finish", exc_info=True)

    def _cancel_thread_futures(self, timeout: float | None) -> None:
        """Cancel all tracked cross-thread futures."""
        with self._lock:
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
            # Ignore cancelled futures - they represent expected shutdown
            if future.cancelled():
                continue

            try:
                exc = future.exception()
            except concurrent.futures.CancelledError:
                # Cancelled by caller while retrieving exception - ignore
                continue
            except Exception as e:
                # Something went wrong while querying the future - log and continue
                logger.debug("Error retrieving exception from future: %s", e)
                continue

            if exc is None:
                continue

            # Non-cancelled futures that completed with an error are noteworthy
            logger.debug("Error waiting for background future to finish: %s", exc)

    def _join_thread(self, join: bool, timeout: float | None) -> None:
        if join and self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
