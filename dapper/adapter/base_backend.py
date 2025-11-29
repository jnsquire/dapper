"""Base backend class with common functionality.

This module provides a base class that implements common patterns
used by all debugger backends to reduce code duplication.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC
from abc import abstractmethod
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from dapper.adapter.debugger_backend import DebuggerBackend
from dapper.errors import BackendError
from dapper.errors import DapperTimeoutError

if TYPE_CHECKING:
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


class BaseBackend(DebuggerBackend, ABC):
    """Base class for debugger backends with common functionality."""
    
    def __init__(self, timeout_seconds: float = 30.0) -> None:
        """Initialize the base backend.
        
        Args:
            timeout_seconds: Default timeout for operations
        """
        self._timeout_seconds = timeout_seconds
        self._available = True
        self._lock = asyncio.Lock()
    
    @abstractmethod
    async def _execute_command(
        self,
        command: str,
        args: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute a command on the backend.
        
        This method must be implemented by concrete backends to handle
        the actual communication with the debugger.
        
        Args:
            command: The command to execute
            args: Additional arguments for the command
            **kwargs: Additional keyword arguments
            
        Returns:
            The command response
        """
        ...
    
    async def _execute_with_timeout(
        self,
        command: str,
        args: dict[str, Any] | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute a command with timeout handling.
        
        Args:
            command: The command to execute
            args: Additional arguments for the command
            timeout: Override the default timeout
            **kwargs: Additional keyword arguments
            
        Returns:
            The command response
            
        Raises:
            TimeoutError: If the command times out
            BackendError: If the command fails
        """
        timeout = timeout or self._timeout_seconds
        
        try:
            return await asyncio.wait_for(
                self._execute_command(command, args, **kwargs),
                timeout=timeout,
            )
        except asyncio.TimeoutError as e:
            msg = f"Command '{command}' timed out after {timeout}s"
            raise DapperTimeoutError(
                msg,
                timeout_seconds=timeout,
                operation=command,
            ) from e
        except Exception as e:
            if isinstance(e, BackendError):
                raise
            msg = f"Command '{command}' failed: {e!s}"
            raise BackendError(
                msg,
                operation=command,
                cause=e,
            ) from e
    
    def is_available(self) -> bool:
        """Check if the backend is available and ready."""
        return self._available
    
    def _set_available(self, available: bool) -> None:
        """Set the availability status."""
        self._available = available
    
    # ------------------------------------------------------------------
    # Default implementations that delegate to _execute_command
    # ------------------------------------------------------------------
    
    async def set_breakpoints(
        self,
        path: str,
        breakpoints: list[SourceBreakpoint],
    ) -> list[Breakpoint]:
        """Set line breakpoints for a file."""
        response = await self._execute_with_timeout(
            "set_breakpoints",
            {"path": path, "breakpoints": breakpoints},
        )
        return cast("list[Breakpoint]", response.get("breakpoints", []))
    
    async def set_function_breakpoints(
        self,
        breakpoints: list[FunctionBreakpoint],
    ) -> list[FunctionBreakpoint]:
        """Set function breakpoints."""
        response = await self._execute_with_timeout(
            "set_function_breakpoints",
            {"breakpoints": breakpoints},
        )
        return cast("list[FunctionBreakpoint]", response.get("breakpoints", []))
    
    async def set_exception_breakpoints(
        self,
        filters: list[str],
        filter_options: list[dict[str, Any]] | None = None,
        exception_options: list[dict[str, Any]] | None = None,
    ) -> list[Breakpoint]:
        """Set exception breakpoints."""
        response = await self._execute_with_timeout(
            "set_exception_breakpoints",
            {
                "filters": filters,
                "filter_options": filter_options,
                "exception_options": exception_options,
            },
        )
        return cast("list[Breakpoint]", response.get("breakpoints", []))
    
    async def continue_(self, thread_id: int) -> ContinueResponseBody:
        """Continue execution."""
        response = await self._execute_with_timeout(
            "continue",
            {"thread_id": thread_id},
        )
        return cast("ContinueResponseBody", response)
    
    async def next_(self, thread_id: int) -> None:
        """Step over."""
        await self._execute_with_timeout(
            "next",
            {"thread_id": thread_id},
        )
    
    async def step_in(self, thread_id: int) -> None:
        """Step into."""
        await self._execute_with_timeout(
            "step_in",
            {"thread_id": thread_id},
        )
    
    async def step_out(self, thread_id: int) -> None:
        """Step out."""
        await self._execute_with_timeout(
            "step_out",
            {"thread_id": thread_id},
        )
    
    async def pause(self, thread_id: int) -> bool:
        """Pause execution. Returns True if pause was sent."""
        response = await self._execute_with_timeout(
            "pause",
            {"thread_id": thread_id},
        )
        return bool(response.get("sent", False))
    
    async def get_stack_trace(
        self,
        thread_id: int,
        start_frame: int = 0,
        levels: int = 0,
    ) -> StackTraceResponseBody:
        """Get stack trace for a thread."""
        response = await self._execute_with_timeout(
            "get_stack_trace",
            {
                "thread_id": thread_id,
                "start_frame": start_frame,
                "levels": levels,
            },
        )
        return cast("StackTraceResponseBody", response)
    
    async def get_variables(
        self,
        variables_reference: int,
        filter_type: str = "",
        start: int = 0,
        count: int = 0,
    ) -> list[Variable]:
        """Get variables for the given reference."""
        response = await self._execute_with_timeout(
            "get_variables",
            {
                "variables_reference": variables_reference,
                "filter": filter_type,
                "start": start,
                "count": count,
            },
        )
        return cast("list[Variable]", response.get("variables", []))
    
    async def set_variable(
        self,
        var_ref: int,
        name: str,
        value: str,
    ) -> SetVariableResponseBody:
        """Set a variable value."""
        response = await self._execute_with_timeout(
            "set_variable",
            {
                "variables_reference": var_ref,
                "name": name,
                "value": value,
            },
        )
        return cast("SetVariableResponseBody", response)
    
    async def evaluate(
        self,
        expression: str,
        frame_id: int | None = None,
        context: str | None = None,
    ) -> EvaluateResponseBody:
        """Evaluate an expression."""
        response = await self._execute_with_timeout(
            "evaluate",
            {
                "expression": expression,
                "frame_id": frame_id,
                "context": context,
            },
        )
        return cast("EvaluateResponseBody", response)
    
    async def exception_info(self, thread_id: int) -> ExceptionInfoResponseBody:
        """Get exception information for a thread."""
        response = await self._execute_with_timeout(
            "exception_info",
            {"thread_id": thread_id},
        )
        return cast("ExceptionInfoResponseBody", response)
    
    async def configuration_done(self) -> None:
        """Signal that configuration is done."""
        await self._execute_with_timeout("configuration_done")
    
    async def terminate(self) -> None:
        """Terminate the debuggee."""
        try:
            await self._execute_with_timeout("terminate")
        except Exception as e:
            logger.warning(f"Error during termination: {e}")
        finally:
            self._set_available(False)


class CommandExecutor(ABC):
    """Helper class for executing commands with different patterns."""
    
    @abstractmethod
    async def send_command(
        self,
        command: str,
        args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a command and get the response."""
        ...
    
    @abstractmethod
    async def wait_for_response(
        self,
        command_id: int,
        timeout: float,
    ) -> dict[str, Any]:
        """Wait for a response to a specific command."""
        ...


class AsyncCommandExecutor(CommandExecutor):
    """Command executor that uses async/await patterns."""
    
    def __init__(self, timeout: float = 30.0) -> None:
        self._timeout = timeout
        self._pending_commands: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._next_command_id = 1
        self._lock = asyncio.Lock()
    
    async def send_command(
        self,
        command: str,
        args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a command and return the future for the response."""
        async with self._lock:
            command_id = self._next_command_id
            self._next_command_id += 1
        
        future = asyncio.Future[dict[str, Any]]()
        self._pending_commands[command_id] = future
        
        try:
            # Send the command (implementation-specific)
            await self._send_command_impl(command_id, command, args or {})
            
            # Wait for the response
            return await self.wait_for_response(command_id, self._timeout)
        finally:
            self._pending_commands.pop(command_id, None)
    
    @abstractmethod
    async def _send_command_impl(
        self,
        command_id: int,
        command: str,
        args: dict[str, Any],
    ) -> None:
        """Implementation-specific command sending."""
        ...
    
    async def wait_for_response(
        self,
        command_id: int,
        timeout: float,
    ) -> dict[str, Any]:
        """Wait for a response to a specific command."""
        if command_id not in self._pending_commands:
            error_msg = f"Command {command_id} not found"
            raise BackendError(error_msg)
        
        future = self._pending_commands[command_id]
        
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as e:
            timeout_msg = f"Command {command_id} timed out"
            raise DapperTimeoutError(
                timeout_msg,
                timeout_seconds=timeout,
                operation="wait_for_response",
            ) from e
    
    def handle_response(self, command_id: int, response: dict[str, Any]) -> None:
        """Handle an incoming response."""
        if command_id in self._pending_commands:
            future = self._pending_commands[command_id]
            if not future.done():
                future.set_result(response)
        else:
            logger.warning(f"Received response for unknown command {command_id}")
    
    def handle_error(self, command_id: int, error: Exception) -> None:
        """Handle an incoming error."""
        if command_id in self._pending_commands:
            future = self._pending_commands[command_id]
            if not future.done():
                future.set_exception(error)
        else:
            logger.warning(f"Received error for unknown command {command_id}")
