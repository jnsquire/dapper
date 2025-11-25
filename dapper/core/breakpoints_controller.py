"""
BreakpointController: thread-safe API for managing breakpoints while the
adapter runs on its own asyncio event loop.

This controller exposes synchronous (Future-returning) and asynchronous
methods that delegate to the underlying PyDebugger running on the adapter's
event loop.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from concurrent.futures import Future


@dataclass(frozen=True)
class LineBreakpointSpec:
    line: int
    condition: str | None = None
    hit_condition: str | None = None
    log_message: str | None = None


@dataclass(frozen=True)
class FunctionBreakpointSpec:
    name: str
    condition: str | None = None
    hit_condition: str | None = None


@dataclass(frozen=True)
class DataBreakpointSpec:
    data_id: str
    access_type: str = "write"
    condition: str | None = None
    hit_condition: str | None = None


class BreakpointController:
    """Controller that schedules breakpoint operations onto the adapter loop.

    All async methods run on the adapter loop and talk to the underlying
    PyDebugger. Synchronous counterparts return concurrent.futures.Future so
    callers on other threads can block with timeouts safely.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, debugger: Any) -> None:
        self._loop = loop
        self._debugger = debugger  # PyDebugger

    # ---- scheduling helper
    def _schedule(self, coro: Coroutine[Any, Any, Any]) -> Future[Any]:
        """Schedule a coroutine on the adapter event loop and return a Future.
        
        Args:
            coro: The coroutine to schedule.
            
        Returns:
            A Future that will be resolved with the coroutine's result.
        """
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    # ---- line/source breakpoints
    def set_source(self, path: str | Path, breakpoints: list[LineBreakpointSpec]) -> Future[Any]:
        return self._schedule(self.async_set_source(path, breakpoints))

    async def async_set_source(
        self, path: str | Path, breakpoints: list[LineBreakpointSpec]
    ) -> list[dict[str, Any]]:
        path_str = str(Path(path).resolve())
        bp_list: list[dict[str, Any]] = [
            {
                "line": bp.line,
                "condition": bp.condition,
                "hitCondition": bp.hit_condition,
                "logMessage": bp.log_message,
                "verified": True,
            }
            for bp in breakpoints
        ]
        return await self._debugger.set_breakpoints(path_str, bp_list)

    # ---- function breakpoints
    def set_function(self, breakpoints: list[FunctionBreakpointSpec]) -> Future[Any]:
        return self._schedule(self.async_set_function(breakpoints))

    async def async_set_function(
        self, breakpoints: list[FunctionBreakpointSpec]
    ) -> list[dict[str, Any]]:
        bp_funcs: list[dict[str, Any]] = [
            {
                "name": bp.name,
                "condition": bp.condition,
                "hitCondition": bp.hit_condition,
                "verified": True,
            }
            for bp in breakpoints
        ]
        return await self._debugger.set_function_breakpoints(bp_funcs)

    # ---- exception breakpoints
    def set_exception(self, filters: list[str]) -> Any:
        return self._schedule(self.async_set_exception(filters))

    async def async_set_exception(self, filters: list[str]) -> list[dict[str, Any]]:
        return await self._debugger.set_exception_breakpoints(list(filters))

    # ---- data breakpoints (Phase 1 bookkeeping)
    def data_info(self, *, name: str, frame_id: int) -> Any:
        return self._schedule(self.async_data_info(name=name, frame_id=frame_id))

    async def async_data_info(self, *, name: str, frame_id: int) -> dict[str, Any]:
        return self._debugger.data_breakpoint_info(name=name, frame_id=frame_id)

    def set_data(self, breakpoints: list[DataBreakpointSpec]) -> Any:
        return self._schedule(self.async_set_data(breakpoints))

    async def async_set_data(self, breakpoints: list[DataBreakpointSpec]) -> list[dict[str, Any]]:
        bp_list: list[dict[str, Any]] = [
            {
                "dataId": bp.data_id,
                "accessType": bp.access_type,
                "condition": bp.condition,
                "hitCondition": bp.hit_condition,
            }
            for bp in breakpoints
        ]
        # set_data_breakpoints is synchronous on the debugger; calling it
        # inside this coroutine ensures it runs on the adapter loop thread.
        return self._debugger.set_data_breakpoints(bp_list)


__all__ = [
    "BreakpointController",
    "DataBreakpointSpec",
    "FunctionBreakpointSpec",
    "LineBreakpointSpec",
]
