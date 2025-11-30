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

from dapper.adapter.base_backend import BaseBackend

if TYPE_CHECKING:
    from dapper.config import DapperConfig
    from dapper.ipc.ipc_adapter import IPCContextAdapter
    from dapper.ipc.ipc_context import IPCContext
    from dapper.protocol.debugger_protocol import Variable
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
        ipc: IPCContext | IPCContextAdapter,
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
            "exception_info": self._handle_exception_info,
            "configuration_done": self._handle_configuration_done,
            "terminate": self._handle_terminate,
        }

        handler = command_handlers.get(command)
        if handler is None:
            error_msg = f"Unknown command: {command}"
            raise ValueError(error_msg)

        return await handler(args)

    # Command handlers
    async def _handle_set_breakpoints(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle set_breakpoints command."""
        cmd = {
            "command": "setBreakpoints",
            "arguments": {
                "source": {"path": args["path"]},
                "breakpoints": [dict(bp) for bp in args["breakpoints"]],
            },
        }
        return await self._send_command(cmd, expect_response=False) or {}

    async def _handle_set_function_breakpoints(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle set_function_breakpoints command."""
        cmd = {
            "command": "setFunctionBreakpoints",
            "arguments": {"breakpoints": [dict(bp) for bp in args["breakpoints"]]},
        }
        return await self._send_command(cmd, expect_response=False) or {}

    async def _handle_set_exception_breakpoints(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle set_exception_breakpoints command."""
        cmd_args: dict[str, Any] = {"filters": args["filters"]}
        if args.get("filter_options") is not None:
            cmd_args["filterOptions"] = args["filter_options"]
        if args.get("exception_options") is not None:
            cmd_args["exceptionOptions"] = args["exception_options"]
        
        cmd = {"command": "setExceptionBreakpoints", "arguments": cmd_args}
        return await self._send_command(cmd, expect_response=False) or {}

    async def _handle_continue(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle continue command."""
        cmd = {"command": "continue", "arguments": {"threadId": args["thread_id"]}}
        return await self._send_command(cmd, expect_response=False) or {"allThreadsContinued": True}

    async def _handle_next(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle next command."""
        cmd = {"command": "next", "arguments": {"threadId": args["thread_id"]}}
        return await self._send_command(cmd, expect_response=False) or {}

    async def _handle_step_in(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle step_in command."""
        cmd = {"command": "stepIn", "arguments": {"threadId": args["thread_id"]}}
        return await self._send_command(cmd, expect_response=False) or {}

    async def _handle_step_out(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle step_out command."""
        cmd = {"command": "stepOut", "arguments": {"threadId": args["thread_id"]}}
        return await self._send_command(cmd, expect_response=False) or {}

    async def _handle_pause(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle pause command."""
        cmd = {"command": "pause", "arguments": {"threadId": args["thread_id"]}}
        return await self._send_command(cmd, expect_response=False) or {"sent": True}

    async def _handle_get_stack_trace(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle get_stack_trace command."""
        cmd = {
            "command": "stackTrace",
            "arguments": {
                "threadId": args["thread_id"],
                "startFrame": args["start_frame"],
                "levels": args["levels"],
            },
        }
        return await self._send_command(cmd, expect_response=True) or {"stackFrames": [], "totalFrames": 0}

    async def _handle_get_variables(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle get_variables command."""
        cmd: dict[str, Any] = {
            "command": "variables",
            "arguments": {"variablesReference": args["variables_reference"]},
        }
        if args.get("filter_type"):
            cmd["arguments"]["filter"] = args["filter_type"]
        if args.get("start", 0) > 0:
            cmd["arguments"]["start"] = args["start"]
        if args.get("count", 0) > 0:
            cmd["arguments"]["count"] = args["count"]
        
        response = await self._send_command(cmd, expect_response=True)
        if response and "body" in response and "variables" in response["body"]:
            return {"variables": response["body"]["variables"]}
        return {"variables": []}

    async def _handle_set_variable(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle set_variable command."""
        cmd = {
            "command": "setVariable",
            "arguments": {
                "variablesReference": args["var_ref"],
                "name": args["name"],
                "value": args["value"],
            },
        }
        response = await self._send_command(cmd, expect_response=True)
        return (response or {}).get("body", {"value": args["value"], "type": "string", "variablesReference": 0})

    async def _handle_evaluate(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle evaluate command."""
        cmd = {
            "command": "evaluate",
            "arguments": {
                "expression": args["expression"],
                "frameId": args.get("frame_id"),
                "context": args.get("context", "hover"),
            },
        }
        response = await self._send_command(cmd, expect_response=True)
        return (response or {}).get("body", {
            "result": f"<evaluation of '{args['expression']}' not available>",
            "type": "string",
            "variablesReference": 0,
        })

    async def _handle_exception_info(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle exception_info command."""
        cmd = {
            "command": "exceptionInfo",
            "arguments": {"threadId": args["thread_id"]},
        }
        response = await self._send_command(cmd, expect_response=True)
        return (response or {}).get("body", {
            "exceptionId": "Unknown",
            "description": "Exception information not available",
            "breakMode": "unhandled",
            "details": {
                "message": "Exception information not available",
                "typeName": "Unknown",
                "fullTypeName": "Unknown",
                "source": "Unknown",
                "stackTrace": ["Exception information not available"],
            },
        })

    async def _handle_configuration_done(self, _args: dict[str, Any]) -> dict[str, Any]:
        """Handle configuration_done command."""
        cmd = {"command": "configurationDone"}
        return await self._send_command(cmd, expect_response=False) or {}

    async def _handle_terminate(self, _args: dict[str, Any]) -> dict[str, Any]:
        """Handle terminate command."""
        cmd = {"command": "terminate"}
        return await self._send_command(cmd, expect_response=False) or {}
    
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
