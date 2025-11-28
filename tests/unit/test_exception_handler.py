"""Tests for ExceptionHandler."""

from __future__ import annotations

import sys
from types import SimpleNamespace

from dapper.core.debugger_bdb import DebuggerBDB
from dapper.core.exception_handler import ExceptionBreakpointConfig
from dapper.core.exception_handler import ExceptionHandler


def _capture_exc_info(exc: BaseException) -> tuple:
    """Helper to capture exc_info for a given exception."""
    try:
        raise exc
    except type(exc):
        return sys.exc_info()


class TestExceptionBreakpointConfig:
    """Tests for ExceptionBreakpointConfig."""

    def test_default_values(self):
        """Test default config has both flags False."""
        config = ExceptionBreakpointConfig()
        assert config.break_on_raised is False
        assert config.break_on_uncaught is False

    def test_is_enabled_when_disabled(self):
        """Test is_enabled returns False when both flags are False."""
        config = ExceptionBreakpointConfig()
        assert config.is_enabled() is False

    def test_is_enabled_with_raised(self):
        """Test is_enabled returns True when break_on_raised is True."""
        config = ExceptionBreakpointConfig(break_on_raised=True)
        assert config.is_enabled() is True

    def test_is_enabled_with_uncaught(self):
        """Test is_enabled returns True when break_on_uncaught is True."""
        config = ExceptionBreakpointConfig(break_on_uncaught=True)
        assert config.is_enabled() is True

    def test_set_from_filters_empty(self):
        """Test set_from_filters with empty list."""
        config = ExceptionBreakpointConfig()
        config.set_from_filters([])
        assert config.break_on_raised is False
        assert config.break_on_uncaught is False

    def test_set_from_filters_raised(self):
        """Test set_from_filters with 'raised'."""
        config = ExceptionBreakpointConfig()
        config.set_from_filters(["raised"])
        assert config.break_on_raised is True
        assert config.break_on_uncaught is False

    def test_set_from_filters_uncaught(self):
        """Test set_from_filters with 'uncaught'."""
        config = ExceptionBreakpointConfig()
        config.set_from_filters(["uncaught"])
        assert config.break_on_raised is False
        assert config.break_on_uncaught is True

    def test_set_from_filters_both(self):
        """Test set_from_filters with both filters."""
        config = ExceptionBreakpointConfig()
        config.set_from_filters(["raised", "uncaught"])
        assert config.break_on_raised is True
        assert config.break_on_uncaught is True


class TestExceptionHandlerInit:
    """Tests for ExceptionHandler initialization."""

    def test_default_values(self):
        """Test ExceptionHandler initializes with default config."""
        handler = ExceptionHandler()
        assert handler.config.break_on_raised is False
        assert handler.config.break_on_uncaught is False
        assert handler.exception_info_by_thread == {}


class TestShouldBreak:
    """Tests for should_break method."""

    def _make_mock_frame(self):
        """Create a mock frame."""
        code = SimpleNamespace(co_filename="test.py", co_name="test_func")
        return SimpleNamespace(f_code=code, f_lineno=10)

    def test_should_break_disabled(self):
        """Test should_break returns False when disabled."""
        handler = ExceptionHandler()
        frame = self._make_mock_frame()
        assert handler.should_break(frame) is False

    def test_should_break_raised_mode(self):
        """Test should_break returns True in raised mode."""
        handler = ExceptionHandler()
        handler.config.break_on_raised = True
        frame = self._make_mock_frame()
        assert handler.should_break(frame) is True

    def test_should_break_uncaught_mode_with_handler(self):
        """Test should_break in uncaught mode when exception is handled."""
        handler = ExceptionHandler()
        handler.config.break_on_uncaught = True

        # Create a frame that appears to handle the exception
        # frame_may_handle_exception returns True for frames with exception handlers
        frame = self._make_mock_frame()
        # By default, frame_may_handle_exception returns None (unknown)
        # which means we treat it as handled and don't break
        result = handler.should_break(frame)
        # None or True from frame_may_handle_exception means handled
        # so we should NOT break
        assert result is False


class TestGetBreakMode:
    """Tests for get_break_mode method."""

    def test_break_mode_raised(self):
        """Test get_break_mode returns 'always' for raised mode."""
        handler = ExceptionHandler()
        handler.config.break_on_raised = True
        assert handler.get_break_mode() == "always"

    def test_break_mode_uncaught(self):
        """Test get_break_mode returns 'unhandled' for uncaught mode."""
        handler = ExceptionHandler()
        handler.config.break_on_uncaught = True
        assert handler.get_break_mode() == "unhandled"

    def test_break_mode_default(self):
        """Test get_break_mode returns 'unhandled' by default."""
        handler = ExceptionHandler()
        assert handler.get_break_mode() == "unhandled"


