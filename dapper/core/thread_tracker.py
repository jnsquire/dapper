"""
ThreadTracker: Centralized management of thread and frame state during debugging.

This module provides a unified API for:
1. Tracking registered threads and their names
2. Managing stopped/running thread state
3. Allocating and tracking frame IDs
4. Storing stack frames per thread
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
import threading
from typing import TYPE_CHECKING
from typing import Any
from typing import Union

if TYPE_CHECKING:
    import types

from dapper.protocol.structures import StackFrame as StackFrameDict

# Runtime type for frame objects
FrameType = Union["types.FrameType", Any]

# Safety limit for stack walking to avoid infinite loops on mocked frames
MAX_STACK_DEPTH = 128


@dataclass
class StackFrame:
    """DAP-style stack frame representation."""

    id: int
    name: str
    line: int
    column: int
    source_name: str
    source_path: str

    def to_dict(self) -> StackFrameDict:
        """Convert to DAP StackFrame dict."""
        return {
            "id": self.id,
            "name": self.name,
            "line": self.line,
            "column": self.column,
            "source": {
                "name": self.source_name,
                "path": self.source_path,
            },
        }


@dataclass
class ThreadTracker:
    """Manages thread registration, stopped state, and frame tracking.

    This class consolidates thread and frame management that was previously
    scattered across multiple attributes in DebuggerBDB:
    - threads: mapping of thread_id -> thread_name
    - stopped_thread_ids: set of currently stopped threads
    - frames_by_thread: mapping of thread_id -> list of stack frames
    - next_frame_id: counter for frame IDs
    - frame_id_to_frame: mapping of frame_id -> actual frame object

    Attributes:
        threads: Mapping of thread ID to thread name.
        stopped_thread_ids: Set of thread IDs that are currently stopped.
        frames_by_thread: Mapping of thread ID to list of stack frame dicts.
        frame_id_to_frame: Mapping of frame ID to actual Python frame object.
        next_frame_id: Next frame ID to allocate.
    """

    threads: dict[int, str] = field(default_factory=dict)
    stopped_thread_ids: set[int] = field(default_factory=set)
    frames_by_thread: dict[int, list[StackFrameDict]] = field(default_factory=dict)
    frame_id_to_frame: dict[int, FrameType] = field(default_factory=dict)
    next_frame_id: int = 1

    def is_thread_registered(self, thread_id: int) -> bool:
        """Check if a thread is registered."""
        return thread_id in self.threads

    def register_thread(self, thread_id: int, name: str | None = None) -> str:
        """Register a thread and return its name.

        If name is not provided, uses the current thread's name.

        Args:
            thread_id: The thread ID to register.
            name: Optional thread name. If None, uses current thread name.

        Returns:
            The thread name.
        """
        if name is None:
            name = threading.current_thread().name
        self.threads[thread_id] = name
        return name

    def get_thread_name(self, thread_id: int) -> str | None:
        """Get the name of a registered thread."""
        return self.threads.get(thread_id)

    def is_stopped(self, thread_id: int) -> bool:
        """Check if a thread is currently stopped."""
        return thread_id in self.stopped_thread_ids

    def mark_stopped(self, thread_id: int) -> None:
        """Mark a thread as stopped."""
        self.stopped_thread_ids.add(thread_id)

    def mark_continued(self, thread_id: int) -> bool:
        """Mark a thread as continued (no longer stopped).

        Returns:
            True if the thread was previously stopped, False otherwise.
        """
        if thread_id in self.stopped_thread_ids:
            self.stopped_thread_ids.discard(thread_id)
            return True
        return False

    def has_stopped_threads(self) -> bool:
        """Check if any threads are currently stopped."""
        return bool(self.stopped_thread_ids)

    def all_threads_continued(self) -> bool:
        """Check if all threads have continued (none stopped)."""
        return not self.stopped_thread_ids

    def allocate_frame_id(self) -> int:
        """Allocate a new frame ID."""
        frame_id = self.next_frame_id
        self.next_frame_id += 1
        return frame_id

    def register_frame(self, frame_id: int, frame: FrameType) -> None:
        """Register a frame object with its ID."""
        self.frame_id_to_frame[frame_id] = frame

    def get_frame(self, frame_id: int) -> FrameType | None:
        """Get a frame object by its ID."""
        return self.frame_id_to_frame.get(frame_id)

    def clear_frames(self) -> None:
        """Evict all frame references to prevent memory leaks.

        Should be called when the debuggee resumes (continue/step/next)
        so that stale frame objects (and their locals/globals) are released.
        """
        self.frame_id_to_frame.clear()
        self.frames_by_thread.clear()

    def store_stack_frames(self, thread_id: int, frames: list[StackFrameDict]) -> None:
        """Store the stack frames for a thread."""
        self.frames_by_thread[thread_id] = frames

    def get_stack_frames(self, thread_id: int) -> list[StackFrameDict]:
        """Get the stack frames for a thread."""
        return self.frames_by_thread.get(thread_id, [])

    def build_stack_frames(
        self,
        frame: types.FrameType | Any | None,
        max_depth: int = MAX_STACK_DEPTH,
    ) -> list[StackFrameDict]:
        """Build a list of DAP stack frame dicts from a Python frame.

        Walks the frame chain, allocating frame IDs and registering each frame.

        Args:
            frame: The starting frame (typically the current frame).
            max_depth: Maximum stack depth to prevent infinite loops.

        Returns:
            List of DAP-style stack frame dicts.
        """
        stack_frames: list[StackFrameDict] = []
        current = frame
        visited: set[int] = set()
        depth = 0

        while current is not None and depth < max_depth:
            # Break if cycle detected
            fid = id(current)
            if fid in visited:
                break
            visited.add(fid)
            depth += 1

            try:
                code = current.f_code
                filename = getattr(code, "co_filename", "<unknown>")
                lineno = getattr(current, "f_lineno", 0)
                name = getattr(code, "co_name", "<unknown>") or "<unknown>"
            except Exception:
                break

            frame_id = self.allocate_frame_id()
            self.register_frame(frame_id, current)

            stack_frame: StackFrameDict = StackFrameDict(
                id=frame_id,
                name=name,
                line=lineno,
                column=0,
                source={
                    "name": Path(filename).name if isinstance(filename, str) else str(filename),
                    "path": filename,
                },
            )
            stack_frames.append(stack_frame)

            # Next frame with defensive getattr
            try:
                current = getattr(current, "f_back", None)
            except Exception:
                break

        return stack_frames

    def clear(self) -> None:
        """Clear all thread and frame state."""
        self.threads.clear()
        self.stopped_thread_ids.clear()
        self.frames_by_thread.clear()
        self.frame_id_to_frame.clear()
        self.next_frame_id = 1


__all__ = ["StackFrame", "ThreadTracker"]
