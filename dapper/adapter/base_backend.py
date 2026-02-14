"""Base backend class with common functionality.

This module provides a base class that implements common patterns
used by all debugger backends to reduce code duplication.
"""

from __future__ import annotations

from abc import ABC
from abc import abstractmethod
import asyncio
import logging
from typing import Any
from typing import TypeVar
from typing import cast
from typing import overload

from dapper.adapter.debugger_backend import DebuggerBackend
from dapper.adapter.lifecycle import LifecycleManager
from dapper.adapter.types import CompletionsResponseBody
from dapper.errors import BackendError
from dapper.errors import DapperTimeoutError
from dapper.errors import async_handle_backend_errors
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

T = TypeVar("T")


def create_timeout_error(command: str, timeout: float) -> DapperTimeoutError:
    """Create a standardized timeout error."""
    timeout_msg = f"Command '{command}' timed out after {timeout}s"
    return DapperTimeoutError(
        timeout_msg,
        timeout_seconds=timeout,
        operation=command,
    )


class BaseBackend(DebuggerBackend, ABC):
    """Base class for debugger backends with common functionality."""

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        """Initialize the base backend.

        Args:
            timeout_seconds: Default timeout for operations
        """
        self._timeout_seconds = timeout_seconds
        self._lock = asyncio.Lock()
        self._lifecycle = LifecycleManager(self.__class__.__name__)

    @abstractmethod
    def _build_dispatch_table(
        self, args: dict[str, Any]
    ) -> dict[str, Any]:
        """Build the command dispatch table.

        Subclasses implement this to map command names to zero-argument
        async handler callables. Each handler returns a ``dict[str, Any]``.

        Args:
            args: The command arguments (closures may reference these).

        Returns:
            Mapping of command name to async handler callable.
        """
        ...

    async def _execute_command(
        self,
        command: str,
        args: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute a command on the backend via the dispatch table.

        Looks up *command* in the table returned by
        ``_build_dispatch_table`` and awaits the matching handler.
        Subclasses may override this to add pre/post processing
        (e.g. availability checks, extra error wrapping) while
        calling ``super()._execute_command(...)`` for the dispatch.

        Args:
            command: The command to execute
            args: Additional arguments for the command
            **kwargs: Additional keyword arguments

        Returns:
            The command response
        """
        if args is None:
            args = {}

        dispatch = self._build_dispatch_table(args)
        handler = dispatch.get(command)
        if handler is None:
            error_msg = f"Unknown command: {command}"
            raise ValueError(error_msg)
        return await handler()

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
        async with self._lifecycle.operation_context(f"execute_{command}"):
            timeout = timeout or self._timeout_seconds

            try:
                return await asyncio.wait_for(
                    self._execute_command(command, args, **kwargs),
                    timeout=timeout,
                )
            except asyncio.TimeoutError as e:
                raise create_timeout_error(command, timeout) from e
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
        return self._lifecycle.is_available

    def is_ready(self) -> bool:
        """Check if the backend is ready for operations."""
        return self._lifecycle.is_ready

    @property
    def lifecycle_state(self):
        """Get the current lifecycle state."""
        return self._lifecycle.state

    @property
    def error_info(self) -> str | None:
        """Get information about the last error."""
        return self._lifecycle.error_info

    # ------------------------------------------------------------------
    # Default implementations that delegate to _execute_command
    # ------------------------------------------------------------------

    @overload
    async def _execute_and_extract(
        self,
        command: str,
        args: dict[str, Any] | None = None,
        *,
        extract_key: str | None = None,
        return_type: type[T],
        timeout: float | None = None,
    ) -> T: ...

    @overload
    async def _execute_and_extract(
        self,
        command: str,
        args: dict[str, Any] | None = None,
        *,
        extract_key: str | None = None,
        return_type: None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]: ...

    async def _execute_and_extract(
        self,
        command: str,
        args: dict[str, Any] | None = None,
        *,
        extract_key: str | None = None,
        return_type: type[T] | None = None,
        timeout: float | None = None,
    ) -> T | dict[str, Any]:
        """Execute a command and optionally extract a specific field.

        Args:
            command: The command to execute
            args: Command arguments
            extract_key: Key to extract from response (if None, returns full response)
            return_type: Type to cast the result to
            timeout: Override timeout

        Returns:
            The extracted field or full response, optionally cast to return_type
        """
        response = await self._execute_with_timeout(command, args, timeout=timeout)

        result = response.get(extract_key, []) if extract_key is not None else response

        return cast("T", result) if return_type else result

    async def set_breakpoints(
        self,
        path: str,
        breakpoints: list[SourceBreakpoint],
    ) -> list[Breakpoint]:
        """Set line breakpoints for a file."""
        return await self._execute_and_extract(
            "set_breakpoints",
            {"path": path, "breakpoints": breakpoints},
            extract_key="breakpoints",
            return_type=list[Breakpoint],
        )

    async def set_function_breakpoints(
        self,
        breakpoints: list[FunctionBreakpoint],
    ) -> list[FunctionBreakpoint]:
        """Set function breakpoints."""
        return await self._execute_and_extract(
            "set_function_breakpoints",
            {"breakpoints": breakpoints},
            extract_key="breakpoints",
            return_type=list[FunctionBreakpoint],
        )

    async def set_exception_breakpoints(
        self,
        filters: list[str],
        filter_options: list[dict[str, Any]] | None = None,
        exception_options: list[dict[str, Any]] | None = None,
    ) -> list[Breakpoint]:
        """Set exception breakpoints."""
        return await self._execute_and_extract(
            "set_exception_breakpoints",
            {
                "filters": filters,
                "filter_options": filter_options,
                "exception_options": exception_options,
            },
            extract_key="breakpoints",
            return_type=list[Breakpoint],
        )

    async def continue_(self, thread_id: int) -> ContinueResponseBody:
        """Continue execution."""
        return await self._execute_and_extract(
            "continue",
            {"thread_id": thread_id},
            return_type=ContinueResponseBody,
        )

    async def next_(self, thread_id: int) -> None:
        """Step over."""
        await self._execute_with_timeout("next", {"thread_id": thread_id})

    async def step_in(self, thread_id: int, target_id: int | None = None) -> None:
        """Step into."""
        args: dict[str, int] = {"thread_id": thread_id}
        if target_id is not None:
            args["target_id"] = target_id
        await self._execute_with_timeout("step_in", args)

    async def step_out(self, thread_id: int) -> None:
        """Step out."""
        await self._execute_with_timeout("step_out", {"thread_id": thread_id})

    async def pause(self, thread_id: int) -> bool:
        """Pause execution. Returns True if pause was sent."""
        response = await self._execute_with_timeout("pause", {"thread_id": thread_id})
        return bool(response.get("sent", False))

    async def get_stack_trace(
        self,
        thread_id: int,
        start_frame: int = 0,
        levels: int = 0,
    ) -> StackTraceResponseBody:
        """Get stack trace for a thread."""
        return await self._execute_and_extract(
            "get_stack_trace",
            {
                "thread_id": thread_id,
                "start_frame": start_frame,
                "levels": levels,
            },
            return_type=StackTraceResponseBody,
        )

    async def get_variables(
        self,
        variables_reference: int,
        filter_type: str = "",
        start: int = 0,
        count: int = 0,
    ) -> list[Variable]:
        """Get variables for the given reference."""
        return await self._execute_and_extract(
            "get_variables",
            {
                "variables_reference": variables_reference,
                "filter": filter_type,
                "start": start,
                "count": count,
            },
            extract_key="variables",
            return_type=list[Variable],
        )

    async def set_variable(
        self,
        var_ref: int,
        name: str,
        value: str,
    ) -> SetVariableResponseBody:
        """Set a variable value."""
        return await self._execute_and_extract(
            "set_variable",
            {
                "variables_reference": var_ref,
                "name": name,
                "value": value,
            },
            return_type=SetVariableResponseBody,
        )

    @async_handle_backend_errors("evaluate")
    async def evaluate(
        self,
        expression: str,
        frame_id: int | None = None,
        context: str | None = None,
    ) -> EvaluateResponseBody:
        """Evaluate an expression."""
        return await self._execute_and_extract(
            "evaluate",
            {
                "expression": expression,
                "frame_id": frame_id,
                "context": context,
            },
            return_type=EvaluateResponseBody,
        )

    @async_handle_backend_errors("completions")
    async def completions(
        self,
        text: str,
        column: int,
        frame_id: int | None = None,
        line: int = 1,
    ) -> CompletionsResponseBody:
        """Get expression completions for the debug console.

        Args:
            text: The input text to complete
            column: Cursor position within text (1-based)
            frame_id: Stack frame for scope context
            line: Line number within text (1-based)

        Returns:
            Dict with 'targets' key containing list of completion items
        """
        return await self._execute_and_extract(
            "completions",
            {
                "text": text,
                "column": column,
                "frame_id": frame_id,
                "line": line,
            },
            return_type=CompletionsResponseBody,
        )

    async def exception_info(self, thread_id: int) -> ExceptionInfoResponseBody:
        """Get exception information for a thread."""
        return await self._execute_and_extract(
            "exception_info",
            {"thread_id": thread_id},
            return_type=ExceptionInfoResponseBody,
        )

    async def configuration_done(self) -> None:
        """Signal that configuration is done."""
        await self._execute_with_timeout("configuration_done")

    async def terminate(self) -> None:
        """Terminate the debuggee."""
        await self._lifecycle.begin_termination()
        try:
            await self._execute_with_timeout("terminate")
        except Exception as e:
            logger.warning(f"Error during termination: {e}")
            await self._lifecycle.mark_error(f"Termination failed: {e}")
        finally:
            await self._lifecycle.complete_termination()

    # ------------------------------------------------------------------
    # Lifecycle methods that subclasses should override
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Initialize the backend. Override in subclasses."""
        await self._lifecycle.initialize()
        await self._lifecycle.mark_ready()

    async def launch(self, config) -> None:
        """Launch a new debuggee process. Override in subclasses."""
        error_msg = f"{self.__class__.__name__} does not support launch"
        raise NotImplementedError(error_msg)

    async def attach(self, config) -> None:
        """Attach to an existing debuggee. Override in subclasses."""
        error_msg = f"{self.__class__.__name__} does not support attach"
        raise NotImplementedError(error_msg)
