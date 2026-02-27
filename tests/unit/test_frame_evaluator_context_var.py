"""Unit tests for ContextVar-based thread-local storage in the frame evaluator.

These tests validate that ThreadInfo isolation is correct when using
``contextvars.ContextVar`` instead of ``threading.local``.

Key properties checked:
- Same context → same ThreadInfo object (identity preserved across calls)
- Different threads → different ThreadInfo objects
- Different contextvars contexts → different ThreadInfo objects (the new behaviour
  that threading.local could NOT provide for async tasks on the same thread)
- clear_thread_local_info() forces a fresh ThreadInfo on next access
- Mutations in one context do not bleed into a sibling context
"""

from __future__ import annotations

import asyncio
import contextvars
import importlib
import importlib.util
import threading

import pytest

CYTHON_AVAILABLE = importlib.util.find_spec("dapper._frame_eval._frame_evaluator") is not None

pytestmark = pytest.mark.skipif(not CYTHON_AVAILABLE, reason="Cython module not available")


@pytest.fixture
def evaluator():
    m = importlib.import_module("dapper._frame_eval._frame_evaluator")
    required = ("get_thread_info", "clear_thread_local_info")
    for name in required:
        if not hasattr(m, name):
            pytest.skip(f"{name} not exported by compiled Cython module in this build")
    return m


# ---------------------------------------------------------------------------
# Basic identity / initialisation
# ---------------------------------------------------------------------------


def test_get_thread_info_returns_same_object_in_same_context(evaluator):
    """Two calls in the same context must return the exact same ThreadInfo."""
    info1 = evaluator.get_thread_info()
    info2 = evaluator.get_thread_info()
    assert info1 is info2


def test_get_thread_info_initialised_on_first_call(evaluator):
    """ThreadInfo must be marked fully_initialized on first access."""

    # Run in a fresh context so we're guaranteed a new ThreadInfo.
    def _get():
        ctx = contextvars.copy_context()
        return ctx.run(evaluator.get_thread_info)

    info = _get()
    assert info.fully_initialized is True


# ---------------------------------------------------------------------------
# Thread isolation (regression - must still work like threading.local)
# ---------------------------------------------------------------------------


def test_different_threads_get_different_thread_infos(evaluator):
    """Threads must each receive a distinct ThreadInfo instance."""
    results: list = []

    def _worker():
        results.append(evaluator.get_thread_info())

    t1 = threading.Thread(target=_worker)
    t2 = threading.Thread(target=_worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(results) == 2
    assert results[0] is not results[1]


# ---------------------------------------------------------------------------
# Context isolation (the NEW behaviour ContextVar enables over threading.local)
# ---------------------------------------------------------------------------


def test_different_contexts_get_different_thread_infos(evaluator):
    """Two independent contextvars contexts must produce different ThreadInfos.

    With threading.local this test would FAIL because both contexts run on the
    same thread and would share the single per-thread slot.

    Important setup note: copy_context() snapshots the *current* context.  If
    the ContextVar already has a value in the caller's context (because an
    earlier test called get_thread_info()), both copies would inherit the same
    object.  We therefore clear the var first so both sibling contexts start
    from None and each lazily creates its own ThreadInfo.
    """

    def _run_isolated():
        # Clear in this context so copies below start with None.
        evaluator.clear_thread_local_info()
        ctx1 = contextvars.copy_context()
        ctx2 = contextvars.copy_context()
        return ctx1.run(evaluator.get_thread_info), ctx2.run(evaluator.get_thread_info)

    # Run inside a copy so we don't permanently clear the test-runner context.
    info1, info2 = contextvars.copy_context().run(_run_isolated)
    assert info1 is not info2


def test_mutation_in_one_context_does_not_affect_sibling_context(evaluator):
    """Setting is_pydevd_thread in one context must not touch another.

    Two sibling contexts (both copied from a cleared state) lazily create
    independent ThreadInfo objects, so a mutation to one is invisible to the
    other.
    """

    def _run_isolated():
        evaluator.clear_thread_local_info()
        ctx1 = contextvars.copy_context()
        ctx2 = contextvars.copy_context()

        def _set_pydevd():
            evaluator.get_thread_info().is_pydevd_thread = True

        def _get_pydevd():
            return evaluator.get_thread_info().is_pydevd_thread

        ctx1.run(_set_pydevd)
        return ctx2.run(_get_pydevd)

    result = contextvars.copy_context().run(_run_isolated)
    assert result is False, (
        "Mutation in ctx1 leaked into ctx2 - contexts are not properly isolated"
    )


# ---------------------------------------------------------------------------
# Async tasks on the same thread each get their own context
# ---------------------------------------------------------------------------


def test_async_tasks_on_same_thread_get_isolated_thread_infos(evaluator):
    """Each asyncio Task runs in its own copy_context(), so each task must
    receive a distinct ThreadInfo even though they share an OS thread.

    This is the primary advantage over threading.local: async tasks are
    otherwise indistinguishable at the OS level.

    asyncio.create_task() (and gather) snapshot the current context when
    spawning each task.  If the ContextVar is None at that moment, each task
    will lazily initialise its own independent ThreadInfo.
    """

    results = {}

    async def _task(name: str):
        results[name] = evaluator.get_thread_info()

    async def _main():
        # Clear so the tasks we're about to spawn inherit None, not an
        # already-constructed ThreadInfo from an earlier call on this OS thread.
        evaluator.clear_thread_local_info()
        await asyncio.gather(_task("a"), _task("b"))

    asyncio.run(_main())

    assert "a" in results
    assert "b" in results
    assert results["a"] is not results["b"], (
        "Two asyncio tasks on the same thread share a ThreadInfo - "
        "ContextVar isolation is not working"
    )


def test_async_mutation_does_not_bleed_between_tasks(evaluator):
    """Setting skip_all_frames in one task must not affect a sibling task."""

    async def _set_skip():
        evaluator.get_thread_info().skip_all_frames = True
        await asyncio.sleep(0)

    async def _read_skip(results: dict):
        await asyncio.sleep(0)  # Let _set_skip run first.
        results["skip"] = evaluator.get_thread_info().skip_all_frames

    async def _main():
        # Ensure tasks inherit None so each creates its own ThreadInfo.
        evaluator.clear_thread_local_info()
        results: dict = {}
        await asyncio.gather(_set_skip(), _read_skip(results))
        return results

    results = asyncio.run(_main())
    assert results["skip"] is False, (
        "skip_all_frames mutated in one task leaked into a sibling task"
    )


# ---------------------------------------------------------------------------
# clear_thread_local_info
# ---------------------------------------------------------------------------


def test_clear_produces_fresh_thread_info(evaluator):
    """After clearing, get_thread_info must return a new object."""
    ctx = contextvars.copy_context()

    def _run():
        before = evaluator.get_thread_info()
        evaluator.clear_thread_local_info()
        after = evaluator.get_thread_info()
        return before, after

    before, after = ctx.run(_run)
    assert before is not after


def test_clear_does_not_affect_other_context(evaluator):
    """Clearing in one context must not invalidate another context's ThreadInfo."""
    ctx1 = contextvars.copy_context()
    ctx2 = contextvars.copy_context()

    # Establish a ThreadInfo in ctx2.
    info2 = ctx2.run(evaluator.get_thread_info)

    # Clear inside ctx1.
    ctx1.run(evaluator.clear_thread_local_info)

    # ctx2's ThreadInfo must be unchanged.
    info2_after = ctx2.run(evaluator.get_thread_info)
    assert info2 is info2_after
