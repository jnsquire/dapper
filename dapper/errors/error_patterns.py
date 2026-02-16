"""Standardized error handling patterns for Dapper debug adapter.

This module provides decorators and utilities for consistent error handling
across the adapter, backend, and protocol layers.
"""

from __future__ import annotations

from functools import wraps
import logging
from typing import TYPE_CHECKING
from typing import Any
from typing import TypeVar
from typing import cast

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Coroutine
    import types
    from types import CoroutineType

    R = TypeVar("R")
else:
    R = TypeVar("R")

from dapper.errors.dapper_errors import BackendError
from dapper.errors.dapper_errors import ConfigurationError
from dapper.errors.dapper_errors import DapperError
from dapper.errors.dapper_errors import DapperTimeoutError
from dapper.errors.dapper_errors import DebuggerError
from dapper.errors.dapper_errors import IPCError
from dapper.errors.dapper_errors import ProtocolError

logger = logging.getLogger(__name__)

# Exception types that indicate IPC / connectivity problems.
_IPC_ERRORS = (ConnectionError, BrokenPipeError, EOFError)
# TimeoutError covers socket.timeout (alias since Python 3.3).
_TIMEOUT_ERRORS = (TimeoutError,)


def _classify_adapter_error(e: Exception, *, operation: str) -> DapperError:
    """Classify a generic exception into the appropriate ``DapperError`` subtype.

    Uses ``isinstance`` checks against well-known stdlib exception
    hierarchies rather than inspecting the exception message string.
    """
    error_msg = f"Error in adapter operation {operation}: {e!s}"

    if isinstance(e, _IPC_ERRORS):
        return IPCError(error_msg, cause=e, details={"operation": operation})
    if isinstance(e, _TIMEOUT_ERRORS):
        return DapperTimeoutError(error_msg, operation=operation, cause=e)
    return DapperError(
        error_msg,
        error_code="AdapterError",
        cause=e,
        details={"operation": operation},
    )


def _classify_backend_error(e: Exception, *, operation: str) -> BackendError | DapperTimeoutError:
    """Classify a generic exception for backend error decorators."""
    error_msg = f"Error in backend operation {operation}: {e!s}"

    if isinstance(e, _TIMEOUT_ERRORS):
        return DapperTimeoutError(error_msg, operation=operation, cause=e)
    return BackendError(error_msg, operation=operation, cause=e)


def _handle_adapter_exception(
    e: Exception,
    *,
    operation: str,
    reraise: bool,
    log_level: int,
) -> None:
    """Handle adapter exceptions consistently for sync/async decorators."""
    if isinstance(e, ConfigurationError):
        if reraise:
            raise e
        logger.exception("Configuration error in %s", operation)
        return

    if isinstance(e, IPCError):
        if reraise:
            raise e
        logger.exception("IPC error in %s", operation)
        return

    if isinstance(e, ProtocolError):
        if reraise:
            raise e
        logger.exception("Protocol error in %s", operation)
        return

    wrapped_error = _classify_adapter_error(e, operation=operation)
    logger.log(log_level, str(wrapped_error), exc_info=True)

    if reraise:
        raise wrapped_error from e


def _handle_backend_exception(
    e: Exception,
    *,
    operation: str,
    reraise: bool,
    log_level: int,
    backend_type: str | None = None,
) -> None:
    """Handle backend exceptions consistently for sync/async decorators."""
    if isinstance(e, BackendError):
        if reraise:
            raise e
        logger.exception("Backend error in %s", operation)
        return

    if isinstance(e, DapperTimeoutError):
        if reraise:
            raise e
        logger.exception("Timeout error in %s", operation)
        return

    wrapped_error = _classify_backend_error(e, operation=operation)
    if isinstance(wrapped_error, BackendError) and backend_type is not None:
        wrapped_error.backend_type = backend_type
        wrapped_error.details["backend_type"] = backend_type

    logger.log(log_level, str(wrapped_error), exc_info=True)

    if reraise:
        raise wrapped_error from e


def handle_adapter_errors(
    operation: str | None = None,
    *,
    reraise: bool = False,
    log_level: int = logging.ERROR,
) -> Callable:
    """Decorator for adapter-level error handling.

    Wraps exceptions in appropriate DapperError types and provides
    consistent logging and context for adapter operations.

    Args:
        operation: Name of the adapter operation being performed
        reraise: Whether to re-raise the wrapped exception
        log_level: Logging level for caught exceptions

    Returns:
        Decorated function
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                op = operation or func.__name__
                _handle_adapter_exception(
                    e,
                    operation=op,
                    reraise=reraise,
                    log_level=log_level,
                )
                return None

        return wrapper

    return decorator


def handle_backend_errors(
    backend_type: str,
    operation: str | None = None,
    *,
    reraise: bool = False,
    log_level: int = logging.ERROR,
) -> Callable:
    """Decorator for backend-level error handling.

    Wraps exceptions in BackendError with proper backend context.

    Args:
        backend_type: Type of backend (e.g., "inprocess", "ipc", "remote")
        operation: Name of the backend operation being performed
        reraise: Whether to re-raise the wrapped exception
        log_level: Logging level for caught exceptions

    Returns:
        Decorated function
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                _handle_backend_exception(
                    e,
                    operation=operation or func.__name__,
                    reraise=reraise,
                    log_level=log_level,
                    backend_type=backend_type,
                )
                return None

        return wrapper

    return decorator


