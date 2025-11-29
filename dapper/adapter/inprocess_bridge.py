"""In-process debugger bridge for PyDebugger.

This module provides the InProcessBridge class that encapsulates all
interaction with the InProcessDebugger, including event forwarding and
command dispatch. This separation keeps the main PyDebugger class focused
on the core debugging protocol while delegating in-process specifics here.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from typing import Any
from typing import Callable

if TYPE_CHECKING:
    from dapper.core.inprocess_debugger import InProcessDebugger
    from dapper.protocol.requests import ContinueResponseBody
    from dapper.protocol.requests import EvaluateResponseBody
    from dapper.protocol.requests import FunctionBreakpoint
    from dapper.protocol.requests import SetVariableResponseBody
    from dapper.protocol.requests import StackTraceResponseBody
    from dapper.protocol.structures import Breakpoint
    from dapper.protocol.structures import SourceBreakpoint

logger = logging.getLogger(__name__)


class InProcessBridge:
    """Bridge between PyDebugger and InProcessDebugger.

    Encapsulates:
    - Event listener registration and forwarding
    - Command dispatch to the in-process debugger
    - Error isolation for callbacks
    """

    def __init__(
        self,
        inproc: InProcessDebugger,
        on_stopped: Callable[[dict[str, Any]], None],
        on_thread: Callable[[dict[str, Any]], None],
        on_exited: Callable[[dict[str, Any]], None],
        on_output: Callable[[str, str], Any],
    ) -> None:
        """Initialize the bridge with an InProcessDebugger and event handlers.

        Args:
            inproc: The InProcessDebugger instance to wrap
            on_stopped: Handler for stopped events
            on_thread: Handler for thread events
            on_exited: Handler for exited events
            on_output: Handler for output events (async or sync)
        """
        self._inproc = inproc
        self._on_stopped = on_stopped
        self._on_thread = on_thread
        self._on_exited = on_exited
        self._on_output = on_output

        # Register event listeners
        self._inproc.on_stopped.add_listener(self._handle_stopped)
        self._inproc.on_thread.add_listener(self._handle_thread)
        self._inproc.on_exited.add_listener(self._handle_exited)
        self._inproc.on_output.add_listener(self._handle_output)

    @property
    def debugger(self) -> InProcessDebugger:
        """Access the underlying InProcessDebugger."""
        return self._inproc

    # ------------------------------------------------------------------
    # Event handlers (with error isolation)
    # ------------------------------------------------------------------
    def _handle_stopped(self, data: dict[str, Any]) -> None:
        """Forward stopped events with isolation."""
        try:
            self._on_stopped(data)
        except Exception:
            logger.exception("error in on_stopped callback")

    def _handle_thread(self, data: dict[str, Any]) -> None:
        """Forward thread events with isolation."""
        try:
            self._on_thread(data)
        except Exception:
            logger.exception("error in on_thread callback")

    def _handle_exited(self, data: dict[str, Any]) -> None:
        """Forward exited events with isolation."""
        try:
            self._on_exited(data)
        except Exception:
            logger.exception("error in on_exited callback")

    def _handle_output(self, category: str, output: str) -> None:
        """Forward output events with isolation."""
        try:
            self._on_output(category, output)
        except Exception:
            logger.exception("error in on_output callback")

    # ------------------------------------------------------------------
    # Breakpoint operations
    # ------------------------------------------------------------------
    def set_breakpoints(
        self, path: str, breakpoints: list[SourceBreakpoint]
    ) -> list[Breakpoint]:
        """Set line breakpoints for a file."""
        return self._inproc.set_breakpoints(path, breakpoints)

    def set_function_breakpoints(
        self, breakpoints: list[FunctionBreakpoint]
    ) -> list[FunctionBreakpoint]:
        """Set function breakpoints."""
        return list(self._inproc.set_function_breakpoints(breakpoints))

    def set_exception_breakpoints(self, filters: list[str]) -> list[Breakpoint]:
        """Set exception breakpoints."""
        return list(self._inproc.set_exception_breakpoints(filters))

    # ------------------------------------------------------------------
    # Execution control
    # ------------------------------------------------------------------
    def continue_(self, thread_id: int) -> ContinueResponseBody:
        """Continue execution."""
        return self._inproc.continue_(thread_id)

    def next_(self, thread_id: int) -> None:
        """Step over."""
        self._inproc.next_(thread_id)

    def step_in(self, thread_id: int) -> None:
        """Step into."""
        self._inproc.step_in(thread_id)

    def step_out(self, thread_id: int) -> None:
        """Step out."""
        self._inproc.step_out(thread_id)

    # ------------------------------------------------------------------
    # Inspection operations
    # ------------------------------------------------------------------
    def stack_trace(
        self, thread_id: int, start_frame: int = 0, levels: int = 0
    ) -> StackTraceResponseBody:
        """Get stack trace for a thread."""
        return self._inproc.stack_trace(thread_id, start_frame, levels)

    def variables(
        self,
        variables_reference: int,
        *,
        filter_type: str | None = None,
        start: int | None = None,
        count: int | None = None,
    ) -> list[Any]:
        """Get variables for a reference."""
        result = self._inproc.variables(
            variables_reference,
            _filter=filter_type,
            _start=start,
            _count=count,
        )
        # Handle both list and dict responses
        if isinstance(result, list):
            return result
        return result.get("variables", [])

    def set_variable(
        self, var_ref: int, name: str, value: str
    ) -> SetVariableResponseBody:
        """Set a variable value."""
        return self._inproc.set_variable(var_ref, name, value)

    def evaluate(
        self, expression: str, frame_id: int | None = None, context: str | None = None
    ) -> EvaluateResponseBody:
        """Evaluate an expression."""
        return self._inproc.evaluate(expression, frame_id, context)

    # ------------------------------------------------------------------
    # Command dispatch (for _send_command_to_debuggee compatibility)
    # ------------------------------------------------------------------
    def dispatch_command(
        self, command: dict[str, Any], expect_response: bool = False
    ) -> dict[str, Any] | None:
        """Dispatch a command dict to the in-process debugger.

        This provides compatibility with the command dict format used by
        _send_command_to_debuggee for IPC communication.

        Args:
            command: Command dict with 'command' and 'arguments' keys
            expect_response: Whether to wrap result in a response dict

        Returns:
            Response dict with 'body' key if expect_response, else None
        """
        try:
            cmd_key = command.get("command", "")
            args = command.get("arguments", {})

            def _tid() -> int:
                return int(args.get("threadId", 1))

            dispatch: dict[str, Callable[[], Any]] = {
                "continue": lambda: self.continue_(_tid()),
                "next": lambda: self.next_(_tid()),
                "stepIn": lambda: self.step_in(_tid()),
                "stepOut": lambda: self.step_out(_tid()),
                "stackTrace": lambda: self.stack_trace(
                    _tid(),
                    args.get("startFrame", 0),
                    args.get("levels", 0),
                ),
                "variables": lambda: self.variables(
                    args.get("variablesReference"),
                    filter_type=args.get("filter"),
                    start=args.get("start"),
                    count=args.get("count"),
                ),
                "setVariable": lambda: self.set_variable(
                    args.get("variablesReference"),
                    args.get("name"),
                    args.get("value"),
                ),
                "evaluate": lambda: self.evaluate(
                    args.get("expression", ""),
                    args.get("frameId", 0),
                    args.get("context", "hover"),
                ),
                "exceptionInfo": lambda: {
                    "exceptionId": "Unknown",
                    "description": "Exception information not available",
                    "breakMode": "unhandled",
                    "details": {
                        "message": "Exception information not available",
                        "typeName": "Unknown",
                        "fullTypeName": "Unknown",
                        "source": "Unknown",
                        "stackTrace": "Exception information not available",
                    },
                },
                "configurationDone": lambda: None,
                "terminate": lambda: None,
                "pause": lambda: None,
            }

            handler = dispatch.get(cmd_key, lambda: None)
            body = handler()

        except Exception:
            logger.exception("in-process command handling failed")
            if expect_response:
                return {"body": {}}
            return None
        else:
            if expect_response:
                return {"body": body or {}}
            return None

    def register_data_watches(
        self, watch_names: list[str], watch_meta: list[tuple[str, dict[str, Any]]]
    ) -> None:
        """Register data watches with the underlying debugger if supported."""
        try:
            dbg = getattr(self._inproc, "debugger", None)
            register = getattr(dbg, "register_data_watches", None)
            if callable(register):
                register(watch_names, watch_meta)
        except Exception:
            logger.debug("Failed bridging data watches to BDB", exc_info=True)
