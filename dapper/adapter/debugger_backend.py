"""Debugger backend protocol for unified in-process and external process debugging.

This module defines the DebuggerBackend Protocol that abstracts the differences
between in-process debugging (via InProcessBridge) and external process debugging
(via subprocess + IPC).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import Protocol
from typing import runtime_checkable

if TYPE_CHECKING:
    from dapper.config import DapperConfig
    from dapper.protocol.debugger_protocol import Variable
    from dapper.protocol.requests import ContinueResponseBody
    from dapper.protocol.requests import EvaluateResponseBody
    from dapper.protocol.requests import ExceptionInfoResponseBody
    from dapper.protocol.requests import FunctionBreakpoint
    from dapper.protocol.requests import SetVariableResponseBody
    from dapper.protocol.requests import StackTraceResponseBody
    from dapper.protocol.structures import Breakpoint
    from dapper.protocol.structures import SourceBreakpoint


@runtime_checkable
class DebuggerBackend(Protocol):
    """Protocol defining the interface for debugger backends.

    Both in-process and external process debugging implement this interface,
    allowing PyDebugger to use a single code path for all operations.
    """

    # ------------------------------------------------------------------
    # Lifecycle operations
    # ------------------------------------------------------------------
    async def launch(self, config: DapperConfig) -> None:
        """Launch a new debuggee process using configuration."""
        ...

    async def attach(self, config: DapperConfig) -> None:
        """Attach to an existing debuggee using configuration."""
        ...

    # ------------------------------------------------------------------
    # Breakpoint operations
    # ------------------------------------------------------------------
    async def set_breakpoints(
        self, path: str, breakpoints: list[SourceBreakpoint]
    ) -> list[Breakpoint]:
        """Set line breakpoints for a file."""
        ...

    async def set_function_breakpoints(
        self, breakpoints: list[FunctionBreakpoint]
    ) -> list[FunctionBreakpoint]:
        """Set function breakpoints."""
        ...

    async def set_exception_breakpoints(
        self, filters: list[str],
        filter_options: list[dict[str, Any]] | None = None,
        exception_options: list[dict[str, Any]] | None = None,
    ) -> list[Breakpoint]:
        """Set exception breakpoints."""
        ...

    # ------------------------------------------------------------------
    # Execution control
    # ------------------------------------------------------------------
    async def continue_(self, thread_id: int) -> ContinueResponseBody:
        """Continue execution."""
        ...

    async def next_(self, thread_id: int) -> None:
        """Step over."""
        ...

    async def step_in(self, thread_id: int) -> None:
        """Step into."""
        ...

    async def step_out(self, thread_id: int) -> None:
        """Step out."""
        ...

    async def pause(self, thread_id: int) -> bool:
        """Pause execution. Returns True if pause was sent."""
        ...

    # ------------------------------------------------------------------
    # Inspection operations
    # ------------------------------------------------------------------
    async def get_stack_trace(
        self, thread_id: int, start_frame: int = 0, levels: int = 0
    ) -> StackTraceResponseBody:
        """Get stack trace for a thread."""
        ...

    async def get_variables(
        self,
        variables_reference: int,
        filter_type: str = "",
        start: int = 0,
        count: int = 0,
    ) -> list[Variable]:
        """Get variables for the given reference."""
        ...

    async def set_variable(
        self, var_ref: int, name: str, value: str
    ) -> SetVariableResponseBody:
        """Set a variable value."""
        ...

    async def evaluate(
        self, expression: str, frame_id: int | None = None, context: str | None = None
    ) -> EvaluateResponseBody:
        """Evaluate an expression."""
        ...

    async def exception_info(self, thread_id: int) -> ExceptionInfoResponseBody:
        """Get exception information for a thread."""
        ...

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def configuration_done(self) -> None:
        """Signal that configuration is done."""
        ...

    async def terminate(self) -> None:
        """Terminate the debuggee."""
        ...

    def is_available(self) -> bool:
        """Check if the backend is available and ready."""
        ...
