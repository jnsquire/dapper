from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import ctypes
from datetime import datetime
from datetime import timezone
import faulthandler
import logging
import os
from pathlib import Path
import sys
import threading
import time
from typing import TYPE_CHECKING

import pytest

from dapper.utils.dev_tools import JSTestsFailedError
from dapper.utils.dev_tools import run_js_tests

if TYPE_CHECKING:
    from collections.abc import Generator

logger = logging.getLogger(__name__)


def _shutdown_trace_enabled() -> bool:
    return str(os.getenv("DAPPER_PYTEST_SHUTDOWN_TRACE", "0")).lower() in (
        "1",
        "true",
        "yes",
    )


def _faulthandler_dump_interval_seconds() -> int:
    raw = str(os.getenv("DAPPER_PYTEST_FAULTHANDLER_DUMP_SECONDS", "0")).strip()
    try:
        interval = int(raw)
    except ValueError:
        return 0
    return max(interval, 0)


def _shutdown_trace(message: str) -> None:
    if not _shutdown_trace_enabled():
        return
    stamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    print(f"[dapper-pytest-shutdown {stamp}] {message}", file=sys.stderr, flush=True)


def _is_truthy(value: str | None) -> bool:
    return str(value).lower() in ("1", "true", "yes")


def _normalized_timeout(timeout_seconds: float) -> float:
    return max(timeout_seconds, 0.05)


def _is_vscode_test_runner_context() -> bool:
    # VS Code Python test adapter typically injects one or both of these pipe env vars.
    # Prefer these specific signals over broad editor markers like VSCODE_PID.
    return bool(
        os.getenv("TEST_RUN_PIPE")
        or os.getenv("RUN_TEST_IDS_PIPE")
        or os.getenv("PYTEST_TEST_RUN_PIPE")
        or os.getenv("PYTEST_RUN_TEST_IDS_PIPE")
    )


def _resolve_skip_js_tests_in_conftest() -> str:
    explicit_skip = os.getenv("DAPPER_SKIP_JS_TESTS_IN_CONFTEST")
    if explicit_skip is None:
        # Backward compatibility for historical typo.
        explicit_skip = os.getenv("DAPPER_SKIP_JS_TESTS_IN_CONFT")

    if _is_truthy(os.getenv("DAPPER_RUN_JS_TESTS_IN_CONFTEST")):
        return "0"

    if _is_vscode_test_runner_context():
        _shutdown_trace("detected VS Code test runner context; skipping JS tests in conftest")
        return "1"

    return explicit_skip if explicit_skip is not None else "1"


def _maybe_start_faulthandler_dump() -> None:
    interval = _faulthandler_dump_interval_seconds()
    if interval <= 0:
        return

    try:
        faulthandler.enable(file=sys.stderr)
    except Exception as exc:  # pragma: no cover - best-effort diagnostics
        _shutdown_trace(f"faulthandler.enable failed: {exc!s}")
        return

    try:
        faulthandler.dump_traceback_later(interval, repeat=True, file=sys.stderr)
        _shutdown_trace(f"faulthandler.dump_traceback_later started interval={interval}s")
    except Exception as exc:  # pragma: no cover - best-effort diagnostics
        _shutdown_trace(f"faulthandler.dump_traceback_later failed: {exc!s}")


def _format_threads_for_trace() -> str:
    items = [
        f"{thread.name}(ident={thread.ident},daemon={thread.daemon},alive={thread.is_alive()})"
        for thread in threading.enumerate()
    ]
    return ", ".join(items)


@atexit.register
def _shutdown_atexit_trace() -> None:
    _shutdown_trace("atexit reached")
    _shutdown_trace(f"threads at atexit: {_format_threads_for_trace()}")
    try:
        faulthandler.cancel_dump_traceback_later()
    except Exception:
        pass


# Track event loops created via asyncio.new_event_loop so tests can ensure
# they are explicitly closed. This prevents relying on CPython's GC and the
# loop destructor which may run during interpreter shutdown and observe
# partially torn-down objects, leading to UnraisableExceptionWarning.
_created_event_loops: set[asyncio.AbstractEventLoop] = set()
_orig_new_event_loop = asyncio.new_event_loop
_KNOWN_BACKGROUND_THREAD_NAMES = {"SyncConnAdapterLoop", "IPC-Reader"}
_pytest_session_state: dict[str, int] = {"exitstatus": 0}


def _force_thread_shutdown_enabled() -> bool:
    # Enabled by default on Windows in test runs to avoid known
    # post-summary shutdown hangs from leaked background threads.
    default = "1" if sys.platform.startswith("win") else "0"
    return str(os.getenv("DAPPER_FORCE_THREAD_SHUTDOWN", default)).lower() in (
        "1",
        "true",
        "yes",
    )


