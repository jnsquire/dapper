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
from dapper.errors.dapper_errors import wrap_errors

__all__ = [
    "BackendError",
    "ConfigurationError",
    "DapperError",
    "DapperTimeoutError",
    "DebuggerError",
    "ErrorHandler",
    "IPCError",
    "ProtocolError",
    "create_dap_response",
    "default_error_handler",
    "handle_error",
    "wrap_errors",
]
