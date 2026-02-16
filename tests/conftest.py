from __future__ import annotations

# isort: skip-file
import asyncio
import logging
import os
from pathlib import Path
import sys

import pytest

from dapper.utils.dev_tools import JSTestsFailedError
from dapper.utils.dev_tools import run_js_tests

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


def _close_tracked_event_loops() -> None:
    for loop in list(_created_event_loops):
        try:
            if not loop.is_closed():
                loop.close()
        except Exception:  # noqa: PERF203
            pass
    _created_event_loops.clear()


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


@pytest.fixture(autouse=True, scope="session")
def track_created_event_loops():
    """Patch `asyncio.new_event_loop` for the test session.

    Installs the tracking wrapper for the duration of the pytest session and
    restores the original function during teardown.
    """
    original_new_event_loop = asyncio.new_event_loop
    asyncio.new_event_loop = _tracking_new_event_loop
    try:
        yield
    finally:
        asyncio.new_event_loop = original_new_event_loop
        _close_tracked_event_loops()


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

    # If a loop is already running (pytest-asyncio), yield it and do not
    # attempt to shut it down here — pytest manages it.
    if running is not None:
        yield running
        return

    # Otherwise create a per-test loop and clean it up on teardown.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        yield loop
    finally:
        try:
            pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
            for t in pending:
                t.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
        except Exception:
            logger.exception("Exception during event loop teardown")
        try:
            loop.close()
        except Exception:
            logger.exception("Failed to close event loop")
        try:
            asyncio.set_event_loop(None)
        except Exception:
            logger.exception("Failed to unset event loop")


def pytest_sessionfinish(session, exitstatus):
    """Invoke extension jest tests at the end of a pytest session.

    If jest tests fail, exit the entire pytest run with the jest exit code so CI signals failure.
    """
    # If pytest already failed, continue and still run JS tests to gather all results.
    # Mark args as used to satisfy linters (plugin requires specific arg names)
    del session, exitstatus
    # Allow the `run_tests` runner to suppress running JS tests inside pytest
    skip_in_conftest = os.getenv("DAPPER_SKIP_JS_TESTS_IN_CONFTEST")
    if skip_in_conftest is None:
        # Backward compatibility for historical typo.
        skip_in_conftest = os.getenv("DAPPER_SKIP_JS_TESTS_IN_CONFT", "0")

    if str(skip_in_conftest).lower() in ("1", "true", "yes"):
        return
    try:
        run_js_tests()
    except JSTestsFailedError as exc:
        logger.exception("Extension JS tests failed")
        sys.exit(exc.returncode)