def _force_process_exit_enabled() -> bool:
    default = (
        "1"
        if sys.platform.startswith("win") and (os.getenv("CI") or _is_vscode_test_runner_context())
        else "0"
    )
    return str(os.getenv("DAPPER_PYTEST_FORCE_OS_EXIT", default)).lower() in (
        "1",
        "true",
        "yes",
    )


def _shutdown_policy() -> tuple[bool, float, float]:
    """Return (force_exit, loop_timeout, cleanup_timeout)."""
    force_exit = _force_process_exit_enabled()
    loop_timeout = 0.2 if (force_exit or _is_vscode_test_runner_context()) else 1.5
    cleanup_timeout = 0.1 if force_exit else 1.5
    return force_exit, loop_timeout, cleanup_timeout


def _loop_teardown_timeout_seconds() -> float:
    return _shutdown_policy()[1]


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
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]
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
    loops = list(_created_event_loops)
    shutdown_timeout = _loop_teardown_timeout_seconds()

    # First, request graceful shutdown so default executor threads get a
    # chance to exit before we close loops.
    for loop in loops:
        _shutdown_loop_best_effort(loop, timeout_seconds=shutdown_timeout)

    # Ask any still-running loops to stop, then allow their threads to observe
    # the stop signal.
    for loop in loops:
        try:
            if not loop.is_closed() and loop.is_running():
                loop.call_soon_threadsafe(loop.stop)
        except Exception:  # noqa: PERF203
            pass

    time.sleep(0.05)

    # Finally close loops that are no longer running.
    for loop in loops:
        try:
            if not loop.is_closed() and not loop.is_running():
                loop.close()
        except Exception:  # noqa: PERF203
            pass

    _created_event_loops.clear()


async def _graceful_loop_shutdown(
    loop: asyncio.AbstractEventLoop, timeout_seconds: float = 1.0
) -> None:
    bounded_timeout = _normalized_timeout(timeout_seconds)
    current = asyncio.current_task(loop=loop)
    pending = [t for t in asyncio.all_tasks(loop) if t is not current and not t.done()]
    for task in pending:
        task.cancel()
    if pending:
        try:
            await asyncio.wait_for(
                asyncio.gather(*pending, return_exceptions=True),
                timeout=bounded_timeout,
            )
        except TimeoutError:
            pass
    try:
        await asyncio.wait_for(loop.shutdown_asyncgens(), timeout=bounded_timeout)
    except TimeoutError:
        pass
    try:
        await asyncio.wait_for(loop.shutdown_default_executor(), timeout=bounded_timeout)
    except TimeoutError:
        pass


def _shutdown_loop_best_effort(
    loop: asyncio.AbstractEventLoop, timeout_seconds: float = 1.0
) -> None:
    if loop.is_closed():
        return

    try:
        if loop.is_running():
            future = asyncio.run_coroutine_threadsafe(
                _graceful_loop_shutdown(loop, timeout_seconds=timeout_seconds),
                loop,
            )
            try:
                future.result(timeout=_normalized_timeout(timeout_seconds) + 0.25)
            except concurrent.futures.TimeoutError:
                future.cancel()
                try:
                    future.result(timeout=0.2)
                except Exception:
                    pass
            except concurrent.futures.CancelledError:
                pass
            return

        loop.run_until_complete(_graceful_loop_shutdown(loop, timeout_seconds=timeout_seconds))
    except Exception:
        pass


def _join_known_background_threads(timeout_seconds: float = 1.0) -> None:
    current = threading.current_thread()
    for thread in list(threading.enumerate()):
        if thread is current:
            continue
        if thread.name not in _KNOWN_BACKGROUND_THREAD_NAMES:
            continue
        if not thread.is_alive():
            continue
        try:
            thread.join(timeout=timeout_seconds)
        except Exception:
            pass


def _force_stop_lingering_threads(timeout_seconds: float = 1.0) -> None:
    if not _force_thread_shutdown_enabled():
        return

    current = threading.current_thread()
    candidates: list[threading.Thread] = []
    for thread in list(threading.enumerate()):
        if thread is current or not thread.is_alive():
            continue
        if thread.name in _KNOWN_BACKGROUND_THREAD_NAMES or thread.name.startswith("asyncio_"):
            candidates.append(thread)

    if not candidates:
        return

    py_async_exc = ctypes.pythonapi.PyThreadState_SetAsyncExc
    py_async_exc.argtypes = [ctypes.c_ulong, ctypes.py_object]
    py_async_exc.restype = ctypes.c_int

    for thread in candidates:
        if thread.ident is None:
            continue
        try:
            result = py_async_exc(ctypes.c_ulong(thread.ident), ctypes.py_object(SystemExit))
            if result > 1:
                py_async_exc(ctypes.c_ulong(thread.ident), None)
                _shutdown_trace(
                    f"forced-stop rollback for thread {thread.name} ident={thread.ident}"
                )
                continue
            _shutdown_trace(
                f"forced-stop signal sent to thread {thread.name} "
                f"ident={thread.ident} result={result}"
            )
        except Exception as exc:  # pragma: no cover - best-effort diagnostics
            _shutdown_trace(f"forced-stop failed for thread {thread.name}: {exc!s}")

    # Give threads a final chance to exit.
    deadline = time.time() + timeout_seconds
    for thread in candidates:
        remaining = max(0.0, deadline - time.time())
        if remaining <= 0:
            break
        try:
            thread.join(timeout=remaining)
        except Exception:
            pass


