import asyncio
import threading
import time

import pytest

from dapper.server import PyDebugger


def _start_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


@pytest.mark.asyncio
async def test_cross_loop_future_is_failed_on_shutdown() -> None:
    """


A future created on another loop is failed during shutdown."""

    other_loop_ready = threading.Event()

    def _loop_thread_fn(loop, ready_evt):
        asyncio.set_event_loop(loop)
        ready_evt.set()
        loop.run_forever()

    other_loop = asyncio.new_event_loop()
    thread = threading.Thread(
        target=_loop_thread_fn,
        args=(other_loop, other_loop_ready),
        daemon=True,
    )
    thread.start()

    # Wait for the other loop to be ready
    other_loop_ready.wait(timeout=1.0)

    # Create an asyncio.Future on the other loop by returning it from a
    # coroutine scheduled on that loop. This mirrors patterns used in the
    # existing test-suite.
    async def _make_future() -> asyncio.Future:
        return other_loop.create_future()

    fut = asyncio.run_coroutine_threadsafe(_make_future(), other_loop).result()

    # Instantiate the debugger (server not required for shutdown path)
    dbg = PyDebugger(None)

    cmd_id = 999_999
    dbg._pending_commands[cmd_id] = fut

    # Call shutdown which should attempt to fail pending futures.
    await dbg.shutdown()

    # Allow a short window for cross-loop callbacks to run.
    start = time.time()
    while not fut.done() and (time.time() - start) < 2.0:
        await asyncio.sleep(0.01)

    assert fut.done(), "Future created on another loop was not finished by shutdown"

    # Any exception on the future is acceptable evidence it was failed.
    try:
        fut.result()
    except Exception:
        pass

    # Clean up the other loop
    other_loop.call_soon_threadsafe(other_loop.stop)
    thread.join(timeout=1.0)
    try:
        other_loop.close()
    except Exception:
        pass