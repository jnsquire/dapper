"""Error handling for Dapper debug adapter."""

from dapper.errors.dapper_errors import BackendError
from dapper.errors.dapper_errors import ConfigurationError
from dapper.errors.dapper_errors import DapperError
from dapper.errors.dapper_errors import DapperTimeoutError
from dapper.errors.dapper_errors import DebuggerError
from dapper.errors.dapper_errors import ErrorHandler
from dapper.errors.dapper_errors import IPCError
from dapper.errors.dapper_errors import ProtocolError
from dapper.errors.dapper_errors import create_dap_response
from dapper.errors.dapper_errors import default_error_handler
from dapper.errors.dapper_errors import handle_error
from dapper.errors.error_patterns import ErrorContext
from dapper.errors.error_patterns import async_handle_adapter_errors
from dapper.errors.error_patterns import async_handle_backend_errors
from dapper.errors.error_patterns import async_handle_debugger_errors
from dapper.errors.error_patterns import handle_adapter_errors
from dapper.errors.error_patterns import handle_backend_errors
from dapper.errors.error_patterns import handle_debugger_errors
from dapper.errors.error_patterns import handle_protocol_errors

__all__ = [
    "BackendError",
    "ConfigurationError",
    "DapperError",
    "DapperTimeoutError",
    "DebuggerError",
    "ErrorContext",
    "ErrorHandler",
    "IPCError",
    "ProtocolError",
    "async_handle_adapter_errors",
    "async_handle_backend_errors",
    "async_handle_debugger_errors",
    "create_dap_response",
    "default_error_handler",
    "handle_adapter_errors",
    "handle_backend_errors",
    "handle_debugger_errors",
    "handle_error",
    "handle_protocol_errors",
]
