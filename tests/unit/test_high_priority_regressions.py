"""Regression tests for the 7 high-priority bug fixes.

Each test class covers one fix from the high-priority section of
doc/improvement-checklist.md.
"""

from __future__ import annotations

import asyncio
import io
import json
from queue import Queue
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# 1. Memory leak in frame_id_to_frame
# ---------------------------------------------------------------------------


class TestThreadTrackerClearFrames:
    """ThreadTracker.clear_frames() evicts stale frame references."""

    def test_clear_frames_empties_frame_map(self):
        from dapper.core.thread_tracker import ThreadTracker

        tracker = ThreadTracker()
        tracker.register_frame(1, object())
        tracker.register_frame(2, object())
        assert len(tracker.frame_id_to_frame) == 2

        tracker.clear_frames()
        assert tracker.frame_id_to_frame == {}

    def test_clear_frames_empties_frames_by_thread(self):
        from dapper.core.thread_tracker import ThreadTracker

        tracker = ThreadTracker()
        tracker.store_stack_frames(1, [{"id": 1, "name": "f"}])
        assert 1 in tracker.frames_by_thread

        tracker.clear_frames()
        assert tracker.frames_by_thread == {}

    def test_clear_frames_preserves_thread_registrations(self):
        from dapper.core.thread_tracker import ThreadTracker

        tracker = ThreadTracker()
        tracker.register_thread(42, "MainThread")
        tracker.register_frame(1, object())

        tracker.clear_frames()
        # Threads should still be registered
        assert tracker.get_thread_name(42) == "MainThread"
        # Frames should be gone
        assert tracker.frame_id_to_frame == {}


# ---------------------------------------------------------------------------
# 2. Data breakpoints: all changes detected, not just the first
# ---------------------------------------------------------------------------


class TestDataBreakpointAllChanges:
    """check_for_changes returns ALL changed variable names."""

    def test_returns_list_not_string(self):
        from dapper.core.data_breakpoint_state import DataBreakpointState

        state = DataBreakpointState()
        state.register_watches(["x"])
        state.update_snapshots(1, {"x": 5})

        result = state.check_for_changes(1, {"x": 10})
        assert isinstance(result, list)

    def test_returns_empty_list_when_no_changes(self):
        from dapper.core.data_breakpoint_state import DataBreakpointState

        state = DataBreakpointState()
        state.register_watches(["x"])
        state.update_snapshots(1, {"x": 5})

        result = state.check_for_changes(1, {"x": 5})
        assert result == []

    def test_detects_multiple_simultaneous_changes(self):
        from dapper.core.data_breakpoint_state import DataBreakpointState

        state = DataBreakpointState()
        state.register_watches(["x", "y", "z"])
        state.update_snapshots(1, {"x": 1, "y": 2, "z": 3})

        # Change x and z but not y
        result = state.check_for_changes(1, {"x": 100, "y": 2, "z": 300})
        assert set(result) == {"x", "z"}

    def test_returns_empty_list_when_no_watches(self):
        from dapper.core.data_breakpoint_state import DataBreakpointState

        state = DataBreakpointState()
        result = state.check_for_changes(1, {"x": 5})
        assert result == []


# ---------------------------------------------------------------------------
# 3. Missing return after exit_func(0) in launcher stream receiver
# ---------------------------------------------------------------------------


class TestStreamReceiverReturnsAfterExit:
    """_recv_binary_from_stream returns after exit_func(0) on EOF."""

    def test_returns_on_empty_header(self):
        from dapper.launcher import debug_launcher
        from dapper.shared.debug_shared import state

        exit_called = []
        original_exit = state.exit_func
        state.exit_func = lambda code: exit_called.append(code)
        state.is_terminated = False

        # Provide an empty stream (header is b"")
        rfile = io.BytesIO(b"")

        try:
            debug_launcher._recv_binary_from_stream(rfile)
        finally:
            state.exit_func = original_exit

        assert exit_called == [0]

    def test_returns_on_empty_payload(self):
        from dapper.ipc.ipc_binary import pack_frame
        from dapper.launcher import debug_launcher
        from dapper.shared.debug_shared import state

        exit_called = []
        original_exit = state.exit_func
        state.exit_func = lambda code: exit_called.append(code)
        state.is_terminated = False

        # Provide a valid header but truncated payload
        header = pack_frame(2, b"test")[:8]  # header only, no payload
        rfile = io.BytesIO(header)

        try:
            debug_launcher._recv_binary_from_stream(rfile)
        finally:
            state.exit_func = original_exit

        assert exit_called == [0]


# ---------------------------------------------------------------------------
# 4. Double-dispatch of IPC commands
# ---------------------------------------------------------------------------


class TestNoDoubleDispatch:
    """receive_debug_commands only queues; process_queued_commands dispatches."""

    def test_receive_only_queues_no_dispatch(self, monkeypatch):
        from dapper.ipc import ipc_receiver

        s = ipc_receiver.state
        s.is_terminated = False
        s.ipc_enabled = True
        s.command_queue = Queue()

        cmd = {"command": "test_cmd", "seq": 1}
        s.ipc_rfile = io.StringIO(json.dumps(cmd) + "\n")

        dispatch_calls = []
        monkeypatch.setattr(s, "dispatch_debug_command", lambda c: dispatch_calls.append(c))

        with pytest.raises(SystemExit):
            ipc_receiver.receive_debug_commands()

        # dispatch_debug_command should NOT have been called directly
        assert dispatch_calls == []
        # But the command should be in the queue
        assert not s.command_queue.empty()
        assert s.command_queue.get_nowait()["command"] == "test_cmd"

    def test_process_queued_dispatches_exactly_once(self, monkeypatch):
        from dapper.ipc import ipc_receiver

        s = ipc_receiver.state
        s.command_queue = Queue()
        s.command_queue.put({"command": "a"})

        dispatch_calls = []
        monkeypatch.setattr(s, "dispatch_debug_command", lambda c: dispatch_calls.append(c))

        ipc_receiver.process_queued_commands()
        assert len(dispatch_calls) == 1
        assert dispatch_calls[0]["command"] == "a"


