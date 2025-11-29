"""Centralized error handling for Dapper debug adapter.

This module provides a hierarchy of exceptions for different types of errors
that can occur in the debug adapter, along with utilities for error reporting
and handling.
"""

from __future__ import annotations

import logging
import traceback
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


class DapperError(Exception):
    """Base exception for all Dapper errors.
    
    All Dapper-specific exceptions should inherit from this class to enable
    centralized error handling and reporting.
    """
    
    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code or self.__class__.__name__
        self.details = details or {}
        self.cause = cause
    
    def to_dict(self) -> dict[str, Any]:
        """Convert error to a dictionary for API responses."""
        return {
            "error": self.error_code,
            "message": self.message,
            "details": self.details,
        }
    
    def __str__(self) -> str:
        if self.cause:
            return f"{self.message} (caused by: {self.cause!s})"
        return self.message


class ConfigurationError(DapperError):
    """Raised when there's a configuration problem."""
    
    def __init__(
        self,
        message: str,
        config_key: str | None = None,
        **kwargs: Any,
    ) -> None:
        details = kwargs.pop("details", {})
        if config_key:
            details["config_key"] = config_key
        super().__init__(message, error_code="ConfigurationError", details=details, **kwargs)
        self.config_key = config_key


class IPCError(DapperError):
    """Raised when there's an IPC-related error."""
    
    def __init__(
        self,
        message: str,
        *,
        transport: str | None = None,
        endpoint: str | None = None,
        **kwargs: Any,
    ) -> None:
        details = kwargs.pop("details", {})
        if transport:
            details["transport"] = transport
        if endpoint:
            details["endpoint"] = endpoint
        super().__init__(message, error_code="IPCError", details=details, **kwargs)
        self.transport = transport
        self.endpoint = endpoint


class DebuggerError(DapperError):
    """Raised when there's a debugger operation error."""
    
    def __init__(
        self,
        message: str,
        *,
        operation: str | None = None,
        thread_id: int | None = None,
        **kwargs: Any,
    ) -> None:
        details = kwargs.pop("details", {})
        if operation:
            details["operation"] = operation
        if thread_id is not None:
            details["thread_id"] = thread_id
        super().__init__(message, error_code="DebuggerError", details=details, **kwargs)
        self.operation = operation
        self.thread_id = thread_id


class ProtocolError(DapperError):
    """Raised when there's a DAP protocol error."""
    
    def __init__(
        self,
        message: str,
        *,
        command: str | None = None,
        sequence: int | None = None,
        **kwargs: Any,
    ) -> None:
        details = kwargs.pop("details", {})
        if command:
            details["command"] = command
        if sequence is not None:
            details["sequence"] = sequence
        super().__init__(message, error_code="ProtocolError", details=details, **kwargs)
        self.command = command
        self.sequence = sequence


class BackendError(DapperError):
    """Raised when there's a backend operation error."""
    
    def __init__(
        self,
        message: str,
        *,
        backend_type: str | None = None,
        **kwargs: Any,
    ) -> None:
        details = kwargs.pop("details", {})
        if backend_type:
            details["backend_type"] = backend_type
        super().__init__(message, error_code="BackendError", details=details, **kwargs)
        self.backend_type = backend_type


class DapperTimeoutError(DapperError):
    """Raised when an operation times out."""
    
    def __init__(
        self,
        message: str,
        *,
        timeout_seconds: float | None = None,
        operation: str | None = None,
        **kwargs: Any,
    ) -> None:
        details = kwargs.pop("details", {})
        if timeout_seconds is not None:
            details["timeout_seconds"] = timeout_seconds
        if operation:
            details["operation"] = operation
        super().__init__(message, error_code="TimeoutError", details=details, **kwargs)
        self.timeout_seconds = timeout_seconds
        self.operation = operation


class ErrorHandler:
    """Centralized error handling and reporting."""
    
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self._error_handlers: dict[type[Exception], Callable[[Exception], Any]] = {}
    
    def register_handler(
        self,
        exception_type: type[Exception],
        handler: Callable[[Exception], Any],
    ) -> None:
        """Register a custom error handler for an exception type."""
        self._error_handlers[exception_type] = handler
    
    def handle_error(
        self,
        error: Exception,
        *,
        reraise: bool = False,
        log_level: int = logging.ERROR,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Handle an error and return a standardized error response.
        
        Args:
            error: The exception to handle
            reraise: Whether to re-raise the exception after handling
            log_level: Logging level for the error
            context: Additional context information
            
        Returns:
            Dictionary with error information suitable for API responses
        """
        # Log the error
        error_msg = f"Error: {error!s}"
        if context:
            error_msg += f" (context: {context})"
        
        self.logger.log(log_level, error_msg, exc_info=True)
        
        # Handle custom error handlers
        for exc_type, handler in self._error_handlers.items():
            if isinstance(error, exc_type):
                try:
                    result = handler(error)
                    if isinstance(result, dict):
                        return result
                except Exception as handler_error:
                    self.logger.error(
                        f"Error handler for {exc_type.__name__} failed: {handler_error}"
                    )
        
        # Convert to standard error response
        if isinstance(error, DapperError):
            error_dict = error.to_dict()
        else:
            error_dict = {
                "error": error.__class__.__name__,
                "message": str(error),
                "details": {},
            }
        
        # Add context if provided
        if context:
            error_dict["context"] = context
        
        # Add traceback for debugging
        error_dict["traceback"] = traceback.format_exc()
        
        if reraise:
            raise error
        
        return error_dict
    
    def create_dap_response(
        self,
        error: Exception,
        request_seq: int,
        command: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a DAP error response for the given error.
        
        Args:
            error: The exception that occurred
            request_seq: The sequence number of the request
            command: The command that failed
            context: Additional context information
            
        Returns:
            DAP response dictionary with error information
        """
        error_info = self.handle_error(error, reraise=False, context=context)
        
        return {
            "seq": 0,  # Will be set by protocol handler
            "type": "response",
            "request_seq": request_seq,
            "success": False,
            "command": command,
            "message": error_info.get("message", "Unknown error"),
            "body": {
                "error": error_info.get("error"),
                "details": error_info.get("details", {}),
            },
        }


# Global error handler instance
default_error_handler = ErrorHandler()


def handle_error(
    error: Exception,
    *,
    reraise: bool = False,
    log_level: int = logging.ERROR,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Handle an error using the default error handler."""
    return default_error_handler.handle_error(
        error, reraise=reraise, log_level=log_level, context=context
    )


def create_dap_response(
    error: Exception,
    request_seq: int,
    command: str,
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a DAP error response using the default error handler."""
    return default_error_handler.create_dap_response(
        error, request_seq, command, context=context
    )


def wrap_errors(
    error_type: type[DapperError] = DapperError,
    *,
    reraise: bool = True,
    log_level: int = logging.ERROR,
) -> Callable:
    """Decorator to wrap functions in error handling.
    
    Args:
        error_type: The type of DapperError to create for caught exceptions
        reraise: Whether to re-raise the wrapped exception
        log_level: Logging level for caught exceptions
        
    Returns:
        Decorated function
    """
    def decorator(func: Callable) -> Callable:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if not isinstance(e, DapperError):
                    # Wrap non-Dapper errors
                    wrapped_error = error_type(
                        f"Error in {func.__name__}: {e!s}",
                        cause=e,
                        details={"function": func.__name__, "args": args, "kwargs": kwargs},
                    )
                else:
                    wrapped_error = e
                
                handle_error(wrapped_error, reraise=reraise, log_level=log_level)
                if reraise:
                    raise wrapped_error
                return None
        return wrapper
    return decorator
