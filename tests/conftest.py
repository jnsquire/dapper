import asyncio
import contextlib
import sys
from pathlib import Path

import pytest

# Add the parent directory to PATH so that the dapper package can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def event_loop():
    """Ensure a usable event loop exists and is cleaned up.

    - If a loop is already running (pytest-asyncio for @pytest.mark.asyncio), reuse it.
    - Otherwise, create a per-test loop and close it on teardown.
    """
    try:
        # If we're inside an asyncio test, just reuse the active loop
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None

    if running is not None:
        # Yield the existing loop without creating another
        yield running
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        yield loop
    finally:
        # Best-effort teardown of anything bound to this loop
        try:
            if not loop.is_closed():
                try:
                    pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
                    for t in pending:
                        t.cancel()
                    if pending:
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                except Exception:
                    pass
                try:
                    loop.run_until_complete(loop.shutdown_asyncgens())
                except Exception:
                    pass
                try:
                    loop.run_until_complete(loop.shutdown_default_executor())
                except Exception:
                    pass
                try:
                    loop.close()
                except Exception:
                    pass
        finally:
            with contextlib.suppress(Exception):
                asyncio.set_event_loop(None)