# ---------------------------------------------------------------------------
# 5. Event emitter continues past listener errors
# ---------------------------------------------------------------------------


class TestEventEmitterContinuesPastErrors:
    """A failing listener does not prevent subsequent listeners from firing."""

    def test_subsequent_listeners_called_after_error(self):
        from dapper.utils.events import EventEmitter

        emitter = EventEmitter()
        calls = []

        def bad():
            raise RuntimeError("boom")

        def good():
            calls.append("ok")

        emitter.add_listener(bad)
        emitter.add_listener(good)
        emitter.emit()

        assert calls == ["ok"]

    def test_multiple_errors_all_logged(self, monkeypatch):
        from dapper.utils.events import EventEmitter

        emitter = EventEmitter()
        log_calls = []
        monkeypatch.setattr(
            "dapper.utils.events.logger.exception",
            lambda *a, **kw: log_calls.append(True),
        )

        def bad1():
            raise ValueError("v")

        def bad2():
            raise TypeError("t")

        def good():
            pass

        emitter.add_listener(bad1)
        emitter.add_listener(good)
        emitter.add_listener(bad2)
        emitter.emit()

        # Both errors should have been logged
        assert len(log_calls) == 2


# ---------------------------------------------------------------------------
# 6. Lifecycle auto-transition from UNINITIALIZED
# ---------------------------------------------------------------------------


class TestLifecycleAutoTransition:
    """operation_context auto-transitions from UNINITIALIZED to READY."""

    def test_operation_context_auto_transitions(self):
        from dapper.adapter.lifecycle import BackendLifecycleState
        from dapper.adapter.lifecycle import LifecycleManager

        async def _run():
            mgr = LifecycleManager("test")
            assert mgr.state == BackendLifecycleState.UNINITIALIZED

            async with mgr.operation_context("test_op"):
                # Should have auto-transitioned to BUSY
                assert mgr.state == BackendLifecycleState.BUSY

            # Should be back to READY after context exit
            assert mgr.state == BackendLifecycleState.READY

        asyncio.run(_run())

    def test_operation_context_still_works_when_ready(self):
        from dapper.adapter.lifecycle import BackendLifecycleState
        from dapper.adapter.lifecycle import LifecycleManager

        async def _run():
            mgr = LifecycleManager("test")
            await mgr.initialize()
            await mgr.mark_ready()
            assert mgr.state == BackendLifecycleState.READY

            async with mgr.operation_context("test_op"):
                assert mgr.state == BackendLifecycleState.BUSY

            assert mgr.state == BackendLifecycleState.READY

        asyncio.run(_run())

    def test_operation_context_fails_from_terminated(self):
        from dapper.adapter.lifecycle import BackendLifecycleState
        from dapper.adapter.lifecycle import LifecycleManager

        async def _run():
            mgr = LifecycleManager("test")
            # Manually go to terminated
            await mgr.transition_to(BackendLifecycleState.TERMINATED)

            with pytest.raises(RuntimeError, match="Backend not ready"):
                async with mgr.operation_context("test_op"):
                    pass

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 7. Leaked resources in transport_factory
# ---------------------------------------------------------------------------


class TestTransportFactoryResourceRetention:
    """Factory methods retain resource references on the returned connection."""

    def test_unix_connection_retains_socket(self, monkeypatch):
        """_create_unix_connection attaches the socket to the connection."""
        from dapper.ipc.transport_factory import TransportConfig
        from dapper.ipc.transport_factory import TransportFactory

        mock_sock = MagicMock()
        mock_sock_class = MagicMock(return_value=mock_sock)
        monkeypatch.setattr("dapper.ipc.transport_factory._socket.socket", mock_sock_class)
        monkeypatch.setattr("dapper.ipc.transport_factory._socket.AF_UNIX", 1, raising=False)

        config = TransportConfig(path="/tmp/test.sock")
        conn = TransportFactory._create_unix_connection(config)

        # The socket should be stored on the connection
        assert conn.socket is mock_sock
        mock_sock.connect.assert_called_once_with("/tmp/test.sock")

    def test_tcp_connection_retains_socket(self, monkeypatch):
        """_create_tcp_connection attaches the socket to the connection."""
        from dapper.ipc.transport_factory import TransportConfig
        from dapper.ipc.transport_factory import TransportFactory

        mock_sock = MagicMock()
        mock_sock_class = MagicMock(return_value=mock_sock)
        monkeypatch.setattr("dapper.ipc.transport_factory._socket.socket", mock_sock_class)

        config = TransportConfig(host="127.0.0.1", port=9999)
        conn = TransportFactory._create_tcp_connection(config)

        # The socket should be stored on the connection
        assert conn.socket is mock_sock
        mock_sock.connect.assert_called_once()
