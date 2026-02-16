"""Tests for ThreadTracker."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any
from typing import cast

from dapper.core.debugger_bdb import DebuggerBDB
from dapper.core.thread_tracker import MAX_STACK_DEPTH
from dapper.core.thread_tracker import StackFrame
from dapper.core.thread_tracker import ThreadTracker
from dapper.protocol.structures import StackFrame as StackFrameDict


class TestStackFrame:
    """Tests for StackFrame dataclass."""

    def test_creation(self):
        """Test StackFrame can be created."""
        frame = StackFrame(
            id=1,
            name="test_func",
            line=42,
            column=0,
            source_name="test.py",
            source_path="/path/to/test.py",
        )
        assert frame.id == 1
        assert frame.name == "test_func"
        assert frame.line == 42
        assert frame.column == 0
        assert frame.source_name == "test.py"
        assert frame.source_path == "/path/to/test.py"

    def test_to_dict(self):
        """Test StackFrame.to_dict() returns DAP-style dict."""
        frame = StackFrame(
            id=1,
            name="test_func",
            line=42,
            column=0,
            source_name="test.py",
            source_path="/path/to/test.py",
        )
        d = frame.to_dict()
        assert d == {
            "id": 1,
            "name": "test_func",
            "line": 42,
            "column": 0,
            "source": {
                "name": "test.py",
                "path": "/path/to/test.py",
            },
        }


class TestThreadTrackerInit:
    """Tests for ThreadTracker initialization."""

    def test_default_values(self):
        """Test ThreadTracker initializes with empty collections."""
        tracker = ThreadTracker()
        assert tracker.threads == {}
        assert tracker.stopped_thread_ids == set()
        assert tracker.frames_by_thread == {}
        assert tracker.frame_id_to_frame == {}
        assert tracker.next_frame_id == 1


class TestThreadRegistration:
    """Tests for thread registration."""

    def test_is_thread_registered_false(self):
        """Test is_thread_registered returns False for unregistered thread."""
        tracker = ThreadTracker()
        assert tracker.is_thread_registered(123) is False

    def test_register_thread_with_name(self):
        """Test registering a thread with explicit name."""
        tracker = ThreadTracker()
        name = tracker.register_thread(123, "MyThread")
        assert name == "MyThread"
        assert tracker.threads[123] == "MyThread"
        assert tracker.is_thread_registered(123) is True

    def test_register_thread_without_name(self):
        """Test registering a thread without explicit name uses current thread name."""
        tracker = ThreadTracker()
        current_name = threading.current_thread().name
        name = tracker.register_thread(456)
        assert name == current_name
        assert tracker.threads[456] == current_name

    def test_get_thread_name(self):
        """Test get_thread_name returns correct name."""
        tracker = ThreadTracker()
        tracker.register_thread(123, "Worker")
        assert tracker.get_thread_name(123) == "Worker"

    def test_get_thread_name_unregistered(self):
        """Test get_thread_name returns None for unregistered thread."""
        tracker = ThreadTracker()
        assert tracker.get_thread_name(999) is None


class TestStoppedState:
    """Tests for stopped/running state management."""

    def test_is_stopped_false(self):
        """Test is_stopped returns False for non-stopped thread."""
        tracker = ThreadTracker()
        assert tracker.is_stopped(123) is False

    def test_mark_stopped(self):
        """Test marking a thread as stopped."""
        tracker = ThreadTracker()
        tracker.mark_stopped(123)
        assert tracker.is_stopped(123) is True
        assert 123 in tracker.stopped_thread_ids

    def test_mark_continued_when_stopped(self):
        """Test marking a stopped thread as continued."""
        tracker = ThreadTracker()
        tracker.mark_stopped(123)
        result = tracker.mark_continued(123)
        assert result is True
        assert tracker.is_stopped(123) is False

    def test_mark_continued_when_not_stopped(self):
        """Test marking a non-stopped thread as continued returns False."""
        tracker = ThreadTracker()
        result = tracker.mark_continued(123)
        assert result is False

    def test_has_stopped_threads(self):
        """Test has_stopped_threads."""
        tracker = ThreadTracker()
        assert tracker.has_stopped_threads() is False
        tracker.mark_stopped(123)
        assert tracker.has_stopped_threads() is True

    def test_all_threads_continued(self):
        """Test all_threads_continued."""
        tracker = ThreadTracker()
        assert tracker.all_threads_continued() is True
        tracker.mark_stopped(123)
        assert tracker.all_threads_continued() is False
        tracker.mark_continued(123)
        assert tracker.all_threads_continued() is True


class TestFrameManagement:
    """Tests for frame ID allocation and registration."""

    def test_allocate_frame_id(self):
        """Test frame ID allocation."""
        tracker = ThreadTracker()
        id1 = tracker.allocate_frame_id()
        id2 = tracker.allocate_frame_id()
        id3 = tracker.allocate_frame_id()
        assert id1 == 1
        assert id2 == 2
        assert id3 == 3

    def test_register_and_get_frame(self):
        """Test registering and retrieving a frame."""
        tracker = ThreadTracker()
        mock_frame = object()
        tracker.register_frame(1, mock_frame)
        assert tracker.get_frame(1) is mock_frame

    def test_get_frame_not_found(self):
        """Test get_frame returns None for unknown ID."""
        tracker = ThreadTracker()
        assert tracker.get_frame(999) is None

    def test_store_and_get_stack_frames(self):
        """Test storing and retrieving stack frames for a thread."""
        tracker = ThreadTracker()
        frames = [
            StackFrameDict(id=1, name="foo", line=1, column=0),
            StackFrameDict(id=2, name="bar", line=2, column=0),
        ]
        tracker.store_stack_frames(123, frames)
        assert tracker.get_stack_frames(123) == frames

    def test_get_stack_frames_empty(self):
        """Test get_stack_frames returns empty list for unknown thread."""
        tracker = ThreadTracker()
        assert tracker.get_stack_frames(999) == []


class TestBuildStackFrames:
    """Tests for build_stack_frames method."""

    def _make_mock_frame(self, name="test", filename="test.py", lineno=1, f_back=None):
        """Create a mock frame object."""
        code = SimpleNamespace(co_filename=filename, co_name=name)
        return SimpleNamespace(f_code=code, f_lineno=lineno, f_back=f_back)

    def test_single_frame(self):
        """Test building stack frames from a single frame."""
        tracker = ThreadTracker()
        frame = self._make_mock_frame("my_func", "/path/test.py", 42)
        frames = tracker.build_stack_frames(frame)

        assert len(frames) == 1
        assert frames[0]["name"] == "my_func"
        assert frames[0]["line"] == 42
        source = frames[0].get("source")
        assert source is not None
        assert source.get("path") == "/path/test.py"
        assert frames[0]["id"] == 1

    def test_frame_chain(self):
        """Test building stack frames from a chain of frames."""
        tracker = ThreadTracker()
        frame3 = self._make_mock_frame("outer", "outer.py", 10)
        frame2 = self._make_mock_frame("middle", "middle.py", 20, f_back=frame3)
        frame1 = self._make_mock_frame("inner", "inner.py", 30, f_back=frame2)

        frames = tracker.build_stack_frames(frame1)

        assert len(frames) == 3
        assert frames[0]["name"] == "inner"
        assert frames[1]["name"] == "middle"
        assert frames[2]["name"] == "outer"

    def test_registers_frames(self):
        """Test that build_stack_frames registers frame objects."""
        tracker = ThreadTracker()
        frame = self._make_mock_frame("test", "test.py", 1)
        tracker.build_stack_frames(frame)

        assert tracker.get_frame(1) is frame

    def test_cycle_detection(self):
        """Test that cycles in frame chain are detected."""
        tracker = ThreadTracker()
        # Create a cycle
        frame1 = SimpleNamespace(
            f_code=SimpleNamespace(co_filename="test.py", co_name="func1"),
            f_lineno=1,
        )
        frame2 = SimpleNamespace(
            f_code=SimpleNamespace(co_filename="test.py", co_name="func2"),
            f_lineno=2,
            f_back=frame1,
        )
        # Create cycle
        frame1.f_back = frame2

        frames = tracker.build_stack_frames(frame1)

        # Should stop when cycle is detected (visits each once)
        assert len(frames) == 2

    def test_max_depth(self):
        """Test that max depth limit is respected."""
        tracker = ThreadTracker()

        # Create a very deep chain
        current = None
        for i in range(MAX_STACK_DEPTH + 10):
            current = self._make_mock_frame(f"func_{i}", "test.py", i, f_back=current)

        frames = tracker.build_stack_frames(current)

        assert len(frames) == MAX_STACK_DEPTH

    def test_none_frame(self):
        """Test building from None frame returns empty list."""
        tracker = ThreadTracker()
        frames = tracker.build_stack_frames(None)
        assert frames == []

    def test_frame_with_exception_in_getattr(self):
        """Test handling of frames that raise exceptions on attribute access."""
        tracker = ThreadTracker()

        class BadFrame:
            @property
            def f_code(self):
                raise RuntimeError("Cannot access code")

            @property
            def f_lineno(self):
                return 1

            @property
            def f_back(self):
                return None

        frames = tracker.build_stack_frames(BadFrame())
        assert frames == []


class TestClear:
    """Tests for clear method."""

    def test_clear_resets_all_state(self):
        """Test that clear resets all state to initial values."""
        tracker = ThreadTracker()

        # Populate with data
        tracker.register_thread(123, "Worker")
        tracker.mark_stopped(123)
        tracker.store_stack_frames(
            123,
            [StackFrameDict(id=1, name="frame", line=1, column=0)],
        )
        tracker.register_frame(1, object())
        tracker.allocate_frame_id()

        # Clear
        tracker.clear()

        # Verify reset
        assert tracker.threads == {}
        assert tracker.stopped_thread_ids == set()
        assert tracker.frames_by_thread == {}
        assert tracker.frame_id_to_frame == {}
        assert tracker.next_frame_id == 1


class TestIntegrationWithDebuggerBDB:
    """Integration tests with DebuggerBDB."""

    def test_debugger_uses_thread_tracker(self):
        """Test that DebuggerBDB uses ThreadTracker internally."""
        dbg = DebuggerBDB()
        assert hasattr(dbg, "thread_tracker")
        assert isinstance(dbg.thread_tracker, ThreadTracker)

    def test_compatibility_properties(self):
        """Test that delegate access works."""
        dbg = DebuggerBDB()

        # Test threads
        dbg.thread_tracker.threads[123] = "Test"
        assert dbg.thread_tracker.threads[123] == "Test"

        # Test stopped_thread_ids
        dbg.thread_tracker.stopped_thread_ids.add(456)
        assert 456 in dbg.thread_tracker.stopped_thread_ids

        # Test frames_by_thread
        frames = [StackFrameDict(id=1, name="frame", line=1, column=0)]
        dbg.thread_tracker.frames_by_thread[123] = frames
        assert dbg.thread_tracker.frames_by_thread[123] == frames

        # Test next_frame_id (use delegate directly - proxy was removed)
        dbg.thread_tracker.next_frame_id = 10
        assert dbg.thread_tracker.next_frame_id == 10

        # Test frame_id_to_frame
        mock_frame = object()
        dbg.thread_tracker.frame_id_to_frame[1] = mock_frame
        assert dbg.thread_tracker.frame_id_to_frame[1] is mock_frame

    def test_get_stack_frames_uses_tracker(self):
        """Test that _get_stack_frames uses the thread tracker."""
        dbg = DebuggerBDB()

        # Create a mock frame
        code = SimpleNamespace(co_filename="test.py", co_name="test_func")
        frame = SimpleNamespace(f_code=code, f_lineno=42, f_back=None)

        stack_frames = dbg._get_stack_frames(cast("Any", frame))

        assert len(stack_frames) == 1
        assert stack_frames[0]["name"] == "test_func"
        assert stack_frames[0]["line"] == 42
        # Verify frame was registered
        assert dbg.thread_tracker.frame_id_to_frame[stack_frames[0]["id"]] is frame
