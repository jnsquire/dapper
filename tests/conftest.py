import asyncio
import atexit
import logging
import sys
from pathlib import Path

import pytest

logger = logging.getLogger(__name__)

# Track event loops created via asyncio.new_event_loop so tests can ensure
# they are explicitly closed. This prevents relying on CPython's GC and the
# loop destructor which may run during interpreter shutdown and observe
# partially torn-down objects, leading to UnraisableExceptionWarning.
_created_event_loops: set[asyncio.AbstractEventLoop] = set()
_orig_new_event_loop = asyncio.new_event_loop


def _tracking_new_event_loop() -> asyncio.AbstractEventLoop:
    # On Windows, creating a new event loop under the Proactor policy may
    # attempt to create a socketpair which can fail with WinError 10055 in
    # constrained environments. To avoid that intermittent failure we
    # temporarily force the selector policy for the duration of loop
    # creation. This ensures new_event_loop returns a selector-based loop
    # regardless of the global policy used by pytest plugins.
    prev_policy = None
    try:
        if sys.platform.startswith("win"):
            try:
                prev_policy = asyncio.get_event_loop_policy()
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            except Exception:
                prev_policy = None

        loop = _orig_new_event_loop()
        _created_event_loops.add(loop)
        return loop
    finally:
        if prev_policy is not None:
            try:
                asyncio.set_event_loop_policy(prev_policy)
            except Exception:
                pass


asyncio.new_event_loop = _tracking_new_event_loop


def _close_tracked_event_loops() -> None:
    for loop in list(_created_event_loops):
        try:
            if not loop.is_closed():
                loop.close()
        except Exception:  # noqa: PERF203
            pass
    _created_event_loops.clear()


atexit.register(_close_tracked_event_loops)

# On Windows the default event loop policy uses ProactorEventLoop which
# attempts to create a socketpair during new_event_loop(). On some Windows
# environments this can fail with WinError 10055 due to limited socket
# resources. For test runs we prefer the selector policy which avoids the
# fallback socketpair path and is sufficient for unit tests.
if sys.platform.startswith("win"):
    try:
        from asyncio import WindowsSelectorEventLoopPolicy

        asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())
    except Exception:
        # If not available or fails, continue with default policy
        pass


# Use a fixture to temporarily add the parent directory to sys.path for tests
@pytest.fixture(autouse=True, scope="session")
def add_parent_to_syspath():
    parent_dir = str(Path(__file__).resolve().parent.parent)
    sys.path.insert(0, parent_dir)
    yield
    try:
        sys.path.remove(parent_dir)
    except ValueError:
        pass


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
        # Best-effort teardown of anything bound to this loop
        pending = None
        try:
            if not running.is_closed():
                pending = [t for t in asyncio.all_tasks(running) if not t.done()]
                for t in pending:
                    t.cancel()
                if pending:
                    running.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                running.run_until_complete(running.shutdown_asyncgens())
                running.run_until_complete(running.shutdown_default_executor())
                running.close()
        except Exception:
            pending = [t for t in asyncio.all_tasks(running) if not t.done()]
        finally:
            if pending:
                results = running.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
                for result in results:
                    if isinstance(result, Exception):
                        logger.error(f"Unhandled exception during event loop teardown: {result}")

            try:
                asyncio.set_event_loop(None)
            except Exception:
                logger.exception("Suppressed exception when resetting event loop")
