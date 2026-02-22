from __future__ import annotations

import asyncio
from collections.abc import Coroutine
import contextlib
from typing import TYPE_CHECKING
from typing import Any
from typing import Callable
from typing import TypeVar

if TYPE_CHECKING:
    import concurrent.futures

T = TypeVar("T")
BodyT = TypeVar("BodyT", bound=dict[str, Any])
SendEvent = Callable[[str, BodyT | None], Coroutine[Any, Any, None]]


def schedule_coroutine_threadsafe(
    coro: Coroutine[Any, Any, T],
    loop: asyncio.AbstractEventLoop,
) -> concurrent.futures.Future[T]:
    """Schedule ``coro`` on ``loop`` from any thread and return its future.

    Raises:
        RuntimeError: If the target event loop is closed or not running.
    """
    if loop.is_closed() or not loop.is_running():
        coro.close()
        raise RuntimeError("Target event loop is not running")

    try:
        return asyncio.run_coroutine_threadsafe(coro, loop)
    except Exception:
        coro.close()
        raise


def run_coroutine_fire_and_forget_threadsafe(
    coro: Coroutine[Any, Any, T],
    loop: asyncio.AbstractEventLoop,
) -> concurrent.futures.Future[T] | None:
    """Schedule ``coro`` on ``loop`` from any thread.

    Returns the scheduled concurrent future, or ``None`` when scheduling is
    not possible (for example if the loop is closed/stopped).
    """
    try:
        future = schedule_coroutine_threadsafe(coro, loop)
    except RuntimeError:
        return None

    def _consume_future_error(done_future: concurrent.futures.Future[T]) -> None:
        with contextlib.suppress(Exception):
            done_future.result()

    future.add_done_callback(_consume_future_error)
    return future


def send_event_threadsafe(
    send_event: SendEvent[BodyT],
    loop: asyncio.AbstractEventLoop,
    event_name: str,
    body: BodyT,
) -> None:
    """Invoke an async ``send_event`` callback from non-loop threads safely."""
    run_coroutine_fire_and_forget_threadsafe(send_event(event_name, body), loop)
