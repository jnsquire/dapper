"""Asyncio task inspection for the DAP threads view.

Exposes live :class:`asyncio.Task` objects as pseudo-threads in the DAP
``threads`` response, and maps each task's coroutine suspension chain to a
list of DAP stack frames so a client can inspect *where* every task is
currently awaiting.

Design notes
------------
* Pseudo-thread IDs start at :data:`TASK_THREAD_ID_BASE` (≈ 251 million) to
  avoid collisions with OS-assigned thread identifiers, which on all common
  platforms are far smaller.
* Frame IDs for task frames start at :data:`TASK_FRAME_ID_BASE` (≈ 2 billion)
  for the same reason.
* The :class:`AsyncioTaskRegistry` rebuilds its snapshot every time
  :meth:`~AsyncioTaskRegistry.snapshot_threads` is called (i.e. on every DAP
  ``threads`` request).  IDs are therefore stable only within a single paused
  snapshot; they should not be persisted across resumes.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from dapper.protocol.structures import StackFrame as StackFrameDict
    from dapper.protocol.structures import Thread

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Base value for pseudo-thread IDs allocated to asyncio tasks.
#: Chosen to be well above typical OS thread IDs (which rarely exceed 2^20).
TASK_THREAD_ID_BASE: int = 0x0F00_0001

#: Base value for frame IDs allocated to coroutine frames.
#: Chosen to be well above typical frame ID counters, which start at 1 and
#: grow incrementally across a debug session.
TASK_FRAME_ID_BASE: int = 0x7FFF_0000

#: Maximum depth when walking a coroutine ``cr_await`` chain.
_MAX_CORO_DEPTH: int = 64


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def get_all_asyncio_tasks() -> frozenset[asyncio.Task[Any]]:
    """Return all live :class:`asyncio.Task` objects across every event loop.

    Prefers the CPython-private ``asyncio.tasks._all_tasks`` :class:`WeakSet`
    which contains tasks from *all* loops.  Falls back to
    :func:`asyncio.all_tasks` (running loop for the current thread only) when
    the private attribute is absent and, finally, returns an empty set if no
    loop is running.
    """
    try:
        # CPython ≥ 3.7 — WeakSet of every Task regardless of which loop owns it.
        raw: Any = asyncio.tasks._all_tasks  # type: ignore[attr-defined]  # noqa: SLF001
        return frozenset(raw)
    except AttributeError:
        pass
    try:
        return frozenset(asyncio.all_tasks())
    except RuntimeError:
        return frozenset()


def task_display_name(task: asyncio.Task[Any]) -> str:
    """Return a human-readable label for *task*.

    Combines the task's own name with the coroutine's qualified name so that
    tasks with CPython-default names (``Task-1``, ``Task-2`` …) still provide
    enough context to identify them.
    """
    name = ""
    try:
        name = task.get_name()
    except Exception:
        pass

    coro_name = ""
    try:
        coro = task.get_coro()
        coro_name = getattr(coro, "__qualname__", "") or getattr(coro, "__name__", "")
    except Exception:
        pass

    if name and coro_name:
        return f"{name} ({coro_name})"
    return name or coro_name or "<asyncio task>"


def build_coroutine_frame_chain(coro: Any) -> list[Any]:
    """Walk a coroutine / awaitable suspension chain and collect live frames.

    Follows ``cr_await`` (coroutine), ``gi_yieldfrom`` (generator), or
    ``ag_await`` (async generator) from *coro* down to the deepest
    suspension point, collecting the frame object at each step.

    The returned list is ordered **innermost first** (deepest suspension at
    index 0, task entry-point at the end) to match the DAP stack-trace
    convention where the most-recent frame is listed first.

    Args:
        coro: A coroutine, generator, or async-generator to inspect.

    Returns:
        List of live frame objects.  May be empty if the coroutine has not
        yet started or has already completed (frame is ``None``).

    """
    outer_to_inner: list[Any] = []
    obj: Any = coro
    seen: set[int] = set()

    for _ in range(_MAX_CORO_DEPTH):
        if obj is None:
            break
        obj_id = id(obj)
        if obj_id in seen:
            break
        seen.add(obj_id)

        frame: Any = None
        next_obj: Any = None

        if hasattr(obj, "cr_frame"):  # coroutine
            frame = obj.cr_frame
            next_obj = getattr(obj, "cr_await", None)
        elif hasattr(obj, "gi_frame"):  # generator
            frame = obj.gi_frame
            next_obj = getattr(obj, "gi_yieldfrom", None)
        elif hasattr(obj, "ag_frame"):  # async generator
            frame = obj.ag_frame
            next_obj = getattr(obj, "ag_await", None)
        else:
            break

        if frame is not None:
            outer_to_inner.append(frame)

        obj = next_obj

    # Reverse so the deepest suspension (innermost frame) is first.
    return list(reversed(outer_to_inner))


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class AsyncioTaskRegistry:
    """Maps live :class:`asyncio.Task` objects to stable pseudo-thread IDs.

    The registry is **rebuilt on every** call to :meth:`snapshot_threads`
    (which should be called once per DAP ``threads`` request).  Between
    snapshot calls, the same pseudo-thread IDs and pre-built frame lists are
    returned unchanged for efficient repeated ``stackTrace`` requests.

    Thread safety
    ~~~~~~~~~~~~~
    Instances are *not* thread-safe.  All calls are expected to come from the
    debugger event-loop thread.
    """

    def __init__(self) -> None:
        self._task_to_pseudo_id: dict[int, int] = {}  # id(task) -> pseudo_id
        self._id_to_task: dict[int, asyncio.Task[Any]] = {}  # pseudo_id -> task
        self._id_to_frames: dict[int, list[StackFrameDict]] = {}  # pseudo_id -> frames
        self._next_thread_id: int = TASK_THREAD_ID_BASE
        self._next_frame_id: int = TASK_FRAME_ID_BASE

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _allocate_frame_id(self) -> int:
        fid = self._next_frame_id
        self._next_frame_id += 1
        return fid

    def _register_task(self, task: asyncio.Task[Any]) -> int:
        key = id(task)
        if key not in self._task_to_pseudo_id:
            pseudo_id = self._next_thread_id
            self._next_thread_id += 1
            self._task_to_pseudo_id[key] = pseudo_id
            self._id_to_task[pseudo_id] = task
        return self._task_to_pseudo_id[key]

    def _build_frames(self, task: asyncio.Task[Any]) -> list[StackFrameDict]:
        try:
            coro = task.get_coro()
        except Exception:
            logger.debug("Could not get coroutine from task", exc_info=True)
            return []

        raw_frames = build_coroutine_frame_chain(coro)
        dap_frames: list[StackFrameDict] = []

        for frame in raw_frames:
            try:
                code = frame.f_code
                filename: str = getattr(code, "co_filename", "<unknown>")
                lineno: int = getattr(frame, "f_lineno", 0)
                name: str = getattr(code, "co_name", "<unknown>") or "<unknown>"
            except Exception:
                continue

            frame_id = self._allocate_frame_id()
            dap_frame: StackFrameDict = {
                "id": frame_id,
                "name": name,
                "line": lineno,
                "column": 0,
                "source": {
                    "name": Path(filename).name if isinstance(filename, str) else str(filename),
                    "path": filename,
                },
            }
            dap_frames.append(dap_frame)

        return dap_frames

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Reset all internal state.

        Call when the debuggee resumes so stale task references don't
        prevent garbage collection.
        """
        self._task_to_pseudo_id.clear()
        self._id_to_task.clear()
        self._id_to_frames.clear()
        self._next_thread_id = TASK_THREAD_ID_BASE
        self._next_frame_id = TASK_FRAME_ID_BASE

    def is_task_thread_id(self, thread_id: int) -> bool:
        """Return ``True`` if *thread_id* was allocated for an asyncio task."""
        return thread_id in self._id_to_task

    def snapshot_threads(self) -> list[Thread]:
        """Enumerate all live asyncio tasks and return them as DAP Thread dicts.

        This method clears any previous snapshot and rebuilds the registry
        from the current set of live tasks.  It also pre-builds the DAP stack
        frames for each task so that subsequent ``stackTrace`` requests are
        cheap.

        Returns:
            List of ``{"id": int, "name": str}`` dicts, one per live task.

        """
        self.clear()
        threads: list[Thread] = []

        for task in get_all_asyncio_tasks():
            try:
                pseudo_id = self._register_task(task)
                name = f"Task: {task_display_name(task)}"
                frames = self._build_frames(task)
                self._id_to_frames[pseudo_id] = frames
                threads.append({"id": pseudo_id, "name": name})
            except Exception:  # noqa: PERF203
                logger.debug("Error inspecting asyncio task", exc_info=True)

        return threads

    def get_task_frames(
        self,
        pseudo_id: int,
        start_frame: int = 0,
        levels: int = 0,
    ) -> list[StackFrameDict]:
        """Return the DAP stack frames for the task with the given *pseudo_id*.

        Args:
            pseudo_id: A pseudo-thread ID previously allocated by this registry.
            start_frame: Index of the first frame to return (0 = innermost).
            levels: Maximum number of frames to return; 0 means all.

        Returns:
            Slice of the pre-built frame list, respecting *start_frame* /
            *levels*.  Returns an empty list if the ID is unknown.

        """
        frames = self._id_to_frames.get(pseudo_id, [])
        total = len(frames)
        end = min(start_frame + levels, total) if levels > 0 else total
        return frames[start_frame:end]

    def get_task_frame_count(self, pseudo_id: int) -> int:
        """Return the total number of frames available for *pseudo_id*."""
        return len(self._id_to_frames.get(pseudo_id, []))


__all__ = [
    "TASK_FRAME_ID_BASE",
    "TASK_THREAD_ID_BASE",
    "AsyncioTaskRegistry",
    "build_coroutine_frame_chain",
    "get_all_asyncio_tasks",
    "task_display_name",
]
