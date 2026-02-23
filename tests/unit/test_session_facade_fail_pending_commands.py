from __future__ import annotations

import asyncio
import threading
from typing import Callable

from dapper.adapter.debugger.session import _PyDebuggerSessionFacade


class _FakeLoop:
    def __init__(self) -> None:
        self.callbacks: list[Callable[[], None]] = []

    def call_soon_threadsafe(self, callback: Callable[[], None]) -> None:
        self.callbacks.append(callback)


class _FakeFuture:
    def __init__(self, loop: _FakeLoop) -> None:
        self._loop = loop
        self._done = False
        self.exceptions: list[BaseException] = []

    def done(self) -> bool:
        return self._done

    def get_loop(self) -> _FakeLoop:
        return self._loop

    def set_exception(self, error: BaseException) -> None:
        self.exceptions.append(error)
        self._done = True


def test_fail_pending_commands_schedules_on_future_loop() -> None:
    loop = asyncio.new_event_loop()
    try:
        facade = _PyDebuggerSessionFacade(threading.RLock(), loop)

        fake_loop = _FakeLoop()
        future = _FakeFuture(fake_loop)
        facade.pending_commands = {123: future}  # type: ignore[assignment]

        err = RuntimeError("Debugger shutdown")
        facade.fail_pending_commands(err)

        assert facade.pending_commands == {}
        assert len(fake_loop.callbacks) == 1
        assert future.exceptions == []

        fake_loop.callbacks[0]()

        assert future.done()
        assert future.exceptions == [err]
    finally:
        loop.close()
