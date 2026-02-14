"""External process backend for PyDebugger.

This module provides the ExternalProcessBackend class that handles communication
with a debuggee running in a separate subprocess via IPC.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from dapper.adapter.base_backend import BaseBackend

if TYPE_CHECKING:
    from dapper.config import DapperConfig
    from dapper.ipc.ipc_manager import IPCManager
    from dapper.protocol.debugger_protocol import Variable
    from dapper.protocol.requests import CompletionsResponseBody
    from dapper.protocol.requests import ContinueResponseBody
    from dapper.protocol.requests import EvaluateResponseBody
    from dapper.protocol.requests import ExceptionDetails
    from dapper.protocol.requests import ExceptionInfoResponseBody
    from dapper.protocol.requests import FunctionBreakpoint
    from dapper.protocol.requests import SetVariableResponseBody
    from dapper.protocol.requests import StackTraceResponseBody
    from dapper.protocol.structures import Breakpoint
    from dapper.protocol.structures import SourceBreakpoint

logger = logging.getLogger(__name__)


class ExternalProcessBackend(BaseBackend):
    """Backend for debugging via external subprocess + IPC.

    This class encapsulates all the logic for sending commands to and
    receiving responses from a debuggee running in a separate process.
    """

    def __init__(
        self,
        ipc: IPCManager,
        loop: asyncio.AbstractEventLoop,
        get_process_state: Any,  # Callable returning (process, is_terminated)
        pending_commands: dict[int, asyncio.Future[dict[str, Any]]],
        lock: Any,  # threading.RLock
        get_next_command_id: Any,  # Callable returning int
    ) -> None:
        """Initialize the external process backend.

        Args:
            ipc: IPC context for communication
            loop: Event loop for async operations
            get_process_state: Callable returning (process, is_terminated) tuple
            pending_commands: Dict of pending command futures (shared with PyDebugger)
            lock: Threading lock for synchronization
            get_next_command_id: Callable to get next command ID
        """
        super().__init__()
        self._ipc = ipc
        self._loop = loop
        self._get_process_state = get_process_state
        self._pending_commands = pending_commands
        self._lock = lock
        self._get_next_command_id = get_next_command_id

        # Register cleanup callbacks
        self._lifecycle.add_cleanup_callback(self._cleanup_ipc)
        self._lifecycle.add_cleanup_callback(self._cleanup_commands)

    def _cleanup_ipc(self) -> None:
        """Cleanup IPC connection."""
        try:
            # IPC cleanup depends on the specific IPC implementation
            # Add implementation-specific cleanup here if needed
            pass
        except Exception:
            logger.exception("Failed to cleanup IPC connection")

    def _cleanup_commands(self) -> None:
        """Cleanup pending commands."""
        try:
            with self._lock:
                for future in self._pending_commands.values():
                    if not future.done():
                        future.cancel()
                self._pending_commands.clear()
        except Exception:
            logger.exception("Failed to cleanup pending commands")

    def is_available(self) -> bool:
        """Check if the backend is available."""
        if not self._lifecycle.is_available:
            return False

        process, is_terminated = self._get_process_state()
        return process is not None and not is_terminated

    def _extract_body(
        self, response: dict[str, Any] | None, default: dict[str, Any]
    ) -> dict[str, Any]:
        """Extract the body from a response, returning default if unavailable."""
        if not response:
            return default
        return response.get("body", default)

    async def _execute_command(
        self,
        command: str,
        args: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        """Execute a command on the external process.

        Args:
            command: The command to execute
            args: Additional arguments for the command
            **kwargs: Additional keyword arguments

        Returns:
            The command response
        """
        if not self.is_available():
            raise RuntimeError("External process not available")

        if args is None:
            args = {}

        # Build dispatch table that maps command names to async handlers.
        # Each handler returns a dict[str, Any] for consistency.
        async def _bp() -> dict[str, Any]:
            r = await self.set_breakpoints(args["path"], args["breakpoints"])
            return {"breakpoints": r}

        async def _fbp() -> dict[str, Any]:
            r = await self.set_function_breakpoints(args["breakpoints"])
            return {"breakpoints": r}

        async def _ebp() -> dict[str, Any]:
            r = await self.set_exception_breakpoints(
                args["filters"], args.get("filter_options"), args.get("exception_options")
            )
            return {"breakpoints": r}

        async def _cont() -> dict[str, Any]:
            return dict(await self.continue_(args["thread_id"]))

        async def _next() -> dict[str, Any]:
            await self.next_(args["thread_id"])
            return {}

        async def _step_in() -> dict[str, Any]:
            await self.step_in(args["thread_id"])
            return {}

        async def _step_out() -> dict[str, Any]:
            await self.step_out(args["thread_id"])
            return {}

        async def _pause() -> dict[str, Any]:
            sent = await self.pause(args["thread_id"])
            return {"sent": sent}

        async def _stack() -> dict[str, Any]:
            return dict(
                await self.get_stack_trace(
                    args["thread_id"], args.get("start_frame", 0), args.get("levels", 0)
                )
            )

        async def _vars() -> dict[str, Any]:
            v = await self.get_variables(
                args["variables_reference"],
                args.get("filter_type", ""),
                args.get("start", 0),
                args.get("count", 0),
            )
            return {"variables": v}

        async def _set_var() -> dict[str, Any]:
            return dict(await self.set_variable(args["var_ref"], args["name"], args["value"]))

        async def _eval() -> dict[str, Any]:
            return dict(
                await self.evaluate(args["expression"], args.get("frame_id"), args.get("context"))
            )

        async def _compl() -> dict[str, Any]:
            return dict(
                await self.completions(
                    args["text"], args["column"], args.get("frame_id"), args.get("line", 1)
                )
            )

        async def _exc_info() -> dict[str, Any]:
            return dict(await self.exception_info(args["thread_id"]))

        async def _cfg_done() -> dict[str, Any]:
            await self.configuration_done()
            return {}

        async def _term() -> dict[str, Any]:
            await self._send_command({"command": "terminate"})
            return {}

        dispatch: dict[str, Any] = {
            "set_breakpoints": _bp,
            "set_function_breakpoints": _fbp,
            "set_exception_breakpoints": _ebp,
            "continue": _cont,
            "next": _next,
            "step_in": _step_in,
            "step_out": _step_out,
            "pause": _pause,
            "get_stack_trace": _stack,
            "get_variables": _vars,
            "set_variable": _set_var,
            "evaluate": _eval,
            "completions": _compl,
            "exception_info": _exc_info,
            "configuration_done": _cfg_done,
            "terminate": _term,
        }

        handler = dispatch.get(command)
        if handler is None:
            error_msg = f"Unknown command: {command}"
            raise ValueError(error_msg)
        return await handler()

    async def _send_command(
        self, command: dict[str, Any], expect_response: bool = False
    ) -> dict[str, Any] | None:
        """Send a command to the debuggee process."""
        if not self.is_available():
            return None

        response_future: asyncio.Future[dict[str, Any]] | None = None
        command_id: int = 0  # Only used when expect_response is True

        if expect_response:
            command_id = self._get_next_command_id()
            command["id"] = command_id
            response_future = self._loop.create_future()
            with self._lock:
                self._pending_commands[command_id] = response_future

        try:
            await self._ipc.send_message(command)
        except Exception:
            logger.exception("Error sending command to debuggee")
            if expect_response:
                self._pending_commands.pop(command_id, None)
            return None

        if response_future is None:
            return None

        try:
            return await asyncio.wait_for(response_future, timeout=5.0)
        except asyncio.TimeoutError:
            self._pending_commands.pop(command_id, None)
            return None

    # ------------------------------------------------------------------
    # Breakpoint operations (now handled by _execute_command)
    # ------------------------------------------------------------------
    async def set_breakpoints(
        self, path: str, breakpoints: list[SourceBreakpoint]
    ) -> list[Breakpoint]:
        """Set line breakpoints for a file."""
        command = {
            "command": "setBreakpoints",
            "arguments": {
                "source": {"path": path},
                "breakpoints": [dict(bp) for bp in breakpoints],
            },
        }
        await self._send_command(command)
        # Return verified breakpoints based on input
        return [{"verified": True, "line": bp.get("line")} for bp in breakpoints]

    async def set_function_breakpoints(
        self, breakpoints: list[FunctionBreakpoint]
    ) -> list[FunctionBreakpoint]:
        """Set function breakpoints."""
        command = {
            "command": "setFunctionBreakpoints",
            "arguments": {"breakpoints": [dict(bp) for bp in breakpoints]},
        }
        await self._send_command(command)
        return [{"verified": bp.get("verified", True)} for bp in breakpoints]

    async def set_exception_breakpoints(
        self,
        filters: list[str],
        filter_options: list[dict[str, Any]] | None = None,
        exception_options: list[dict[str, Any]] | None = None,
    ) -> list[Breakpoint]:
        """Set exception breakpoints."""
        args: dict[str, Any] = {"filters": filters}
        if filter_options is not None:
            args["filterOptions"] = filter_options
        if exception_options is not None:
            args["exceptionOptions"] = exception_options

        command = {"command": "setExceptionBreakpoints", "arguments": args}
        await self._send_command(command)
        return [{"verified": True} for _ in filters]

    # ------------------------------------------------------------------
    # Execution control
    # ------------------------------------------------------------------
    async def continue_(self, thread_id: int) -> ContinueResponseBody:
        """Continue execution."""
        command = {"command": "continue", "arguments": {"threadId": thread_id}}
        await self._send_command(command)
        return {"allThreadsContinued": True}

    async def next_(self, thread_id: int) -> None:
        """Step over."""
        command = {"command": "next", "arguments": {"threadId": thread_id}}
        await self._send_command(command)

    async def step_in(self, thread_id: int, target_id: int | None = None) -> None:
        """Step into."""
        args: dict[str, int] = {"threadId": thread_id}
        if target_id is not None:
            args["targetId"] = target_id
        command = {"command": "stepIn", "arguments": args}
        await self._send_command(command)

    async def step_out(self, thread_id: int) -> None:
        """Step out."""
        command = {"command": "stepOut", "arguments": {"threadId": thread_id}}
        await self._send_command(command)

    async def pause(self, thread_id: int) -> bool:
        """Pause execution."""
        command = {"command": "pause", "arguments": {"threadId": thread_id}}
        await self._send_command(command)
        return True

    # ------------------------------------------------------------------
    # Inspection operations
    # ------------------------------------------------------------------
    async def get_stack_trace(
        self, thread_id: int, start_frame: int = 0, levels: int = 0
    ) -> StackTraceResponseBody:
        """Get stack trace for a thread."""
        command = {
            "command": "stackTrace",
            "arguments": {
                "threadId": thread_id,
                "startFrame": start_frame,
                "levels": levels,
            },
        }
        response = await self._send_command(command, expect_response=True)
        body = self._extract_body(response, {"stackFrames": [], "totalFrames": 0})
        return cast("StackTraceResponseBody", body)

    async def get_variables(
        self,
        variables_reference: int,
        filter_type: str = "",
        start: int = 0,
        count: int = 0,
    ) -> list[Variable]:
        """Get variables for the given reference."""
        command: dict[str, Any] = {
            "command": "variables",
            "arguments": {"variablesReference": variables_reference},
        }
        if filter_type:
            command["arguments"]["filter"] = filter_type
        if start > 0:
            command["arguments"]["start"] = start
        if count > 0:
            command["arguments"]["count"] = count

        response = await self._send_command(command, expect_response=True)
        if not response:
            return []
        body = response.get("body", {})
        return cast("list[Variable]", body.get("variables", []))

    async def set_variable(self, var_ref: int, name: str, value: str) -> SetVariableResponseBody:
        """Set a variable value."""
        command = {
            "command": "setVariable",
            "arguments": {
                "variablesReference": var_ref,
                "name": name,
                "value": value,
            },
        }
        response = await self._send_command(command, expect_response=True)
        body = self._extract_body(
            response, {"value": value, "type": "string", "variablesReference": 0}
        )
        return cast("SetVariableResponseBody", body)

    async def evaluate(
        self, expression: str, frame_id: int | None = None, context: str | None = None
    ) -> EvaluateResponseBody:
        """Evaluate an expression."""
        command = {
            "command": "evaluate",
            "arguments": {
                "expression": expression,
                "frameId": frame_id,
                "context": context or "hover",
            },
        }
        response = await self._send_command(command, expect_response=True)
        default = {
            "result": f"<evaluation of '{expression}' not available>",
            "type": "string",
            "variablesReference": 0,
        }
        return cast("EvaluateResponseBody", self._extract_body(response, default))

    async def completions(
        self, text: str, column: int, frame_id: int | None = None, line: int = 1
    ) -> CompletionsResponseBody:
        """Get completions for an expression."""
        command = {
            "command": "completions",
            "arguments": {
                "text": text,
                "column": column,
                "frameId": frame_id,
                "line": line,
            },
        }
        response = await self._send_command(command, expect_response=True)
        return cast("CompletionsResponseBody", self._extract_body(response, {"targets": []}))

    async def exception_info(self, thread_id: int) -> ExceptionInfoResponseBody:
        """Get exception information for a thread."""
        command = {
            "command": "exceptionInfo",
            "arguments": {"threadId": thread_id},
        }
        response = await self._send_command(command, expect_response=True)
        if response and "body" in response:
            return cast("ExceptionInfoResponseBody", response["body"])

        exception_details: ExceptionDetails = {
            "message": "Exception information not available",
            "typeName": "Unknown",
            "fullTypeName": "Unknown",
            "source": "Unknown",
            "stackTrace": ["Exception information not available"],
        }
        return {
            "exceptionId": "Unknown",
            "description": "Exception information not available",
            "breakMode": "unhandled",
            "details": exception_details,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def configuration_done(self) -> None:
        """Signal that configuration is done."""
        command = {"command": "configurationDone"}
        await self._send_command(command)

    async def initialize(self) -> None:
        """Initialize the external process backend."""
        await self._lifecycle.initialize()

        # Verify IPC connection and process are available
        if not self.is_available():
            await self._lifecycle.mark_error("IPC connection or process not available")
            raise RuntimeError("External process backend not available")

        await self._lifecycle.mark_ready()

    async def launch(self, config: DapperConfig) -> None:
        """Launch external process debugging session."""
        # Config parameter required by protocol but unused for external process debugging
        _ = config  # Mark as intentionally unused
        await self.initialize()
        logger.info("External process debugging session started")

    async def attach(self, config: DapperConfig) -> None:
        """Attach to external process debugging session."""
        # Config parameter required by protocol but unused for external process debugging
        _ = config  # Mark as intentionally unused
        await self.initialize()
        logger.info("External process debugging session attached")

    async def terminate(self) -> None:
        """Terminate the debuggee."""
        await self._lifecycle.begin_termination()
        try:
            await self._execute_command("terminate")
        except Exception as e:
            logger.warning(f"Error during external process termination: {e}")
            await self._lifecycle.mark_error(f"Termination failed: {e}")
        finally:
            await self._lifecycle.complete_termination()
