"""In-process backend for PyDebugger.

This module provides the InProcessBackend class that wraps InProcessBridge
with an async interface matching the DebuggerBackend protocol.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from typing import Any

from dapper.adapter.base_backend import BaseBackend

if TYPE_CHECKING:
    from dapper.adapter.inprocess_bridge import InProcessBridge
    from dapper.config import DapperConfig
    from dapper.protocol.debugger_protocol import Variable
    from dapper.protocol.requests import CompletionsResponseBody
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

        # Pre-built dispatch map to avoid rebuilding nested async wrappers on
        # every command execution. Handlers accept an `args` dict.
        self._dispatch_map = {
            "set_breakpoints": self._handler_set_breakpoints,
            "set_function_breakpoints": self._handler_set_function_breakpoints,
            "set_exception_breakpoints": self._handler_set_exception_breakpoints,
            "continue": self._handler_continue,
            "next": self._handler_next,
            "step_in": self._handler_step_in,
            "step_out": self._handler_step_out,
            "pause": self._handler_pause,
            "get_stack_trace": self._handler_get_stack_trace,
            "get_variables": self._handler_get_variables,
            "set_variable": self._handler_set_variable,
            "evaluate": self._handler_evaluate,
            "completions": self._handler_completions,
            "exception_info": self._handler_exception_info,
            "configuration_done": self._handler_configuration_done,
            "terminate": self._handler_terminate,
        }

    @property
    def bridge(self) -> InProcessBridge:
        """Access the underlying bridge."""
        return self._bridge

    def is_available(self) -> bool:
        """Check if the backend is available."""
        return self._lifecycle.is_available

    # -------------------------
    # Generic per-command handlers
    # -------------------------

    async def _handler_set_breakpoints(self, args: dict[str, Any]) -> dict[str, Any]:
        r = await self.set_breakpoints(args["path"], args["breakpoints"])
        return {"breakpoints": r}

    async def _handler_set_function_breakpoints(self, args: dict[str, Any]) -> dict[str, Any]:
        r = await self.set_function_breakpoints(args["breakpoints"])
        return {"breakpoints": r}

    async def _handler_set_exception_breakpoints(self, args: dict[str, Any]) -> dict[str, Any]:
        r = await self.set_exception_breakpoints(args["filters"])
        return {"breakpoints": r}

    async def _handler_continue(self, args: dict[str, Any]) -> dict[str, Any]:
        return dict(await self.continue_(args["thread_id"]))

    async def _handler_next(self, args: dict[str, Any]) -> dict[str, Any]:
        await self.next_(args["thread_id"])
        return {}

    async def _handler_step_in(self, args: dict[str, Any]) -> dict[str, Any]:
        await self.step_in(args["thread_id"])
        return {}

    async def _handler_step_out(self, args: dict[str, Any]) -> dict[str, Any]:
        await self.step_out(args["thread_id"])
        return {}

    async def _handler_pause(self, args: dict[str, Any]) -> dict[str, Any]:
        sent = await self.pause(args.get("thread_id", 1))
        return {"sent": sent}

    async def _handler_get_stack_trace(self, args: dict[str, Any]) -> dict[str, Any]:
        return dict(
            await self.get_stack_trace(
                args["thread_id"],
                args.get("start_frame", 0),
                args.get("levels", 0),
            ),
        )

    async def _handler_get_variables(self, args: dict[str, Any]) -> dict[str, Any]:
        v = await self.get_variables(
            args["variables_reference"],
            args.get("filter_type", ""),
            args.get("start", 0),
            args.get("count", 0),
        )
        return {"variables": v}

    async def _handler_set_variable(self, args: dict[str, Any]) -> dict[str, Any]:
        return dict(
            await self.set_variable(args["variables_reference"], args["name"], args["value"]),
        )

    async def _handler_evaluate(self, args: dict[str, Any]) -> dict[str, Any]:
        return dict(
            await self.evaluate(args["expression"], args.get("frame_id"), args.get("context")),
        )

    async def _handler_completions(self, args: dict[str, Any]) -> dict[str, Any]:
        return dict(
            await self.completions(
                args["text"],
                args["column"],
                args.get("frame_id"),
                args.get("line", 1),
            ),
        )

    async def _handler_exception_info(self, args: dict[str, Any]) -> dict[str, Any]:
        return dict(await self.exception_info(args["thread_id"]))

    async def _handler_configuration_done(self, _args: dict[str, Any]) -> dict[str, Any]:
        await self.configuration_done()
        return {}

    async def _handler_terminate(self, _args: dict[str, Any]) -> dict[str, Any]:
        await self.terminate()
        return {}

    def _build_dispatch_table(
        self,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        """Back-compat builder that delegates to the prebuilt handlers.

        Kept for backward compatibility with older subclasses/tests that
        expect `_build_dispatch_table` to return zero-arg callables. New
        callers should prefer `self._dispatch_map`.
        """

        # Reuse the class-level handlers by wrapping them into zero-arg
        # callables that capture the `args` dict. This keeps behavior
        # identical while eliminating repeated nested-function definitions
        # in hot paths where `_dispatch_map` is not used.
        def _wrap(h):
            return lambda: h(args)

        return {name: _wrap(handler) for name, handler in self._dispatch_map.items()}

    async def _execute_command(
        self,
        command: str,
        args: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute a debugger command in-process with error wrapping."""
        try:
            return await super()._execute_command(command, args, **kwargs)
        except ValueError:
            raise
        except Exception as e:
            logger.exception(f"In-process command '{command}' failed")
            error_msg = f"Command '{command}' failed: {e}"
            raise ValueError(error_msg) from e

    # ------------------------------------------------------------------
    # Breakpoint operations
    # ------------------------------------------------------------------
    async def set_breakpoints(
        self,
        path: str,
        breakpoints: list[SourceBreakpoint],
    ) -> list[Breakpoint]:
        """Set line breakpoints for a file."""
        try:
            return self._bridge.set_breakpoints(path, breakpoints)
        except Exception:
            logger.exception("in-process set_breakpoints failed")
            return [{"verified": False} for _ in breakpoints]

    async def set_function_breakpoints(
        self,
        breakpoints: list[FunctionBreakpoint],
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
            result = self._bridge.continue_(thread_id)
            return self._normalize_continue_payload(
                result,
                default_all_threads_continued=True,
                default_for_non_dict=False,
            )
        except Exception:
            logger.exception("in-process continue failed")
            return {"allThreadsContinued": False}

    async def next_(self, thread_id: int, *, granularity: str = "line") -> None:
        """Step over."""
        try:
            self._bridge.next_(thread_id, granularity=granularity)
        except Exception:
            logger.exception("in-process next failed")

    async def step_in(
        self,
        thread_id: int,
        target_id: int | None = None,
        *,
        granularity: str = "line",
    ) -> None:
        """Step into."""
        try:
            self._bridge.step_in(thread_id, target_id, granularity=granularity)
        except Exception:
            logger.exception("in-process step_in failed")

    async def step_out(self, thread_id: int, *, granularity: str = "line") -> None:
        """Step out."""
        try:
            self._bridge.step_out(thread_id, granularity=granularity)
        except Exception:
            logger.exception("in-process step_out failed")

    async def pause(self, thread_id: int) -> bool:  # noqa: ARG002
        """Pause execution. In-process debugger does not support pause."""
        return False

    # ------------------------------------------------------------------
    # Inspection operations
    # ------------------------------------------------------------------
    async def get_stack_trace(
        self,
        thread_id: int,
        start_frame: int = 0,
        levels: int = 0,
    ) -> StackTraceResponseBody:
        """Get stack trace for a thread."""
        try:
            return self._bridge.stack_trace(thread_id, start_frame, levels)
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
            return self._bridge.variables(
                variables_reference,
                filter_type=filter_type or None,
                start=start if start > 0 else None,
                count=count if count > 0 else None,
            )
        except Exception:
            logger.exception("in-process variables failed")
            return []

    async def set_variable(self, var_ref: int, name: str, value: str) -> SetVariableResponseBody:
        """Set a variable value."""
        try:
            return self._bridge.set_variable(var_ref, name, value)
        except Exception:
            logger.exception("in-process set_variable failed")
            return {"value": value, "type": "string", "variablesReference": 0}

    async def evaluate(
        self,
        expression: str,
        frame_id: int | None = None,
        context: str | None = None,
    ) -> EvaluateResponseBody:
        """Evaluate an expression."""
        try:
            return self._bridge.evaluate(expression, frame_id, context)
        except Exception:
            logger.exception("in-process evaluate failed")
            return {
                "result": f"<evaluation of '{expression}' not available>",
                "type": "string",
                "variablesReference": 0,
            }

    async def completions(
        self,
        text: str,
        column: int,
        frame_id: int | None = None,
        line: int = 1,
    ) -> CompletionsResponseBody:
        """Get completions for an expression."""
        try:
            return self._bridge.completions(text, column, frame_id, line)
        except Exception:
            logger.exception("in-process completions failed")
            return {"targets": []}

    async def exception_info(self, thread_id: int) -> ExceptionInfoResponseBody:
        """Get exception information for a thread."""
        try:
            # Use bridge accessor to avoid reaching into private internals
            exception_info = None
            try:
                exception_info = self._bridge.get_exception_info(thread_id)
            except Exception:
                logger.exception("bridge.get_exception_info failed")

            if exception_info:
                return {
                    "exceptionId": exception_info.get("exceptionId", "Unknown"),
                    "description": exception_info.get("description", "Exception occurred"),
                    "breakMode": exception_info.get("breakMode", "unhandled"),
                    "details": exception_info.get(
                        "details",
                        {
                            "message": "Exception information available",
                            "typeName": exception_info.get("exceptionId", "Unknown"),
                            "fullTypeName": exception_info.get("exceptionId", "Unknown"),
                            "source": "in-process debugger",
                            "stackTrace": exception_info.get(
                                "stackTrace",
                                ["Stack trace available"],
                            ),
                        },
                    ),
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
            logger.warning("Error during in-process termination: %s", e)
            await self._lifecycle.mark_error(f"Termination failed: {e}")
        finally:
            await self._lifecycle.complete_termination()