class TestBuildExceptionInfo:
    """Tests for build_exception_info method."""

    def _make_mock_frame(self, filename="test.py"):
        """Create a mock frame."""
        code = SimpleNamespace(co_filename=filename, co_name="test_func")
        return SimpleNamespace(f_code=code, f_lineno=10)

    def test_build_exception_info(self):
        """Test building exception info."""
        handler = ExceptionHandler()
        handler.config.break_on_raised = True

        exc_info = _capture_exc_info(ValueError("test error"))
        frame = self._make_mock_frame("/path/to/test.py")

        info = handler.build_exception_info(exc_info, frame)

        assert info["exceptionId"] == "ValueError"
        assert info["description"] == "test error"
        assert info["breakMode"] == "always"
        assert info["details"]["message"] == "test error"
        assert info["details"]["typeName"] == "ValueError"
        assert "builtins.ValueError" in info["details"]["fullTypeName"]
        assert info["details"]["source"] == "/path/to/test.py"
        assert isinstance(info["details"]["stackTrace"], list)

    def test_build_exception_info_uncaught_mode(self):
        """Test breakMode is 'unhandled' in uncaught mode."""
        handler = ExceptionHandler()
        handler.config.break_on_uncaught = True

        exc_info = _capture_exc_info(ValueError("test"))
        frame = self._make_mock_frame()

        info = handler.build_exception_info(exc_info, frame)
        assert info["breakMode"] == "unhandled"


class TestGetExceptionText:
    """Tests for get_exception_text method."""

    def test_get_exception_text(self):
        """Test getting exception text."""
        handler = ExceptionHandler()
        exc_info = _capture_exc_info(ValueError("test message"))
        text = handler.get_exception_text(exc_info)
        assert text == "ValueError: test message"

    def test_get_exception_text_no_message(self):
        """Test getting exception text with no message."""
        handler = ExceptionHandler()
        exc_info = _capture_exc_info(ValueError())
        text = handler.get_exception_text(exc_info)
        assert text == "ValueError: "


class TestExceptionInfoStorage:
    """Tests for exception info storage methods."""

    def _make_info(self, exception_id: str = "ValueError") -> dict:
        """Create a mock ExceptionInfo dict."""
        return {
            "exceptionId": exception_id,
            "description": "test",
            "breakMode": "always",
            "details": {
                "message": "test",
                "typeName": exception_id,
                "fullTypeName": f"builtins.{exception_id}",
                "source": "test.py",
                "stackTrace": [],
            },
        }

    def test_store_and_get(self):
        """Test storing and retrieving exception info."""
        handler = ExceptionHandler()
        info = self._make_info()

        handler.store_exception_info(123, info)  # type: ignore[arg-type]
        assert handler.get_exception_info(123) == info

    def test_get_not_found(self):
        """Test get returns None for unknown thread."""
        handler = ExceptionHandler()
        assert handler.get_exception_info(999) is None

    def test_clear_exception_info(self):
        """Test clearing exception info for a thread."""
        handler = ExceptionHandler()
        info = self._make_info()
        handler.store_exception_info(123, info)  # type: ignore[arg-type]

        handler.clear_exception_info(123)
        assert handler.get_exception_info(123) is None

    def test_clear_exception_info_not_found(self):
        """Test clearing non-existent exception info doesn't raise."""
        handler = ExceptionHandler()
        handler.clear_exception_info(999)  # Should not raise

    def test_clear_all(self):
        """Test clearing all exception info."""
        handler = ExceptionHandler()
        handler.store_exception_info(1, self._make_info("Error1"))  # type: ignore[arg-type]
        handler.store_exception_info(2, self._make_info("Error2"))  # type: ignore[arg-type]

        handler.clear_all()

        assert handler.get_exception_info(1) is None
        assert handler.get_exception_info(2) is None


class TestIntegrationWithDebuggerBDB:
    """Integration tests with DebuggerBDB."""

    def test_debugger_uses_exception_handler(self):
        """Test that DebuggerBDB uses ExceptionHandler internally."""
        dbg = DebuggerBDB()
        assert hasattr(dbg, "_exception_handler")
        assert isinstance(dbg._exception_handler, ExceptionHandler)

    def test_compatibility_properties(self):
        """Test that compatibility properties work."""
        dbg = DebuggerBDB()

        # Test exception_breakpoints_raised
        dbg.exception_breakpoints_raised = True
        assert dbg._exception_handler.config.break_on_raised is True

        # Test exception_breakpoints_uncaught
        dbg.exception_breakpoints_uncaught = True
        assert dbg._exception_handler.config.break_on_uncaught is True

        # Test current_exception_info (using type ignore for test dict)
        info = {"exceptionId": "Test"}  # type: ignore[typeddict-item]
        dbg.current_exception_info[123] = info  # type: ignore[assignment]
        assert dbg._exception_handler.exception_info_by_thread[123] == info

    def test_user_exception_uses_handler(self):
        """Test that user_exception uses the exception handler."""
        messages = []

        def capture_message(event, **kwargs):
            messages.append((event, kwargs))

        dbg = DebuggerBDB(send_message=capture_message)
        dbg.exception_breakpoints_raised = True

        # Create mock frame
        code = SimpleNamespace(co_filename="test.py", co_name="test_func")
        frame = SimpleNamespace(f_code=code, f_lineno=10, f_back=None)

        # Create exception info
        exc_info = _capture_exc_info(ValueError("test error"))

        dbg.user_exception(frame, exc_info)  # type: ignore[arg-type]

        # Should have sent a stopped event
        assert len(messages) >= 1
        event, kwargs = messages[-1]
        assert event == "stopped"
        assert kwargs["reason"] == "exception"
        assert "ValueError" in kwargs["text"]
