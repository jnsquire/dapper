"""Tests for SteppingController."""

from __future__ import annotations

from types import SimpleNamespace

from dapper.core.debugger_bdb import DebuggerBDB
from dapper.core.stepping_controller import SteppingController
from dapper.core.stepping_controller import StopReason


class TestStopReason:
    """Tests for StopReason enum."""

    def test_stop_reason_values(self):
        """Test StopReason enum values match DAP strings."""
        assert StopReason.BREAKPOINT.value == "breakpoint"
        assert StopReason.STEP.value == "step"
        assert StopReason.ENTRY.value == "entry"
        assert StopReason.EXCEPTION.value == "exception"
        assert StopReason.PAUSE.value == "pause"
        assert StopReason.DATA_BREAKPOINT.value == "data breakpoint"
        assert StopReason.FUNCTION_BREAKPOINT.value == "function breakpoint"

    def test_stop_reason_is_string(self):
        """Test StopReason values can be used as strings."""
        assert StopReason.BREAKPOINT == "breakpoint"
        assert StopReason.STEP == "step"


class TestSteppingControllerInit:
    """Tests for SteppingController initialization."""

    def test_default_values(self):
        """Test SteppingController initializes with False flags."""
        controller = SteppingController()
        assert controller.stepping is False
        assert controller.stop_on_entry is False
        assert controller.current_frame is None


class TestSteppingState:
    """Tests for stepping state management."""

    def test_is_stepping_false(self):
        """Test is_stepping returns False when not stepping."""
        controller = SteppingController()
        assert controller.is_stepping() is False

    def test_is_stepping_true(self):
        """Test is_stepping returns True when stepping."""
        controller = SteppingController()
        controller.stepping = True
        assert controller.is_stepping() is True

    def test_set_stepping(self):
        """Test set_stepping sets the flag."""
        controller = SteppingController()
        controller.set_stepping(True)
        assert controller.stepping is True
        controller.set_stepping(False)
        assert controller.stepping is False

    def test_set_stepping_default(self):
        """Test set_stepping defaults to True."""
        controller = SteppingController()
        controller.set_stepping()
        assert controller.stepping is True

    def test_request_step(self):
        """Test request_step sets stepping flag."""
        controller = SteppingController()
        controller.request_step()
        assert controller.stepping is True


class TestStopOnEntry:
    """Tests for stop_on_entry state."""

    def test_set_stop_on_entry(self):
        """Test set_stop_on_entry sets the flag."""
        controller = SteppingController()
        controller.set_stop_on_entry(True)
        assert controller.stop_on_entry is True
        controller.set_stop_on_entry(False)
        assert controller.stop_on_entry is False


class TestCurrentFrame:
    """Tests for current_frame management."""

    def test_set_current_frame(self):
        """Test setting current frame."""
        controller = SteppingController()
        frame = SimpleNamespace(f_lineno=10)
        controller.set_current_frame(frame)
        assert controller.current_frame is frame

    def test_current_frame_none(self):
        """Test current frame is None by default."""
        controller = SteppingController()
        assert controller.current_frame is None


class TestGetStopReason:
    """Tests for get_stop_reason method."""

    def test_get_stop_reason_breakpoint(self):
        """Test get_stop_reason returns BREAKPOINT by default."""
        controller = SteppingController()
        assert controller.get_stop_reason() == StopReason.BREAKPOINT

    def test_get_stop_reason_entry(self):
        """Test get_stop_reason returns ENTRY when stop_on_entry is set."""
        controller = SteppingController()
        controller.stop_on_entry = True
        assert controller.get_stop_reason() == StopReason.ENTRY

    def test_get_stop_reason_step(self):
        """Test get_stop_reason returns STEP when stepping is set."""
        controller = SteppingController()
        controller.stepping = True
        assert controller.get_stop_reason() == StopReason.STEP

    def test_get_stop_reason_entry_priority(self):
        """Test stop_on_entry takes priority over stepping."""
        controller = SteppingController()
        controller.stop_on_entry = True
        controller.stepping = True
        assert controller.get_stop_reason() == StopReason.ENTRY

    def test_get_stop_reason_does_not_consume(self):
        """Test get_stop_reason does not consume state."""
        controller = SteppingController()
        controller.stop_on_entry = True
        controller.get_stop_reason()
        assert controller.stop_on_entry is True


