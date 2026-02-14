"""Standardized error handling patterns for Dapper debug adapter.

This module provides decorators and utilities for consistent error handling
across the adapter, backend, and protocol layers.
"""

from __future__ import annotations

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

if TYPE_CHECKING:
    from collections.abc import Coroutine

logger = logging.getLogger(__name__)


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
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except ConfigurationError:
                # Already properly typed - just log and re-raise if needed
                if reraise:
                    raise
                logger.exception(f"Configuration error in {operation or func.__name__}")
                return None
            except IPCError:
                # Already properly typed - just log and re-raise if needed
                if reraise:
                    raise
                logger.exception(f"IPC error in {operation or func.__name__}")
                return None
            except ProtocolError:
                # Already properly typed - just log and re-raise if needed
                if reraise:
                    raise
                logger.exception(f"Protocol error in {operation or func.__name__}")
                return None
            except Exception as e:
                # Wrap generic exceptions
                error_msg = f"Error in adapter operation {operation or func.__name__}: {e!s}"

                # Determine appropriate error type based on exception characteristics
                if (
                    "connection" in str(e).lower()
                    or "pipe" in str(e).lower()
                    or "socket" in str(e).lower()
                ):
                    wrapped_error = IPCError(
                        error_msg, cause=e, details={"operation": operation or func.__name__}
                    )
                elif "timeout" in str(e).lower():
                    wrapped_error = DapperTimeoutError(
                        error_msg, operation=operation or func.__name__, cause=e
                    )
                else:
                    wrapped_error = DapperError(
                        error_msg,
                        error_code="AdapterError",
                        cause=e,
                        details={"operation": operation or func.__name__},
                    )

                logger.log(log_level, error_msg, exc_info=True)

                if reraise:
                    raise wrapped_error from e
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
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_msg = f"Error in {backend_type} backend operation {operation or func.__name__}: {e!s}"

                wrapped_error = BackendError(
                    error_msg,
                    backend_type=backend_type,
                    cause=e,
                    details={"operation": operation or func.__name__},
                )

                logger.log(log_level, error_msg, exc_info=True)

                if reraise:
                    raise wrapped_error from e
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
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except ConfigurationError:
                if reraise:
                    raise
                logger.exception(f"Configuration error in {operation or func.__name__}")
                return None
            except IPCError:
                if reraise:
                    raise
                logger.exception(f"IPC error in {operation or func.__name__}")
                return None
            except ProtocolError:
                if reraise:
                    raise
                logger.exception(f"Protocol error in {operation or func.__name__}")
                return None
            except Exception as e:
                error_msg = f"Error in adapter operation {operation or func.__name__}: {e!s}"

                if (
                    "connection" in str(e).lower()
                    or "pipe" in str(e).lower()
                    or "socket" in str(e).lower()
                ):
                    wrapped_error = IPCError(
                        error_msg, cause=e, details={"operation": operation or func.__name__}
                    )
                elif "timeout" in str(e).lower():
                    wrapped_error = DapperTimeoutError(
                        error_msg, operation=operation or func.__name__, cause=e
                    )
                else:
                    wrapped_error = DapperError(
                        error_msg,
                        error_code="AdapterError",
                        cause=e,
                        details={"operation": operation or func.__name__},
                    )

                logger.log(log_level, error_msg, exc_info=True)

                if reraise:
                    raise wrapped_error from e
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
        async def wrapper(*args: Any, **kwargs: Any) -> R:
            try:
                return await func(*args, **kwargs)
            except BackendError:
                if reraise:
                    raise
                logger.exception(f"Backend error in {operation or func.__name__}")
                return cast("R", None)
            except DapperTimeoutError:
                if reraise:
                    raise
                logger.exception(f"Timeout error in {operation or func.__name__}")
                return cast("R", None)
            except Exception as e:
                error_msg = f"Error in backend operation {operation or func.__name__}: {e!s}"

                if "timeout" in str(e).lower():
                    wrapped_error = DapperTimeoutError(
                        error_msg, operation=operation or func.__name__, cause=e
                    )
                else:
                    wrapped_error = BackendError(
                        error_msg, operation=operation or func.__name__, cause=e
                    )

                logger.log(log_level, error_msg, exc_info=True)

                if reraise:
                    raise wrapped_error from e
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
                logger.exception(f"Dapper error in {self.operation}: {exc_val}")
            elif isinstance(exc_val, Exception):
                # Wrap the exception
                wrapped_error = self.error_type(
                    f"Error in {self.operation}: {exc_val!s}",
                    cause=exc_val,
                    details={"operation": self.operation, **self.context},
                )
                logger.exception(f"Wrapped error in {self.operation}: {wrapped_error}")
                raise wrapped_error from exc_val
            else:
                # Non-Exception BaseException, re-raise as-is
                raise exc_val
        return False
