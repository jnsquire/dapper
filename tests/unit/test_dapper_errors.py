"""Tests for the centralized Dapper error handling system."""

import pytest

from dapper.config import DapperConfig
from dapper.errors import BackendError
from dapper.errors import ConfigurationError
from dapper.errors import DapperError
from dapper.errors import DapperTimeoutError
from dapper.errors import DebuggerError
from dapper.errors import ErrorHandler
from dapper.errors import IPCError
from dapper.errors import ProtocolError
from dapper.errors import create_dap_response
from dapper.errors import handle_error


class TestDapperError:
    """Test cases for DapperError base class."""

    def test_basic_error(self) -> None:
        """Test basic error creation and properties."""
        error = DapperError("Test message")
        
        assert error.message == "Test message"
        assert error.error_code == "DapperError"
        assert error.details == {}
        assert error.cause is None
        assert str(error) == "Test message"

    def test_error_with_cause(self) -> None:
        """Test error with a cause."""
        original_error = ValueError("Original error")
        error = DapperError("Wrapped error", cause=original_error)
        
        assert error.cause is original_error
        assert "caused by: Original error" in str(error)

    def test_error_with_details(self) -> None:
        """Test error with additional details."""
        details = {"key": "value", "number": 42}
        error = DapperError("Test message", details=details)
        
        assert error.details == details

    def test_to_dict(self) -> None:
        """Test converting error to dictionary."""
        error = DapperError("Test message", error_code="CustomError", details={"key": "value"})
        
        result = error.to_dict()
        
        expected = {
            "error": "CustomError",
            "message": "Test message",
            "details": {"key": "value"},
        }
        assert result == expected


class TestSpecificErrors:
    """Test cases for specific error types."""

    def test_configuration_error(self) -> None:
        """Test ConfigurationError."""
        error = ConfigurationError("Invalid config", config_key="test_key")
        
        assert error.error_code == "ConfigurationError"
        assert error.config_key == "test_key"
        assert error.details["config_key"] == "test_key"

    def test_ipc_error(self) -> None:
        """Test IPCError."""
        error = IPCError("Connection failed", transport="tcp", endpoint="localhost:4711")
        
        assert error.error_code == "IPCError"
        assert error.transport == "tcp"
        assert error.endpoint == "localhost:4711"
        assert error.details["transport"] == "tcp"
        assert error.details["endpoint"] == "localhost:4711"

    def test_debugger_error(self) -> None:
        """Test DebuggerError."""
        error = DebuggerError("Operation failed", operation="set_breakpoint", thread_id=123)
        
        assert error.error_code == "DebuggerError"
        assert error.operation == "set_breakpoint"
        assert error.thread_id == 123
        assert error.details["operation"] == "set_breakpoint"
        assert error.details["thread_id"] == 123

    def test_protocol_error(self) -> None:
        """Test ProtocolError."""
        error = ProtocolError("Invalid protocol", command="launch", sequence=42)
        
        assert error.error_code == "ProtocolError"
        assert error.command == "launch"
        assert error.sequence == 42
        assert error.details["command"] == "launch"
        assert error.details["sequence"] == 42

    def test_backend_error(self) -> None:
        """Test BackendError."""
        error = BackendError("Backend failure", backend_type="InProcessBackend")
        
        assert error.error_code == "BackendError"
        assert error.backend_type == "InProcessBackend"
        assert error.details["backend_type"] == "InProcessBackend"

    def test_timeout_error(self) -> None:
        """Test DapperTimeoutError."""
        error = DapperTimeoutError("Operation timed out", timeout_seconds=30.0, operation="connect")
        
        assert error.error_code == "TimeoutError"
        assert error.timeout_seconds == 30.0
        assert error.operation == "connect"
        assert error.details["timeout_seconds"] == 30.0
        assert error.details["operation"] == "connect"


class TestErrorHandler:
    """Test cases for ErrorHandler class."""

    def test_handle_dapper_error(self) -> None:
        """Test handling a DapperError."""
        handler = ErrorHandler()
        error = ConfigurationError("Test error", config_key="test")
        
        result = handler.handle_error(error, reraise=False)
        
        assert result["error"] == "ConfigurationError"
        assert result["message"] == "Test error"
        assert result["details"]["config_key"] == "test"
        assert "traceback" in result

    def test_handle_regular_exception(self) -> None:
        """Test handling a regular exception."""
        handler = ErrorHandler()
        error = ValueError("Regular error")
        
        result = handler.handle_error(error, reraise=False)
        
        assert result["error"] == "ValueError"
        assert result["message"] == "Regular error"
        assert result["details"] == {}

    def test_handle_with_context(self) -> None:
        """Test handling error with context."""
        handler = ErrorHandler()
        error = ConfigurationError("Test error")
        context = {"request_id": 123, "user": "test_user"}
        
        result = handler.handle_error(error, context=context, reraise=False)
        
        assert result["context"] == context

    def test_custom_handler(self) -> None:
        """Test custom error handler registration."""
        handler = ErrorHandler()
        
        def custom_handler(error: Exception) -> dict[str, str]:
            return {"custom": "response", "original": str(error)}
        
        handler.register_handler(ConfigurationError, custom_handler)
        
        error = ConfigurationError("Test error")
        result = handler.handle_error(error, reraise=False)
        
        assert result["custom"] == "response"
        assert result["original"] == "Test error"

    def test_reraise(self) -> None:
        """Test reraising errors."""
        handler = ErrorHandler()
        error = ConfigurationError("Test error")
        
        with pytest.raises(ConfigurationError):
            handler.handle_error(error, reraise=True)

    def test_create_dap_response(self) -> None:
        """Test creating DAP error response."""
        handler = ErrorHandler()
        error = ConfigurationError("Test error")
        
        response = handler.create_dap_response(error, request_seq=42, command="launch")
        
        assert response["request_seq"] == 42
        assert response["command"] == "launch"
        assert response["success"] is False
        assert response["message"] == "Test error"
        assert response["body"]["error"] == "ConfigurationError"


class TestGlobalFunctions:
    """Test cases for global convenience functions."""

    def test_handle_error_global(self) -> None:
        """Test global handle_error function."""
        error = ConfigurationError("Test error")
        
        result = handle_error(error, reraise=False)
        
        assert result["error"] == "ConfigurationError"
        assert result["message"] == "Test error"

    def test_create_dap_response_global(self) -> None:
        """Test global create_dap_response function."""
        error = ConfigurationError("Test error")
        
        response = create_dap_response(error, request_seq=42, command="attach")
        
        assert response["request_seq"] == 42
        assert response["command"] == "attach"
        assert response["success"] is False


class TestErrorIntegration:
    """Integration tests for error handling with other components."""

    def test_error_in_config_validation(self) -> None:
        """Test that configuration validation uses proper errors."""
        
        config = DapperConfig(mode="launch")  # No program set
        
        with pytest.raises(ConfigurationError) as exc_info:
            config.validate()
        
        assert "Program path is required" in str(exc_info.value)
        assert exc_info.value.details["mode"] == "launch"

    def test_dap_response_structure(self) -> None:
        """Test DAP error response structure matches expected format."""
        error = IPCError("Connection failed", transport="tcp", endpoint="localhost:4711")
        response = create_dap_response(error, request_seq=123, command="attach")
        
        # Verify DAP response structure
        assert response["type"] == "response"
        assert response["request_seq"] == 123
        assert response["command"] == "attach"
        assert response["success"] is False
        assert "message" in response
        assert "body" in response
        assert response["body"]["error"] == "IPCError"
        assert response["body"]["details"]["transport"] == "tcp"
