"""External process backend for PyDebugger.

This module provides the ExternalProcessBackend class that handles communication
with a debuggee running in a separate subprocess via IPC.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

if TYPE_CHECKING:
    from dapper.ipc.ipc_context import IPCContext
    from dapper.protocol.debugger_protocol import Variable
    from dapper.protocol.structures import Breakpoint, SourceBreakpoint
    from dapper.protocol.requests import (
        ContinueResponseBody,
        EvaluateResponseBody,
        ExceptionDetails,
        ExceptionInfoResponseBody,
        FunctionBreakpoint,
        SetVariableResponseBody,
        StackTraceResponseBody,
    )

logger = logging.getLogger(__name__)


class ExternalProcessBackend:
    """Backend for debugging via external subprocess + IPC.

    This class encapsulates all the logic for sending commands to and
    receiving responses from a debuggee running in a separate process.
    """

    def __init__(
        self,
        ipc: IPCContext,
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
        self._ipc = ipc
        self._loop = loop
        self._get_process_state = get_process_state
        self._pending_commands = pending_commands
        self._lock = lock
        self._get_next_command_id = get_next_command_id

    def is_available(self) -> bool:
        """Check if the backend is available."""
        process, is_terminated = self._get_process_state()
        return process is not None and not is_terminated

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
            await asyncio.to_thread(self._ipc.write_command, json.dumps(command))
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
    # Breakpoint operations
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

    async def step_in(self, thread_id: int) -> None:
        """Step into."""
        command = {"command": "stepIn", "arguments": {"threadId": thread_id}}
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
        if response and "body" in response:
            return response["body"]
        return {"stackFrames": [], "totalFrames": 0}

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
        if response and "body" in response and "variables" in response["body"]:
            return cast("list[Variable]", response["body"]["variables"])
        return []

    async def set_variable(
        self, var_ref: int, name: str, value: str
    ) -> SetVariableResponseBody:
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
        if response and "body" in response:
            return response["body"]
        return {"value": value, "type": "string", "variablesReference": 0}

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
        if response and "body" in response:
            return response["body"]
        return {
            "result": f"<evaluation of '{expression}' not available>",
            "type": "string",
            "variablesReference": 0,
        }

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
            "stackTrace": "Exception information not available",
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

    async def terminate(self) -> None:
        """Terminate the debuggee."""
        command = {"command": "terminate"}
        await self._send_command(command)