def handle_debugger_errors(
    operation: str | None = None,
    thread_id: int | None = None,
    *,
    reraise: bool = False,
    log_level: int = logging.ERROR,
) -> Callable:
    """Decorator for debugger operation error handling.

    Wraps exceptions in DebuggerError with proper debugging context.

    Args:
        operation: Name of the debugger operation being performed
        thread_id: Thread ID if applicable to the operation
        reraise: Whether to re-raise the wrapped exception
        log_level: Logging level for caught exceptions

    Returns:
        Decorated function
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_msg = f"Error in debugger operation {operation or func.__name__}: {e!s}"

                wrapped_error = DebuggerError(
                    error_msg, operation=operation or func.__name__, thread_id=thread_id, cause=e
                )

                logger.log(log_level, error_msg, exc_info=True)

                if reraise:
                    raise wrapped_error from e
                return None

        return wrapper

    return decorator


def handle_protocol_errors(
    command: str | None = None,
    sequence: int | None = None,
    *,
    reraise: bool = False,
    log_level: int = logging.ERROR,
) -> Callable:
    """Decorator for protocol-level error handling.

    Wraps exceptions in ProtocolError with proper DAP context.

    Args:
        command: DAP command being processed
        sequence: Sequence number of the request
        reraise: Whether to re-raise the wrapped exception
        log_level: Logging level for caught exceptions

    Returns:
        Decorated function
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_msg = f"Error in protocol command {command or func.__name__}: {e!s}"

                wrapped_error = ProtocolError(
                    error_msg, command=command, sequence=sequence, cause=e
                )

                logger.log(log_level, error_msg, exc_info=True)

                if reraise:
                    raise wrapped_error from e
                return None

        return wrapper

    return decorator


def async_handle_adapter_errors(
    operation: str | None = None,
    *,
    reraise: bool = False,
    log_level: int = logging.ERROR,
) -> Callable:
    """Async version of handle_adapter_errors."""

    def decorator(
        func: Callable[..., Coroutine[Any, Any, Any]],
    ) -> Callable[..., Coroutine[Any, Any, Any]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                op = operation or func.__name__
                _handle_adapter_exception(
                    e,
                    operation=op,
                    reraise=reraise,
                    log_level=log_level,
                )
                return None

        return wrapper

    return decorator


def async_handle_backend_errors(
    operation: str | None = None,
    *,
    reraise: bool = False,
    log_level: int = logging.ERROR,
) -> Callable[
    [Callable[..., CoroutineType[Any, Any, R]]], Callable[..., CoroutineType[Any, Any, R]]
]:
    """Async version of handle_backend_errors."""

    def decorator(
        func: Callable[..., CoroutineType[Any, Any, R]],
    ) -> Callable[..., CoroutineType[Any, Any, R]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> R:
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                op = operation or func.__name__
                _handle_backend_exception(
                    e,
                    operation=op,
                    reraise=reraise,
                    log_level=log_level,
                )
                return cast("R", None)

        return wrapper

    return decorator


def async_handle_debugger_errors(
    operation: str | None = None,
    thread_id: int | None = None,
    *,
    reraise: bool = False,
    log_level: int = logging.ERROR,
) -> Callable:
    """Async version of handle_debugger_errors."""

    def decorator(
        func: Callable[..., Coroutine[Any, Any, Any]],
    ) -> Callable[..., Coroutine[Any, Any, Any]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                error_msg = f"Error in debugger operation {operation or func.__name__}: {e!s}"

                wrapped_error = DebuggerError(
                    error_msg, operation=operation or func.__name__, thread_id=thread_id, cause=e
                )

                logger.log(log_level, error_msg, exc_info=True)

                if reraise:
                    raise wrapped_error from e
                return None

        return wrapper

    return decorator


# Context manager for error handling
class ErrorContext:
    """Context manager for standardized error handling with context."""

    def __init__(
        self,
        operation: str,
        error_type: type[DapperError] = DapperError,
        **context_kwargs: Any,
    ):
        self.operation = operation
        self.error_type = error_type
        self.context = context_kwargs

    def __enter__(self) -> None:
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> bool:
        if exc_val is not None:
            if isinstance(exc_val, DapperError):
                # Already a Dapper error - just log it
                logger.exception("Dapper error in %s: %s", self.operation, exc_val)
            elif isinstance(exc_val, Exception):
                # Wrap the exception
                wrapped_error = self.error_type(
                    f"Error in {self.operation}: {exc_val!s}",
                    cause=exc_val,
                    details={"operation": self.operation, **self.context},
                )
                logger.exception("Wrapped error in %s: %s", self.operation, wrapped_error)
                raise wrapped_error from exc_val
            else:
                # Non-Exception BaseException, re-raise as-is
                raise exc_val
        return False
