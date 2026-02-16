"""Compatibility exports for adapter server/debugger components.

`PyDebugger` now lives in `dapper.adapter.debugger.py_debugger` and the
protocol server lives in `dapper.adapter.server_core`.
"""

from __future__ import annotations

from dapper.adapter.debugger.py_debugger import PyDebugger
from dapper.adapter.debugger.py_debugger import _acquire_event_loop
from dapper.adapter.request_handlers import RequestHandler
from dapper.adapter.server_core import DebugAdapterServer

__all__ = ["DebugAdapterServer", "PyDebugger", "RequestHandler", "_acquire_event_loop"]
