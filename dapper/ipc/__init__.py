"""IPC module for Dapper debug adapter.

This module provides inter-process communication functionality with
a clean, maintainable architecture using the factory pattern.
"""

from dapper.ipc.ipc_manager import IPCManager
from dapper.ipc.transport_factory import TransportConfig
from dapper.ipc.transport_factory import TransportFactory

__all__ = [
    "IPCManager",
    "TransportConfig",
    "TransportFactory",
]
