from __future__ import annotations

# ruff: noqa: SLF001
import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dapper.adapter.debugger.py_debugger import PyDebugger
    from dapper.protocol.requests import ContinueResponseBody
    from dapper.protocol.requests import ExceptionDetails
    from dapper.protocol.requests import ExceptionInfoResponseBody
    from dapper.protocol.structures import Thread

logger = logging.getLogger(__name__)


class _PyDebuggerExecutionManager:
    """Handles execution-control and lifecycle termination operations."""

    def __init__(self, debugger: PyDebugger):
        self._debugger = debugger

    async def continue_execution(self, thread_id: int) -> ContinueResponseBody:
        if not self._debugger.program_running or self._debugger.is_terminated:
            return {"allThreadsContinued": False}

        self._debugger.stopped_event.clear()

        # Invalidate the asyncio task snapshot so stale task references do not
        # prevent garbage collection while the debuggee is running.
        try:
            self._debugger.task_registry.clear()
        except Exception:
            pass

        with self._debugger.lock:
            thread = self._debugger.get_thread(thread_id)
            if thread is not None:
                thread.is_stopped = False

        if self._debugger._backend is not None:
            return await self._debugger._backend.continue_(thread_id)

        return {"allThreadsContinued": False}

    async def next(self, thread_id: int, *, granularity: str = "line") -> None:
        if not self._debugger.program_running or self._debugger.is_terminated:
            return

        self._debugger.stopped_event.clear()

        try:
            self._debugger.task_registry.clear()
        except Exception:
            pass

        if self._debugger._backend is not None:
            await self._debugger._backend.next_(thread_id, granularity=granularity)

    async def step_in(
        self, thread_id: int, target_id: int | None = None, *, granularity: str = "line"
    ) -> None:
        if not self._debugger.program_running or self._debugger.is_terminated:
            return

        self._debugger.stopped_event.clear()

        try:
            self._debugger.task_registry.clear()
        except Exception:
            pass

        if self._debugger._backend is not None:
            await self._debugger._backend.step_in(thread_id, target_id, granularity=granularity)

    async def step_out(self, thread_id: int, *, granularity: str = "line") -> None:
        if not self._debugger.program_running or self._debugger.is_terminated:
            return

        self._debugger.stopped_event.clear()

        try:
            self._debugger.task_registry.clear()
        except Exception:
            pass

        if self._debugger._backend is not None:
            await self._debugger._backend.step_out(thread_id, granularity=granularity)

    async def pause(self, thread_id: int) -> bool:
        if not self._debugger.program_running or self._debugger.is_terminated:
            return False

        if self._debugger._backend is not None:
            return await self._debugger._backend.pause(thread_id)
        return False

    async def get_threads(self) -> list[Thread]:
        threads: list[Thread] = []
        for thread_id, thread in self._debugger.iter_threads():
            threads.append({"id": thread_id, "name": thread.name})

        # Append asyncio task pseudo-threads from the task registry.
        # snapshot_threads() re-enumerates live tasks and rebuilds the
        # per-task stack-frame cache in one pass.
        try:
            task_threads = self._debugger.task_registry.snapshot_threads()
            threads.extend(task_threads)
        except Exception:
            logger.debug("Error enumerating asyncio tasks for threads response", exc_info=True)

        return threads

    async def exception_info(self, thread_id: int) -> ExceptionInfoResponseBody:
        if self._debugger._backend is not None:
            return await self._debugger._backend.exception_info(thread_id)

        exception_details: ExceptionDetails = {
            "message": "Exception information not available",
            "typeName": "Unknown",
            "fullTypeName": "Unknown",
            "source": "Unknown",
            "stackTrace": ["Exception information not available"],
        }

        return {
            "exceptionId": "Unknown",
            "description": "Exception information not available",
            "breakMode": "unhandled",
            "details": exception_details,
        }

    async def configuration_done_request(self) -> None:
        self._debugger.configuration_done.set()

        if self._debugger._backend is not None:
            await self._debugger._backend.configuration_done()

    async def disconnect(self, terminate_debuggee: bool = False) -> None:
        if self._debugger.program_running:
            if terminate_debuggee and self._debugger.process:
                try:
                    await self.terminate()
                    await asyncio.sleep(0.5)
                    if self._debugger.process.poll() is None:
                        self._debugger.process.kill()
                except Exception:
                    logger.exception("Error terminating debuggee")

            self._debugger.program_running = False

        await self._debugger.shutdown()

    async def terminate(self) -> None:
        if self._debugger._backend is not None:
            await self._debugger._backend.terminate()

        if self._debugger.in_process:
            try:
                self._debugger.is_terminated = True
                self._debugger.program_running = False
                await self._debugger.server.send_event("terminated")
            except Exception:
                logger.exception("in-process terminate failed")
            return

        if self._debugger.program_running and self._debugger.process:
            try:
                self._debugger.process.terminate()
                self._debugger.is_terminated = True
                self._debugger.program_running = False
            except Exception:
                logger.exception("Error terminating process")

    async def restart(self) -> None:
        try:
            await self._debugger.server.send_event("terminated", {"restart": True})
        except Exception:
            logger.exception("failed to send terminated(restart=true) event")

        try:
            if self._debugger.program_running and self._debugger.process:
                try:
                    self._debugger.process.terminate()
                except Exception:
                    logger.debug("process.terminate() failed during restart")
        except Exception:
            logger.debug("error during restart termination path")

        self._debugger.is_terminated = True
        self._debugger.program_running = False

        await self._debugger.shutdown()

    async def send_command_to_debuggee(self, command: str) -> None:
        if not self._debugger.process or self._debugger.is_terminated:
            msg = "No debuggee process"
            raise RuntimeError(msg)

        try:
            await asyncio.to_thread(
                lambda: (
                    self._debugger.process.stdin.write(f"{command}\n")
                    if self._debugger.process and self._debugger.process.stdin
                    else None
                ),
            )
        except Exception:
            logger.exception("Error sending command to debuggee")
