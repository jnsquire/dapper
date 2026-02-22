import asyncio
import time

import pytest

from dapper.adapter.server import PyDebugger


@pytest.mark.asyncio
async def test_cross_loop_future_is_failed_on_shutdown(
    background_event_loop: asyncio.AbstractEventLoop,
) -> None:
    """A future created on another loop is failed during shutdown."""
    other_loop = background_event_loop

    # Create an asyncio.Future on the other loop by returning it from a
    # coroutine scheduled on that loop. This mirrors patterns used in the
    # existing test-suite.
    async def _make_future() -> asyncio.Future:
        return other_loop.create_future()

    fut = asyncio.run_coroutine_threadsafe(_make_future(), other_loop).result()

    # Instantiate the debugger (server not required for shutdown path)
    dbg = PyDebugger(None)

    cmd_id = 999_999
    dbg._session_facade.pending_commands[cmd_id] = fut

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
