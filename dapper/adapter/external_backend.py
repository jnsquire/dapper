"""External process backend for PyDebugger.

This module provides the ExternalProcessBackend class that handles communication
with a debuggee running in a separate subprocess via IPC.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING
from typing import Any
from typing import Final
from typing import TypedDict
from typing import cast

from dapper.adapter.base_backend import BaseBackend
from dapper.protocol.requests import GotoTargetsResponseBody

if TYPE_CHECKING:
    from collections.abc import Callable
    import subprocess
    import threading

    from dapper.config import DapperConfig
    from dapper.ipc.ipc_manager import IPCManager
    from dapper.protocol.requests import CompletionsResponseBody
    from dapper.protocol.requests import ContinueResponseBody
    from dapper.protocol.requests import EvaluateResponseBody
    from dapper.protocol.requests import ExceptionInfoResponseBody
    from dapper.protocol.requests import GotoTarget
    from dapper.protocol.requests import HotReloadResponseBody
    from dapper.protocol.requests import SetBreakpointsResponseBody
    from dapper.protocol.requests import SetExceptionBreakpointsResponseBody
    from dapper.protocol.requests import SetExpressionResponseBody
    from dapper.protocol.requests import SetFunctionBreakpointsResponseBody
    from dapper.protocol.requests import SetVariableResponseBody
    from dapper.protocol.requests import StackTraceResponseBody
    from dapper.protocol.requests import VariablesResponseBody

logger = logging.getLogger(__name__)


def _command_response_timeout_seconds() -> float | None:
    raw = str(os.getenv("DAPPER_COMMAND_RESPONSE_TIMEOUT_SECONDS", "0")).strip()
    try:
        value = float(raw)
    except ValueError:
        return None
    if value <= 0:
        return None
    return value


class _SetExpressionDispatchArgs(TypedDict):
    expression: str
    value: str
    frame_id: int | None


class _HotReloadDispatchArgs(TypedDict, total=False):
    """Arguments for the 'hot_reload' dispatch entry."""

    path: str
    options: dict[str, Any]


class _EmptyBody(TypedDict, total=False):
    """TypedDict for DAP commands whose response body carries no fields."""


class _PauseResponseBody(TypedDict):
    """Internal bookkeeping body returned by _dispatch_pause."""

    sent: bool


# Singletons — avoids allocating a new dict on every fire-and-forget dispatch.
_EMPTY_BODY: Final[_EmptyBody] = _EmptyBody()
_PAUSE_SENT: Final[_PauseResponseBody] = _PauseResponseBody(sent=True)


class ExternalProcessBackend(BaseBackend):
    """Backend for debugging via external subprocess + IPC.

    This class encapsulates all the logic for sending commands to and
    receiving responses from a debuggee running in a separate process.
    """

    def __init__(
        self,
        ipc: IPCManager,
        loop: asyncio.AbstractEventLoop,
        get_process_state: Callable[[], tuple[subprocess.Popen[Any] | None, bool]],
        pending_commands: dict[int, asyncio.Future[dict[str, Any]]],
        lock: threading.RLock,
        get_next_command_id: Callable[[], int],
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

        # Pre-built dispatch map to avoid reallocating the dispatch table
        # on every _execute_command invocation. Handlers accept a single
        # `args` dict and return an awaitable that yields a dict response.
        self._dispatch_map = {
            "set_breakpoints": self._dispatch_set_breakpoints,
            "set_function_breakpoints": self._dispatch_set_function_breakpoints,
            "set_exception_breakpoints": self._dispatch_set_exception_breakpoints,
            "continue": self._dispatch_continue,
            "next": self._dispatch_next,
            "step_in": self._dispatch_step_in,
            "step_out": self._dispatch_step_out,
            "pause": self._dispatch_pause,
            "goto_targets": self._dispatch_goto_targets,
            "goto": self._dispatch_goto,
            "get_stack_trace": self._dispatch_stack_trace,
            "get_variables": self._dispatch_variables,
            "set_variable": self._dispatch_set_variable,
            "set_expression": self._dispatch_set_expression,
            "evaluate": self._dispatch_evaluate,
            "completions": self._dispatch_completions,
            "exception_info": self._dispatch_exception_info,
            "configuration_done": self._dispatch_configuration_done,
            "terminate": self._dispatch_terminate,
            "hot_reload": self._dispatch_hot_reload,
        }

    def _cleanup_ipc(self) -> None:
        """Cleanup IPC connection."""
        try:
            self._ipc.cleanup()
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
        self,
        response: dict[str, Any] | None,
        default: dict[str, Any],
    ) -> dict[str, Any]:
        """Extract the body from a response, returning default if unavailable."""
        if not response:
            return default
        return response.get("body", default)

    def _build_dispatch_table(
        self,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        """Back-compat builder delegating to the prebuilt dispatch map.

        Older callers may still rely on ``_build_dispatch_table`` returning
        zero-argument callables. The authoritative command mapping lives in
        ``self._dispatch_map``.
        """

        def _wrap(handler):
            return lambda: handler(args)

        return {name: _wrap(handler) for name, handler in self._dispatch_map.items()}

    async def _dispatch_set_breakpoints(self, args: dict[str, Any]) -> SetBreakpointsResponseBody:
        cmd = {
            "command": "setBreakpoints",
            "arguments": {
                "source": {"path": args["path"]},
                "breakpoints": [dict(bp) for bp in args["breakpoints"]],
            },
        }
        await self._send_command(cmd)
        return cast(
            "SetBreakpointsResponseBody",
            {
                "breakpoints": [
                    {"verified": True, "line": bp.get("line")} for bp in args["breakpoints"]
                ]
            },
        )

    async def _dispatch_set_function_breakpoints(
        self, args: dict[str, Any]
    ) -> SetFunctionBreakpointsResponseBody:
        cmd = {
            "command": "setFunctionBreakpoints",
            "arguments": {"breakpoints": [dict(bp) for bp in args["breakpoints"]]},
        }
        await self._send_command(cmd)
        return cast(
            "SetFunctionBreakpointsResponseBody",
            {"breakpoints": [{"verified": bp.get("verified", True)} for bp in args["breakpoints"]]},
        )

    async def _dispatch_set_exception_breakpoints(
        self, args: dict[str, Any]
    ) -> SetExceptionBreakpointsResponseBody:
        ebp_args: dict[str, Any] = {"filters": args["filters"]}
        if args.get("filter_options") is not None:
            ebp_args["filterOptions"] = args["filter_options"]
        if args.get("exception_options") is not None:
            ebp_args["exceptionOptions"] = args["exception_options"]
        cmd = {"command": "setExceptionBreakpoints", "arguments": ebp_args}
        await self._send_command(cmd)
        return cast(
            "SetExceptionBreakpointsResponseBody",
            {"breakpoints": [{"verified": True} for _ in args["filters"]]},
        )

    async def _dispatch_continue(self, args: dict[str, Any]) -> ContinueResponseBody:
        cmd = {"command": "continue", "arguments": {"threadId": args["thread_id"]}}
        response = await self._send_command(cmd, expect_response=True)
        body = self._extract_body(response, {})
        if isinstance(body, dict) and body:
            return self._normalize_continue_payload(body)
        return self._normalize_continue_payload(response)

    async def _dispatch_next(self, args: dict[str, Any]) -> _EmptyBody:
        cmd_args: dict[str, Any] = {"threadId": args["thread_id"]}
        if args.get("granularity") and args["granularity"] != "line":
            cmd_args["granularity"] = args["granularity"]
        cmd = {"command": "next", "arguments": cmd_args}
        await self._send_command(cmd)
        return _EMPTY_BODY

    async def _dispatch_step_in(self, args: dict[str, Any]) -> _EmptyBody:
        cmd_args: dict[str, Any] = {"threadId": args["thread_id"]}
        if args.get("granularity") and args["granularity"] != "line":
            cmd_args["granularity"] = args["granularity"]
        cmd = {"command": "stepIn", "arguments": cmd_args}
        await self._send_command(cmd)
        return _EMPTY_BODY

    async def _dispatch_step_out(self, args: dict[str, Any]) -> _EmptyBody:
        cmd_args: dict[str, Any] = {"threadId": args["thread_id"]}
        if args.get("granularity") and args["granularity"] != "line":
            cmd_args["granularity"] = args["granularity"]
        cmd = {"command": "stepOut", "arguments": cmd_args}
        await self._send_command(cmd)
        return _EMPTY_BODY

    async def _dispatch_pause(self, args: dict[str, Any]) -> _PauseResponseBody:
        cmd = {"command": "pause", "arguments": {"threadId": args["thread_id"]}}
        await self._send_command(cmd)
        return _PAUSE_SENT

    async def _dispatch_goto_targets(self, args: dict[str, Any]) -> GotoTargetsResponseBody:
        frame_id = int(args["frame_id"])
        line = int(args["line"])
        cmd = {
            "command": "gotoTargets",
            "arguments": {
                "frameId": frame_id,
                "line": line,
            },
        }
        response = await self._send_command(cmd, expect_response=True)
        if not response:
            return GotoTargetsResponseBody(targets=[])
        body = response.get("body", {})
        if not isinstance(body, dict):
            return GotoTargetsResponseBody(targets=[])
        typed_body = cast("GotoTargetsResponseBody", body)
        targets = typed_body.get("targets", [])
        normalized_targets: list[GotoTarget] = targets if isinstance(targets, list) else []
        return GotoTargetsResponseBody(targets=normalized_targets)

    async def _dispatch_goto(self, args: dict[str, Any]) -> _EmptyBody:
        cmd = {
            "command": "goto",
            "arguments": {
                "threadId": args["thread_id"],
                "targetId": args["target_id"],
            },
        }
        response = await self._send_command(cmd, expect_response=True)
        if isinstance(response, dict) and response.get("success") is False:
            msg = str(response.get("message") or "goto failed")
            raise ValueError(msg)
        return _EMPTY_BODY

    async def _dispatch_stack_trace(self, args: dict[str, Any]) -> StackTraceResponseBody:
        cmd = {
            "command": "stackTrace",
            "arguments": {
                "threadId": args["thread_id"],
                "startFrame": args.get("start_frame", 0),
                "levels": args.get("levels", 0),
            },
        }
        response = await self._send_command(cmd, expect_response=True)
        return cast(
            "StackTraceResponseBody",
            self._extract_body(response, {"stackFrames": [], "totalFrames": 0}),
        )

    async def _dispatch_variables(self, args: dict[str, Any]) -> VariablesResponseBody:
        cmd: dict[str, Any] = {
            "command": "variables",
            "arguments": {"variablesReference": args["variables_reference"]},
        }
        ft = args.get("filter_type", "")
        if ft:
            cmd["arguments"]["filter"] = ft
        s = args.get("start", 0)
        if s > 0:
            cmd["arguments"]["start"] = s
        c = args.get("count", 0)
        if c > 0:
            cmd["arguments"]["count"] = c
        response = await self._send_command(cmd, expect_response=True)
        if not response:
            return VariablesResponseBody(variables=[])
        body = response.get("body", {})
        return cast("VariablesResponseBody", {"variables": body.get("variables", [])})

    async def _dispatch_set_variable(self, args: dict[str, Any]) -> SetVariableResponseBody:
        cmd = {
            "command": "setVariable",
            "arguments": {
                "variablesReference": args["var_ref"],
                "name": args["name"],
                "value": args["value"],
            },
        }
        response = await self._send_command(cmd, expect_response=True)
        return cast(
            "SetVariableResponseBody",
            self._extract_body(
                response,
                {"value": args["value"], "type": "string", "variablesReference": 0},
            ),
        )

    async def _dispatch_set_expression(
        self,
        args: _SetExpressionDispatchArgs,
    ) -> SetExpressionResponseBody:
        cmd = {
            "command": "setExpression",
            "arguments": {
                "expression": args["expression"],
                "value": args["value"],
                "frameId": args.get("frame_id"),
            },
        }
        response = await self._send_command(cmd, expect_response=True)
        return cast(
            "SetExpressionResponseBody",
            self._extract_body(
                response,
                {"value": args["value"], "type": "string", "variablesReference": 0},
            ),
        )

    async def _dispatch_evaluate(self, args: dict[str, Any]) -> EvaluateResponseBody:
        cmd = {
            "command": "evaluate",
            "arguments": {
                "expression": args["expression"],
                "frameId": args.get("frame_id"),
                "context": args.get("context", "hover"),
            },
        }
        response = await self._send_command(cmd, expect_response=True)
        default: dict[str, Any] = {
            "result": f"<evaluation of '{args['expression']}' not available>",
            "type": "string",
            "variablesReference": 0,
        }
        return cast("EvaluateResponseBody", self._extract_body(response, default))

    async def _dispatch_completions(self, args: dict[str, Any]) -> CompletionsResponseBody:
        cmd = {
            "command": "completions",
            "arguments": {
                "text": args["text"],
                "column": args["column"],
                "frameId": args.get("frame_id"),
                "line": args.get("line", 1),
            },
        }
        response = await self._send_command(cmd, expect_response=True)
        return cast("CompletionsResponseBody", self._extract_body(response, {"targets": []}))

    async def _dispatch_exception_info(self, args: dict[str, Any]) -> ExceptionInfoResponseBody:
        cmd = {
            "command": "exceptionInfo",
            "arguments": {"threadId": args["thread_id"]},
        }
        response = await self._send_command(cmd, expect_response=True)
        if response and "body" in response:
            return cast("ExceptionInfoResponseBody", response["body"])
        return ExceptionInfoResponseBody()

    async def _dispatch_configuration_done(self, *_args: Any, **_kwargs: Any) -> _EmptyBody:
        await self._send_command({"command": "configurationDone"})
        return _EMPTY_BODY

    async def _dispatch_terminate(self, *_args: Any, **_kwargs: Any) -> _EmptyBody:
        await self._send_command({"command": "terminate"})
        return _EMPTY_BODY

    async def _dispatch_hot_reload(
        self, args: _HotReloadDispatchArgs
    ) -> HotReloadResponseBody:
        """Send a 'hotReload' command to the debuggee and await its response.

        The debuggee's ``@command_handler("hotReload")`` performs the reload
        and returns a ``{"success": True, "body": {...}}`` response.  The
        ``CommandDispatcher`` on the debuggee side automatically tags the
        response with the command ``id`` so the adapter can match it to the
        pending :class:`~asyncio.Future`.

        Raises:
            RuntimeError: If the debuggee signals ``success=False``.
        """
        cmd: dict[str, Any] = {
            "command": "hotReload",
            "arguments": {
                "path": args.get("path", ""),
                "options": args.get("options") or {},
            },
        }
        response = await self._send_command(cmd, expect_response=True)
        if response is not None and response.get("success") is False:
            msg = str(response.get("message") or "hotReload failed in debuggee process")
            raise RuntimeError(msg)

        _default: dict[str, Any] = {
            "reloadedModule": "<unknown>",
            "reboundFrames": 0,
            "updatedFrameCodes": 0,
            "patchedInstances": 0,
            "warnings": [],
        }
        body = self._extract_body(response, _default)
        return cast("HotReloadResponseBody", body)

    async def _execute_command(
        self,
        command: str,
        args: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute a command on the external process with availability check."""
        if not self.is_available():
            raise RuntimeError("External process not available")
        return await super()._execute_command(command, args, **kwargs)

    async def _send_command(
        self,
        command: dict[str, Any],
        expect_response: bool = False,
    ) -> dict[str, Any] | None:
        """Send a command to the debuggee process."""
        result: dict[str, Any] | None = None

        if not self.is_available():
            return result

        response_future: asyncio.Future[dict[str, Any]] | None = None
        command_id: int = 0  # Only used when expect_response is True

        if expect_response:
            command_id = self._get_next_command_id()
            command["id"] = command_id
            response_loop = asyncio.get_running_loop()
            response_future = response_loop.create_future()
            with self._lock:
                self._pending_commands[command_id] = response_future

        try:
            await self._ipc.send_message(command)
        except Exception:
            logger.exception("Error sending command to debuggee")
            if expect_response:
                self._pending_commands.pop(command_id, None)
        else:
            if response_future is not None:
                timeout_seconds = _command_response_timeout_seconds()
                try:
                    if timeout_seconds is None:
                        result = await response_future
                    else:
                        result = await asyncio.wait_for(response_future, timeout=timeout_seconds)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    self._pending_commands.pop(command_id, None)

        return result

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
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
