"""In-process backend for PyDebugger.

This module provides the InProcessBackend class that wraps InProcessBridge
with an async interface matching the DebuggerBackend protocol.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

if TYPE_CHECKING:
    from dapper.adapter.inprocess_bridge import InProcessBridge
    from dapper.protocol.debugger_protocol import Variable
    from dapper.protocol.requests import ContinueResponseBody
    from dapper.protocol.requests import EvaluateResponseBody
    from dapper.protocol.requests import ExceptionInfoResponseBody
    from dapper.protocol.requests import FunctionBreakpoint
    from dapper.protocol.requests import SetVariableResponseBody
    from dapper.protocol.requests import StackTraceResponseBody
    from dapper.protocol.structures import Breakpoint
    from dapper.protocol.structures import SourceBreakpoint

logger = logging.getLogger(__name__)


class InProcessBackend:
    """Backend for in-process debugging via InProcessBridge.

    This wraps InProcessBridge with an async interface and error handling
    to match the DebuggerBackend protocol.
    """

    def __init__(self, bridge: InProcessBridge) -> None:
        """Initialize with an InProcessBridge instance."""
        self._bridge = bridge

    @property
    def bridge(self) -> InProcessBridge:
        """Access the underlying bridge."""
        return self._bridge

    def is_available(self) -> bool:
        """Check if the backend is available."""
        return True

    # ------------------------------------------------------------------
    # Breakpoint operations
    # ------------------------------------------------------------------
    async def set_breakpoints(
        self, path: str, breakpoints: list[SourceBreakpoint]
    ) -> list[Breakpoint]:
        """Set line breakpoints for a file."""
        try:
            return self._bridge.set_breakpoints(path, breakpoints)
        except Exception:
            logger.exception("in-process set_breakpoints failed")
            return [{"verified": False} for _ in breakpoints]

    async def set_function_breakpoints(
        self, breakpoints: list[FunctionBreakpoint]
    ) -> list[FunctionBreakpoint]:
        """Set function breakpoints."""
        try:
            return list(self._bridge.set_function_breakpoints(breakpoints))
        except Exception:
            logger.exception("in-process set_function_breakpoints failed")
            return [{"verified": False} for _ in breakpoints]

    async def set_exception_breakpoints(
        self,
        filters: list[str],
        _filter_options: list[dict[str, Any]] | None = None,
        _exception_options: list[dict[str, Any]] | None = None,
    ) -> list[Breakpoint]:
        """Set exception breakpoints.

        Note: filter_options and exception_options are not currently supported
        by the in-process debugger.
        """
        try:
            return list(self._bridge.set_exception_breakpoints(filters))
        except Exception:
            logger.exception("in-process set_exception_breakpoints failed")
            return [{"verified": False} for _ in filters]

    # ------------------------------------------------------------------
    # Execution control
    # ------------------------------------------------------------------
    async def continue_(self, thread_id: int) -> ContinueResponseBody:
        """Continue execution."""
        try:
            return cast("ContinueResponseBody", self._bridge.continue_(thread_id))
        except Exception:
            logger.exception("in-process continue failed")
            return {"allThreadsContinued": False}

    async def next_(self, thread_id: int) -> None:
        """Step over."""
        try:
            self._bridge.next_(thread_id)
        except Exception:
            logger.exception("in-process next failed")

    async def step_in(self, thread_id: int) -> None:
        """Step into."""
        try:
            self._bridge.step_in(thread_id)
        except Exception:
            logger.exception("in-process step_in failed")

    async def step_out(self, thread_id: int) -> None:
        """Step out."""
        try:
            self._bridge.step_out(thread_id)
        except Exception:
            logger.exception("in-process step_out failed")

    async def pause(self, _thread_id: int) -> bool:
        """Pause execution. In-process debugger does not support pause."""
        return False

    # ------------------------------------------------------------------
    # Inspection operations
    # ------------------------------------------------------------------
    async def get_stack_trace(
        self, thread_id: int, start_frame: int = 0, levels: int = 0
    ) -> StackTraceResponseBody:
        """Get stack trace for a thread."""
        try:
            return cast(
                "StackTraceResponseBody",
                self._bridge.stack_trace(thread_id, start_frame, levels),
            )
        except Exception:
            logger.exception("in-process stack_trace failed")
            return {"stackFrames": [], "totalFrames": 0}

    async def get_variables(
        self,
        variables_reference: int,
        filter_type: str = "",
        start: int = 0,
        count: int = 0,
    ) -> list[Variable]:
        """Get variables for the given reference."""
        try:
            result = self._bridge.variables(
                variables_reference,
                filter_type=filter_type or None,
                start=start if start > 0 else None,
                count=count if count > 0 else None,
            )
            if isinstance(result, list):
                return cast("list[Variable]", result)
            return cast("list[Variable]", result.get("variables", []))
        except Exception:
            logger.exception("in-process variables failed")
            return []

    async def set_variable(
        self, var_ref: int, name: str, value: str
    ) -> SetVariableResponseBody:
        """Set a variable value."""
        try:
            return cast(
                "SetVariableResponseBody",
                self._bridge.set_variable(var_ref, name, value),
            )
        except Exception:
            logger.exception("in-process set_variable failed")
            return {"value": value, "type": "string", "variablesReference": 0}

    async def evaluate(
        self, expression: str, frame_id: int | None = None, context: str | None = None
    ) -> EvaluateResponseBody:
        """Evaluate an expression."""
        try:
            return cast(
                "EvaluateResponseBody",
                self._bridge.evaluate(expression, frame_id, context),
            )
        except Exception:
            logger.exception("in-process evaluate failed")
            return {
                "result": f"<evaluation of '{expression}' not available>",
                "type": "string",
                "variablesReference": 0,
            }

    async def exception_info(self, _thread_id: int) -> ExceptionInfoResponseBody:
        """Get exception information for a thread."""
        # In-process debugger doesn't have a dedicated exception_info method
        return {
            "exceptionId": "Unknown",
            "description": "Exception information not available",
            "breakMode": "unhandled",
            "details": {
                "message": "Exception information not available",
                "typeName": "Unknown",
                "fullTypeName": "Unknown",
                "stackTrace": "Exception information not available",
            },
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def configuration_done(self) -> None:
        """Signal that configuration is done. No-op for in-process."""

    async def terminate(self) -> None:
        """Terminate the debuggee. No-op for in-process."""