class TestConsumeStopState:
    """Tests for consume_stop_state method."""

    def test_consume_breakpoint(self):
        """Test consuming breakpoint state."""
        controller = SteppingController()
        reason = controller.consume_stop_state()
        assert reason == StopReason.BREAKPOINT

    def test_consume_entry(self):
        """Test consuming entry state."""
        controller = SteppingController()
        controller.stop_on_entry = True
        reason = controller.consume_stop_state()
        assert reason == StopReason.ENTRY
        assert controller.stop_on_entry is False

    def test_consume_step(self):
        """Test consuming step state."""
        controller = SteppingController()
        controller.stepping = True
        reason = controller.consume_stop_state()
        assert reason == StopReason.STEP
        assert controller.stepping is False

    def test_consume_entry_priority(self):
        """Test entry is consumed before stepping."""
        controller = SteppingController()
        controller.stop_on_entry = True
        controller.stepping = True
        reason = controller.consume_stop_state()
        assert reason == StopReason.ENTRY
        assert controller.stop_on_entry is False
        # Stepping should still be True (not consumed)
        assert controller.stepping is True


class TestClear:
    """Tests for clear method."""

    def test_clear_resets_all_state(self):
        """Test clear resets all stepping state."""
        controller = SteppingController()
        controller.stepping = True
        controller.stop_on_entry = True
        controller.current_frame = SimpleNamespace()

        controller.clear()

        assert controller.stepping is False
        assert controller.stop_on_entry is False
        assert controller.current_frame is None


class TestIntegrationWithDebuggerBDB:
    """Integration tests with DebuggerBDB."""

    def test_debugger_uses_stepping_controller(self):
        """Test that DebuggerBDB uses SteppingController internally."""
        dbg = DebuggerBDB()
        assert hasattr(dbg, "_stepping_controller")
        assert isinstance(dbg._stepping_controller, SteppingController)

    def test_stepping_compatibility_property(self):
        """Test stepping compatibility property works."""
        dbg = DebuggerBDB()

        dbg.stepping = True
        assert dbg._stepping_controller.stepping is True

        dbg._stepping_controller.stepping = False
        assert dbg.stepping is False

    def test_stop_on_entry_compatibility_property(self):
        """Test stop_on_entry compatibility property works."""
        dbg = DebuggerBDB()

        dbg.stop_on_entry = True
        assert dbg._stepping_controller.stop_on_entry is True

        dbg._stepping_controller.stop_on_entry = False
        assert dbg.stop_on_entry is False

    def test_current_frame_compatibility_property(self):
        """Test current_frame compatibility property works."""
        dbg = DebuggerBDB()

        frame = SimpleNamespace(f_lineno=42)
        dbg.current_frame = frame
        assert dbg._stepping_controller.current_frame is frame

        dbg._stepping_controller.current_frame = None
        assert dbg.current_frame is None

    def test_user_line_uses_controller(self):
        """Test that user_line uses the stepping controller."""
        messages = []

        def capture_message(event, **kwargs):
            messages.append((event, kwargs))

        dbg = DebuggerBDB(send_message=capture_message)
        dbg.stepping = True

        # Create mock frame
        code = SimpleNamespace(co_filename="test.py", co_name="test_func")
        frame = SimpleNamespace(f_code=code, f_lineno=10, f_back=None, f_locals={}, f_globals={})

        dbg.user_line(frame)  # type: ignore[arg-type]

        # Should have sent a stopped event with reason="step"
        stopped_events = [(e, k) for e, k in messages if e == "stopped"]
        assert len(stopped_events) >= 1
        _event, kwargs = stopped_events[-1]
        assert kwargs["reason"] == "step"

        # Stepping should be consumed
        assert dbg.stepping is False

    def test_user_line_entry_reason(self):
        """Test that user_line reports 'entry' reason correctly."""
        messages = []

        def capture_message(event, **kwargs):
            messages.append((event, kwargs))

        dbg = DebuggerBDB(send_message=capture_message)
        dbg.stop_on_entry = True

        # Create mock frame
        code = SimpleNamespace(co_filename="test.py", co_name="test_func")
        frame = SimpleNamespace(f_code=code, f_lineno=10, f_back=None, f_locals={}, f_globals={})

        dbg.user_line(frame)  # type: ignore[arg-type]

        # Should have sent a stopped event with reason="entry"
        stopped_events = [(e, k) for e, k in messages if e == "stopped"]
        assert len(stopped_events) >= 1
        _event, kwargs = stopped_events[-1]
        assert kwargs["reason"] == "entry"

        # stop_on_entry should be consumed
        assert dbg.stop_on_entry is False
