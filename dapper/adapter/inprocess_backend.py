"""In-process backend for PyDebugger.

This module provides the InProcessBackend class that wraps InProcessBridge
with an async interface matching the DebuggerBackend protocol.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from dapper.adapter.base_backend import BaseBackend

if TYPE_CHECKING:
    from dapper.adapter.inprocess_bridge import InProcessBridge
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

logger = logging.getLogger(__name__)


class InProcessBackend(BaseBackend):
    """Backend for in-process debugging via InProcessBridge.

    This wraps InProcessBridge with an async interface and error handling
    to match the DebuggerBackend protocol.
    """

    def __init__(self, bridge: InProcessBridge) -> None:
        """Initialize with an InProcessBridge instance."""
        super().__init__()
        self._bridge = bridge
        
        # Register cleanup callback
        self._lifecycle.add_cleanup_callback(self._cleanup_bridge)
    
    def _cleanup_bridge(self) -> None:
        """Cleanup the bridge connection."""
        try:
            # Add any bridge-specific cleanup here if needed
            pass
        except Exception:
            logger.exception("Failed to cleanup InProcessBridge")

    @property
    def bridge(self) -> InProcessBridge:
        """Access the underlying bridge."""
        return self._bridge

    def is_available(self) -> bool:
        """Check if the backend is available."""
        return self._lifecycle.is_available

    async def _execute_command(
        self,
        command: str,
        args: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute a debugger command in-process."""
        if args is None:
            args = {}
        
        # kwargs is unused but required for interface compatibility
        _ = kwargs

        # Command dispatch mapping
        command_handlers = {
            "set_breakpoints": self._handle_set_breakpoints,
            "set_function_breakpoints": self._handle_set_function_breakpoints,
            "set_exception_breakpoints": self._handle_set_exception_breakpoints,
            "continue": self._handle_continue,
            "next": self._handle_next,
            "step_in": self._handle_step_in,
            "step_out": self._handle_step_out,
            "pause": self._handle_pause,
            "get_stack_trace": self._handle_get_stack_trace,
            "get_variables": self._handle_get_variables,
            "set_variable": self._handle_set_variable,
            "evaluate": self._handle_evaluate,
            "completions": self._handle_completions,
            "exception_info": self._handle_exception_info,
            "configuration_done": self._handle_configuration_done,
            "terminate": self._handle_terminate,
        }

        handler = command_handlers.get(command)
        if handler is None:
            error_msg = f"Unknown command: {command}"
            raise ValueError(error_msg)

        try:
            return await handler(args)
        except Exception as e:
            logger.exception(f"In-process command '{command}' failed")
            error_msg = f"Command '{command}' failed: {e}"
            raise ValueError(error_msg) from e

    # Command handlers
    async def _handle_set_breakpoints(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle set_breakpoints command."""
        result = self._bridge.set_breakpoints(args["path"], args["breakpoints"])
        return {"breakpoints": result}

    async def _handle_set_function_breakpoints(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle set_function_breakpoints command."""
        result = self._bridge.set_function_breakpoints(args["breakpoints"])
        return {"breakpoints": list(result)}

    async def _handle_set_exception_breakpoints(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle set_exception_breakpoints command."""
        result = self._bridge.set_exception_breakpoints(args["filters"])
        return {"breakpoints": list(result)}

    async def _handle_continue(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle continue command."""
        return cast("dict", self._bridge.continue_(args["thread_id"]))

    async def _handle_next(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle next command."""
        self._bridge.next_(args["thread_id"])
        return {}

    async def _handle_step_in(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle step_in command."""
        self._bridge.step_in(args["thread_id"])
        return {}

    async def _handle_step_out(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle step_out command."""
        self._bridge.step_out(args["thread_id"])
        return {}

    async def _handle_pause(self, _args: dict[str, Any]) -> dict[str, Any]:
        """Handle pause command."""
        # In-process doesn't support pause
        return {"sent": False}

    async def _handle_get_stack_trace(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle get_stack_trace command."""
        return cast("dict", self._bridge.stack_trace(
            args["thread_id"], args["start_frame"], args["levels"]
        ))

    async def _handle_get_variables(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle get_variables command."""
        result = self._bridge.variables(
            args["variables_reference"],
            filter_type=args.get("filter") or None,
            start=args.get("start") if args.get("start", 0) > 0 else None,
            count=args.get("count") if args.get("count", 0) > 0 else None,
        )
        if isinstance(result, list):
            return {"variables": result}
        return cast("dict", result)

    async def _handle_set_variable(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle set_variable command."""
        return cast("dict", self._bridge.set_variable(
            args["variables_reference"], args["name"], args["value"]
        ))

    async def _handle_evaluate(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle evaluate command."""
        return cast("dict", self._bridge.evaluate(
            args["expression"], args.get("frame_id"), args.get("context")
        ))

    async def _handle_completions(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle completions command for expression auto-complete."""
        return cast("dict", self._bridge.completions(
            args["text"],
            args["column"],
            args.get("frame_id"),
            args.get("line", 1),
        ))

    async def _handle_exception_info(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle exception_info command."""
        thread_id = args["thread_id"]
        try:
            # Access the debugger's exception handler through public interface
            inproc_debugger = getattr(self._bridge, "_inproc", None)
            if inproc_debugger:
                debugger = getattr(inproc_debugger, "debugger", None)
                if debugger and hasattr(debugger, "current_exception_info"):
                    # Use the public property to access exception info
                    exception_info_map = debugger.current_exception_info
                    exception_info = exception_info_map.get(thread_id)
                    if exception_info:
                        return {
                            "exceptionId": exception_info.get("exceptionId", "Unknown"),
                            "description": exception_info.get("description", "Exception occurred"),
                            "breakMode": exception_info.get("breakMode", "unhandled"),
                            "details": exception_info.get("details", {
                                "message": "Exception information available",
                                "typeName": exception_info.get("exceptionId", "Unknown"),
                                "fullTypeName": exception_info.get("exceptionId", "Unknown"),
                                "source": "in-process debugger",
                                "stackTrace": exception_info.get("stackTrace", ["Stack trace available"]),
                            }),
                        }
        except Exception:
            logger.exception("Failed to get exception info from in-process debugger")

        # Fallback to placeholder if no real exception info available
        return {
            "exceptionId": "Unknown",
            "description": "No exception information available",
            "breakMode": "unhandled",
            "details": {
                "message": "No exception currently active",
                "typeName": "None",
                "fullTypeName": "None",
                "source": "in-process debugger",
                "stackTrace": ["No exception stack trace available"],
            },
        }

    async def _handle_configuration_done(self, _args: dict[str, Any]) -> dict[str, Any]:
        """Handle configuration_done command."""
        # No-op for in-process
        return {}

    async def _handle_terminate(self, _args: dict[str, Any]) -> dict[str, Any]:
        """Handle terminate command."""
        # No-op for in-process
        return {}

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
        filter_options: list[dict[str, Any]] | None = None,  # noqa: ARG002
        exception_options: list[dict[str, Any]] | None = None,  # noqa: ARG002
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

    async def pause(self, thread_id: int) -> bool:  # noqa: ARG002
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

    async def exception_info(self, thread_id: int) -> ExceptionInfoResponseBody:
        """Get exception information for a thread."""
        try:
            # Access the debugger's exception handler through public interface
            inproc_debugger = getattr(self._bridge, "_inproc", None)
            if inproc_debugger:
                debugger = getattr(inproc_debugger, "debugger", None)
                if debugger and hasattr(debugger, "current_exception_info"):
                    # Use the public property to access exception info
                    exception_info_map = debugger.current_exception_info
                    exception_info = exception_info_map.get(thread_id)
                    if exception_info:
                        return {
                            "exceptionId": exception_info.get("exceptionId", "Unknown"),
                            "description": exception_info.get("description", "Exception occurred"),
                            "breakMode": exception_info.get("breakMode", "unhandled"),
                            "details": exception_info.get("details", {
                                "message": "Exception information available",
                                "typeName": exception_info.get("exceptionId", "Unknown"),
                                "fullTypeName": exception_info.get("exceptionId", "Unknown"),
                                "source": "in-process debugger",
                                "stackTrace": exception_info.get("stackTrace", ["Stack trace available"]),
                            }),
                        }
        except Exception:
            logger.exception("Failed to get exception info from in-process debugger")
        
        # Fallback to placeholder if no real exception info available
        return {
            "exceptionId": "Unknown",
            "description": "No exception information available",
            "breakMode": "unhandled",
            "details": {
                "message": "No exception currently active",
                "typeName": "None",
                "fullTypeName": "None",
                "source": "in-process debugger",
                "stackTrace": ["No exception stack trace available"],
            },
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def configuration_done(self) -> None:
        """Signal that configuration is done. No-op for in-process."""

    async def initialize(self) -> None:
        """Initialize the in-process backend."""
        await self._lifecycle.initialize()
        
        # Verify bridge is available
        try:
            # Add any bridge-specific initialization here
            pass
        except Exception as e:
            await self._lifecycle.mark_error(f"Bridge initialization failed: {e}")
            raise
        
        await self._lifecycle.mark_ready()
    
    async def launch(self, config: DapperConfig) -> None:
        """Launch in-process debugging session."""
        # Config parameter required by protocol but unused for in-process debugging
        _ = config  # Mark as intentionally unused
        await self.initialize()
        
        # In-process debugging doesn't need separate launch/attach
        # The bridge is already connected to the current process
        logger.info("In-process debugging session started")
    
    async def attach(self, config: DapperConfig) -> None:
        """Attach to in-process debugging session."""
        # Config parameter required by protocol but unused for in-process debugging
        _ = config  # Mark as intentionally unused
        await self.initialize()
        
        # For in-process, attach and launch are the same
        logger.info("In-process debugging session attached")
    
    async def terminate(self) -> None:
        """Terminate the debuggee."""
        await self._lifecycle.begin_termination()
        try:
            # In-process debugging doesn't need explicit termination
            logger.info("In-process debugging session terminated")
        except Exception as e:
            logger.warning(f"Error during in-process termination: {e}")
            await self._lifecycle.mark_error(f"Termination failed: {e}")
        finally:
            await self._lifecycle.complete_termination()