# On Windows the default event loop policy uses ProactorEventLoop which
# attempts to create a socketpair during new_event_loop(). On some Windows
# environments this can fail with WinError 10055 due to limited socket
# resources. For test runs we prefer the selector policy which avoids the
# fallback socketpair path and is sufficient for unit tests.
if sys.platform.startswith("win"):
    try:
        from asyncio import WindowsSelectorEventLoopPolicy  # type: ignore[attr-defined]

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
        _shutdown_loop_best_effort(loop, timeout_seconds=_loop_teardown_timeout_seconds())
        try:
            loop.close()
        except Exception:
            logger.exception("Failed to close event loop")
        try:
            asyncio.set_event_loop(None)
        except Exception:
            logger.exception("Failed to unset event loop")


@pytest.fixture
def background_event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Provide an event loop running in a dedicated background thread."""
    loop = asyncio.new_event_loop()
    ready = threading.Event()

    def _run() -> None:
        asyncio.set_event_loop(loop)
        ready.set()
        loop.run_forever()

    thread = threading.Thread(target=_run, daemon=True, name="TestBackgroundLoop")
    thread.start()

    if not ready.wait(timeout=1.0):
        try:
            if not loop.is_closed():
                loop.close()
        finally:
            thread.join(timeout=1.0)
        raise RuntimeError("Timed out waiting for background event loop to start")

    try:
        yield loop
    finally:
        _shutdown_loop_best_effort(loop, timeout_seconds=_loop_teardown_timeout_seconds())
        if not loop.is_closed():
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                pass
        thread.join(timeout=_loop_teardown_timeout_seconds())
        if not loop.is_closed() and not loop.is_running():
            loop.close()


def pytest_sessionfinish(session, exitstatus):
    """Invoke extension jest tests at the end of a pytest session.

    If jest tests fail, exit the entire pytest run with the jest exit code so CI signals failure.
    """
    _pytest_session_state["exitstatus"] = int(exitstatus)
    # If pytest already failed, continue and still run JS tests to gather all results.
    # Mark args as used to satisfy linters (plugin requires specific arg names)
    del session, exitstatus
    _shutdown_trace("pytest_sessionfinish entered")
    _maybe_start_faulthandler_dump()
    _shutdown_trace(f"threads at sessionfinish entry: {_format_threads_for_trace()}")
    skip_in_conftest = _resolve_skip_js_tests_in_conftest()

    _shutdown_trace(f"skip_in_conftest={skip_in_conftest!r}")

    if _is_truthy(skip_in_conftest):
        _shutdown_trace("pytest_sessionfinish returning early (JS tests skipped)")
        return
    try:
        _shutdown_trace("calling run_js_tests()")
        run_js_tests()
        _shutdown_trace("run_js_tests() completed")
    except JSTestsFailedError as exc:
        logger.exception("Extension JS tests failed")
        sys.exit(exc.returncode)
    finally:
        _shutdown_trace("pytest_sessionfinish exiting")


def pytest_unconfigure(config):
    _shutdown_trace("pytest_unconfigure entered")
    try:
        plugin_names = sorted(
            {
                str(name)
                for name, plugin in config.pluginmanager.list_name_plugin()
                if plugin is not None
            }
        )
        _shutdown_trace(f"loaded plugins: {plugin_names}")
    except Exception as exc:  # pragma: no cover - best-effort diagnostics
        _shutdown_trace(f"failed to enumerate plugins: {exc!s}")

    # Aggressive final cleanup for leaked background loops/threads that can
    # keep the interpreter alive on Windows during pytest shutdown.
    force_exit, _loop_timeout, cleanup_timeout = _shutdown_policy()
    _close_tracked_event_loops()
    _join_known_background_threads(timeout_seconds=cleanup_timeout)
    _force_stop_lingering_threads(timeout_seconds=cleanup_timeout)

    _shutdown_trace(f"threads at unconfigure: {_format_threads_for_trace()}")

    if force_exit:
        code = int(_pytest_session_state["exitstatus"])
        _shutdown_trace(f"forcing os._exit({code}) due to DAPPER_PYTEST_FORCE_OS_EXIT")
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(code)
