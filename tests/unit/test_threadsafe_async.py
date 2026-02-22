from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest

from dapper.utils.threadsafe_async import run_coroutine_fire_and_forget_threadsafe
from dapper.utils.threadsafe_async import schedule_coroutine_threadsafe
from dapper.utils.threadsafe_async import send_event_threadsafe


def test_schedule_coroutine_threadsafe_returns_result(
    background_event_loop: asyncio.AbstractEventLoop,
) -> None:
    async def _value() -> int:
        return 7

    future = schedule_coroutine_threadsafe(_value(), background_event_loop)
    assert future.result(timeout=1.0) == 7


def test_schedule_coroutine_threadsafe_raises_when_loop_not_running() -> None:
    loop = asyncio.new_event_loop()

    async def _value() -> int:
        return 1

    coro = _value()
    with pytest.raises(RuntimeError, match="not running"):
        schedule_coroutine_threadsafe(coro, loop)
    assert coro.cr_frame is None

    loop.close()


def test_run_coroutine_fire_and_forget_returns_none_when_loop_not_running() -> None:
    loop = asyncio.new_event_loop()

    async def _value() -> int:
        return 1

    coro = _value()
    future = run_coroutine_fire_and_forget_threadsafe(coro, loop)

    assert future is None
    assert coro.cr_frame is None

    loop.close()


def test_send_event_threadsafe_schedules_event(
    background_event_loop: asyncio.AbstractEventLoop,
) -> None:
    seen: list[tuple[str, dict[str, Any] | None]] = []
    done = threading.Event()

    async def _send_event(event_name: str, body: dict[str, Any] | None = None) -> None:
        seen.append((event_name, body))
        done.set()

    send_event_threadsafe(_send_event, background_event_loop, "evt", {"x": 1})

    assert done.wait(timeout=1.0)
    assert seen == [("evt", {"x": 1})]
