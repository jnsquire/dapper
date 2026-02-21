"""Unit tests for dapper.core.asyncio_task_inspector."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from dapper.adapter.server import PyDebugger
from dapper.core.asyncio_task_inspector import TASK_FRAME_ID_BASE
from dapper.core.asyncio_task_inspector import TASK_THREAD_ID_BASE
from dapper.core.asyncio_task_inspector import AsyncioTaskRegistry
from dapper.core.asyncio_task_inspector import build_coroutine_frame_chain
from dapper.core.asyncio_task_inspector import get_all_asyncio_tasks
from dapper.core.asyncio_task_inspector import task_display_name

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_frame(filename: str = "app.py", lineno: int = 10, co_name: str = "my_func") -> Any:
    """Build a minimal mock frame object."""
    code = MagicMock()
    code.co_filename = filename
    code.co_name = co_name
    frame = MagicMock()
    frame.f_code = code
    frame.f_lineno = lineno
    return frame


async def _simple_coro() -> None:
    await asyncio.sleep(100)


async def _nested_outer() -> None:
    await _nested_inner()


async def _nested_inner() -> None:
    await asyncio.sleep(100)


# ---------------------------------------------------------------------------
# get_all_asyncio_tasks
# ---------------------------------------------------------------------------


class TestGetAllAsyncioTasks:
    """Tests for get_all_asyncio_tasks()."""

    def test_returns_frozenset(self) -> None:
        result = get_all_asyncio_tasks()
        assert isinstance(result, frozenset)

    def test_contains_running_tasks(self) -> None:
        loop = asyncio.new_event_loop()
        try:

            async def _run():
                t = loop.create_task(_simple_coro())
                try:
                    await asyncio.sleep(0)  # let _simple_coro start
                    tasks = get_all_asyncio_tasks()
                    assert t in tasks
                finally:
                    t.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await t

            loop.run_until_complete(_run())
        finally:
            loop.close()


# ---------------------------------------------------------------------------
# task_display_name
# ---------------------------------------------------------------------------


class TestTaskDisplayName:
    def test_named_task_with_coro(self) -> None:
        loop = asyncio.new_event_loop()
        try:

            async def _run():
                t = loop.create_task(_simple_coro(), name="my-task")
                try:
                    await asyncio.sleep(0)
                    name = task_display_name(t)
                    assert "my-task" in name
                    assert "_simple_coro" in name
                finally:
                    t.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await t

            loop.run_until_complete(_run())
        finally:
            loop.close()

    def test_default_task_name_still_shows_coro(self) -> None:
        loop = asyncio.new_event_loop()
        try:

            async def _run():
                t = loop.create_task(_simple_coro())
                try:
                    await asyncio.sleep(0)
                    name = task_display_name(t)
                    # Even with the default CPython name, coro name is visible
                    assert "_simple_coro" in name
                finally:
                    t.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await t

            loop.run_until_complete(_run())
        finally:
            loop.close()


# ---------------------------------------------------------------------------
# build_coroutine_frame_chain
# ---------------------------------------------------------------------------


class TestBuildCoroutineFrameChain:
    """Tests for build_coroutine_frame_chain()."""

    def test_empty_for_none(self) -> None:
        assert build_coroutine_frame_chain(None) == []

    def test_empty_for_unknown_object(self) -> None:
        assert build_coroutine_frame_chain(object()) == []

    def test_single_coro_with_frame(self) -> None:
        loop = asyncio.new_event_loop()
        try:

            async def _run():
                t = loop.create_task(_simple_coro())
                try:
                    await asyncio.sleep(0)  # let _simple_coro suspend at sleep
                    coro = t.get_coro()
                    frames = build_coroutine_frame_chain(coro)
                    # At least the _simple_coro frame should be present
                    assert len(frames) >= 1
                    # Innermost frame first: asyncio.sleep is deepest
                    # The outermost actual user frame is _simple_coro
                    names = [f.f_code.co_name for f in frames]
                    assert "_simple_coro" in names
                finally:
                    t.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await t

            loop.run_until_complete(_run())
        finally:
            loop.close()

    def test_nested_coros_inner_frame_is_first(self) -> None:
        loop = asyncio.new_event_loop()
        try:

            async def _run():
                t = loop.create_task(_nested_outer())
                try:
                    await asyncio.sleep(0)
                    coro = t.get_coro()
                    frames = build_coroutine_frame_chain(coro)
                    names = [f.f_code.co_name for f in frames]
                    # _nested_inner is the deepest suspension → must appear before _nested_outer
                    assert "_nested_inner" in names
                    assert "_nested_outer" in names
                    assert names.index("_nested_inner") < names.index("_nested_outer")
                finally:
                    t.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await t

            loop.run_until_complete(_run())
        finally:
            loop.close()

    def test_cycle_guard(self) -> None:
        """A self-referential mock should not loop forever."""
        coro = MagicMock()
        coro.cr_frame = _make_frame()
        coro.cr_await = coro  # cycle
        frames = build_coroutine_frame_chain(coro)
        # Should return exactly one frame without hanging
        assert len(frames) == 1


# ---------------------------------------------------------------------------
# AsyncioTaskRegistry
# ---------------------------------------------------------------------------


class TestAsyncioTaskRegistry:
    """Tests for AsyncioTaskRegistry."""

    def test_initial_state(self) -> None:
        reg = AsyncioTaskRegistry()
        assert not reg.is_task_thread_id(1)
        assert not reg.is_task_thread_id(TASK_THREAD_ID_BASE)

    def test_snapshot_threads_returns_list(self) -> None:
        """snapshot_threads with no running tasks returns an empty list."""
        # Between tests, there are typically no asyncio tasks running.
        reg = AsyncioTaskRegistry()
        threads = reg.snapshot_threads()
        assert isinstance(threads, list)

    def test_snapshot_threads_includes_live_tasks(self) -> None:
        loop = asyncio.new_event_loop()
        try:

            async def _run():
                t = loop.create_task(_simple_coro(), name="inspector-test")
                try:
                    await asyncio.sleep(0)
                    reg = AsyncioTaskRegistry()
                    threads = reg.snapshot_threads()
                    ids = [th["id"] for th in threads]
                    names = [th["name"] for th in threads]
                    assert any(th >= TASK_THREAD_ID_BASE for th in ids)
                    assert any("inspector-test" in n for n in names)
                finally:
                    t.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await t

            loop.run_until_complete(_run())
        finally:
            loop.close()

    def test_is_task_thread_id_after_snapshot(self) -> None:
        loop = asyncio.new_event_loop()
        try:

            async def _run():
                t = loop.create_task(_simple_coro())
                try:
                    await asyncio.sleep(0)
                    reg = AsyncioTaskRegistry()
                    threads = reg.snapshot_threads()
                    pseudo_ids = [th["id"] for th in threads]
                    assert all(reg.is_task_thread_id(pid) for pid in pseudo_ids)
                finally:
                    t.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await t

            loop.run_until_complete(_run())
        finally:
            loop.close()

    def test_is_task_thread_id_false_for_real_thread_id(self) -> None:
        reg = AsyncioTaskRegistry()
        reg.snapshot_threads()
        assert not reg.is_task_thread_id(1)
        assert not reg.is_task_thread_id(0)

    def test_get_task_frames_unknown_id(self) -> None:
        reg = AsyncioTaskRegistry()
        assert reg.get_task_frames(TASK_THREAD_ID_BASE) == []

    def test_get_task_frame_count_unknown_id(self) -> None:
        reg = AsyncioTaskRegistry()
        assert reg.get_task_frame_count(TASK_THREAD_ID_BASE) == 0

    def test_get_task_frames_for_real_task(self) -> None:
        loop = asyncio.new_event_loop()
        try:

            async def _run():
                t = loop.create_task(_simple_coro())
                try:
                    await asyncio.sleep(0)
                    reg = AsyncioTaskRegistry()
                    threads = reg.snapshot_threads()
                    for thread in threads:
                        frames = reg.get_task_frames(thread["id"])
                        # Should be a list (possibly empty for non-started)
                        assert isinstance(frames, list)
                        if frames:
                            frame = frames[0]
                            assert "id" in frame
                            assert "name" in frame
                            assert "line" in frame
                            assert "source" in frame
                            assert frame["id"] >= TASK_FRAME_ID_BASE
                finally:
                    t.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await t

            loop.run_until_complete(_run())
        finally:
            loop.close()

    def test_get_task_frames_slicing(self) -> None:
        loop = asyncio.new_event_loop()
        try:

            async def _run():
                t = loop.create_task(_nested_outer())
                try:
                    await asyncio.sleep(0)
                    reg = AsyncioTaskRegistry()
                    threads = reg.snapshot_threads()
                    pseudo_id = threads[0]["id"] if threads else None
                    if pseudo_id is None:
                        return
                    total = reg.get_task_frame_count(pseudo_id)
                    if total < 2:
                        return
                    # start_frame=1 should skip the innermost frame
                    sliced = reg.get_task_frames(pseudo_id, start_frame=1)
                    all_frames = reg.get_task_frames(pseudo_id)
                    assert sliced == all_frames[1:]
                    # levels=1 should return only one frame
                    one = reg.get_task_frames(pseudo_id, levels=1)
                    assert len(one) == 1
                finally:
                    t.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await t

            loop.run_until_complete(_run())
        finally:
            loop.close()

    def test_clear_resets_registry(self) -> None:
        loop = asyncio.new_event_loop()
        try:

            async def _run():
                t = loop.create_task(_simple_coro())
                try:
                    await asyncio.sleep(0)
                    reg = AsyncioTaskRegistry()
                    threads = reg.snapshot_threads()
                    assert threads  # at least one task
                    pseudo_id = threads[0]["id"]
                    assert reg.is_task_thread_id(pseudo_id)
                    reg.clear()
                    assert not reg.is_task_thread_id(pseudo_id)
                    assert reg.get_task_frames(pseudo_id) == []
                finally:
                    t.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await t

            loop.run_until_complete(_run())
        finally:
            loop.close()

    def test_snapshot_clears_previous_mapping(self) -> None:
        """Calling snapshot_threads twice should reset IDs from the first call."""
        reg = AsyncioTaskRegistry()
        reg.snapshot_threads()
        reg.snapshot_threads()  # second call should clear the first mapping
        # Counter resets to base after each clear
        assert reg._next_thread_id >= TASK_THREAD_ID_BASE


# ---------------------------------------------------------------------------
# Integration: PyDebugger.get_threads includes task pseudo-threads
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetThreadsIntegration:
    """Integration tests for asyncio task pseudo-threads via PyDebugger."""

    def setup_method(self) -> None:
        self.mock_server = MagicMock()

        class _CompletedAwaitable:
            def __await__(self):
                async def _c():
                    return None

                return _c().__await__()

        self.mock_server.send_event = MagicMock(return_value=_CompletedAwaitable())

    async def _make_debugger(self) -> PyDebugger:
        """Create a PyDebugger bound to the currently-running (pytest-asyncio) loop."""
        return PyDebugger(self.mock_server, asyncio.get_running_loop())

    async def test_get_threads_includes_live_tasks(self) -> None:
        debugger = await self._make_debugger()
        t = asyncio.create_task(_simple_coro(), name="test-task-for-threads")
        try:
            await asyncio.sleep(0)
            threads = await debugger.get_threads()
            names = [th["name"] for th in threads]
            ids = [th["id"] for th in threads]
            assert any("test-task-for-threads" in n for n in names)
            assert any(tid >= TASK_THREAD_ID_BASE for tid in ids)
        finally:
            t.cancel()
            with pytest.raises(asyncio.CancelledError):
                await t
            await debugger.shutdown()

    async def test_get_stack_trace_for_task_pseudo_thread(self) -> None:
        debugger = await self._make_debugger()
        t = asyncio.create_task(_nested_outer(), name="test-task-for-stack")
        try:
            await asyncio.sleep(0)
            threads = await debugger.get_threads()
            task_threads = [th for th in threads if th["id"] >= TASK_THREAD_ID_BASE]
            assert task_threads, "Expected at least one task pseudo-thread"
            pseudo_id = task_threads[0]["id"]
            result = await debugger.get_stack_trace(pseudo_id)
            assert "stackFrames" in result
            assert "totalFrames" in result
            frames = result["stackFrames"]
            assert isinstance(frames, list)
            if frames:
                assert all("id" in f and "name" in f and "source" in f for f in frames)
        finally:
            t.cancel()
            with pytest.raises(asyncio.CancelledError):
                await t
            await debugger.shutdown()

    async def test_get_stack_trace_unknown_pseudo_id_returns_empty(self) -> None:
        debugger = await self._make_debugger()
        t = asyncio.create_task(_simple_coro())
        try:
            await asyncio.sleep(0)
            _ = await debugger.get_threads()  # populate registry
            # Use an ID that's in task range but not allocated
            bad_id = TASK_THREAD_ID_BASE + 99999
            result = await debugger.get_stack_trace(bad_id)
            # Should return empty gracefully (falls through to backend/cache path)
            assert isinstance(result.get("stackFrames", []), list)
        finally:
            t.cancel()
            with pytest.raises(asyncio.CancelledError):
                await t
            await debugger.shutdown()
