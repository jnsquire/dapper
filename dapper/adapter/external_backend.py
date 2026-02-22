"""External process backend for PyDebugger.

This module provides the ExternalProcessBackend class that handles communication
with a debuggee running in a separate subprocess via IPC.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING
from typing import Any
from typing import TypedDict
from typing import cast

from dapper.adapter.base_backend import BaseBackend

if TYPE_CHECKING:
    from collections.abc import Callable
    import subprocess
    import threading

    from dapper.config import DapperConfig
    from dapper.ipc.ipc_manager import IPCManager
    from dapper.protocol.requests import GotoTarget
    from dapper.protocol.requests import GotoTargetsResponseBody
    from dapper.protocol.requests import SetExpressionResponseBody

logger = logging.getLogger(__name__)


class _SetExpressionDispatchArgs(TypedDict):
    expression: str
    value: str
    frame_id: int | None


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

    async def _dispatch_set_breakpoints(self, args: dict[str, Any]) -> dict[str, Any]:
        cmd = {
            "command": "setBreakpoints",
            "arguments": {
                "source": {"path": args["path"]},
                "breakpoints": [dict(bp) for bp in args["breakpoints"]],
            },
        }
        await self._send_command(cmd)
        return {
            "breakpoints": [
                {"verified": True, "line": bp.get("line")} for bp in args["breakpoints"]
            ],
        }

    async def _dispatch_set_function_breakpoints(self, args: dict[str, Any]) -> dict[str, Any]:
        cmd = {
            "command": "setFunctionBreakpoints",
            "arguments": {"breakpoints": [dict(bp) for bp in args["breakpoints"]]},
        }
        await self._send_command(cmd)
        return {
            "breakpoints": [{"verified": bp.get("verified", True)} for bp in args["breakpoints"]],
        }

    async def _dispatch_set_exception_breakpoints(self, args: dict[str, Any]) -> dict[str, Any]:
        ebp_args: dict[str, Any] = {"filters": args["filters"]}
        if args.get("filter_options") is not None:
            ebp_args["filterOptions"] = args["filter_options"]
        if args.get("exception_options") is not None:
            ebp_args["exceptionOptions"] = args["exception_options"]
        cmd = {"command": "setExceptionBreakpoints", "arguments": ebp_args}
        await self._send_command(cmd)
        return {"breakpoints": [{"verified": True} for _ in args["filters"]]}

    async def _dispatch_continue(self, args: dict[str, Any]) -> dict[str, Any]:
        cmd = {"command": "continue", "arguments": {"threadId": args["thread_id"]}}
        response = await self._send_command(cmd, expect_response=True)
        body = self._extract_body(response, {})
        if isinstance(body, dict) and body:
            return dict(self._normalize_continue_payload(body))
        return dict(self._normalize_continue_payload(response))

    async def _dispatch_next(self, args: dict[str, Any]) -> dict[str, Any]:
        cmd_args: dict[str, Any] = {"threadId": args["thread_id"]}
        if args.get("granularity") and args["granularity"] != "line":
            cmd_args["granularity"] = args["granularity"]
        cmd = {"command": "next", "arguments": cmd_args}
        await self._send_command(cmd)
        return {}

    async def _dispatch_step_in(self, args: dict[str, Any]) -> dict[str, Any]:
        cmd_args: dict[str, Any] = {"threadId": args["thread_id"]}
        if args.get("granularity") and args["granularity"] != "line":
            cmd_args["granularity"] = args["granularity"]
        cmd = {"command": "stepIn", "arguments": cmd_args}
        await self._send_command(cmd)
        return {}

    async def _dispatch_step_out(self, args: dict[str, Any]) -> dict[str, Any]:
        cmd_args: dict[str, Any] = {"threadId": args["thread_id"]}
        if args.get("granularity") and args["granularity"] != "line":
            cmd_args["granularity"] = args["granularity"]
        cmd = {"command": "stepOut", "arguments": cmd_args}
        await self._send_command(cmd)
        return {}

    async def _dispatch_pause(self, args: dict[str, Any]) -> dict[str, Any]:
        cmd = {"command": "pause", "arguments": {"threadId": args["thread_id"]}}
        await self._send_command(cmd)
        return {"sent": True}

    async def _dispatch_goto_targets(self, args: dict[str, Any]) -> dict[str, Any]:
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
            return {"targets": []}
        body = response.get("body", {})
        if not isinstance(body, dict):
            return {"targets": []}
        typed_body = cast("GotoTargetsResponseBody", body)
        targets = typed_body.get("targets", [])
        normalized_targets: list[GotoTarget] = targets if isinstance(targets, list) else []
        return {"targets": normalized_targets}

    async def _dispatch_goto(self, args: dict[str, Any]) -> dict[str, Any]:
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
        return {}

    async def _dispatch_stack_trace(self, args: dict[str, Any]) -> dict[str, Any]:
        cmd = {
            "command": "stackTrace",
            "arguments": {
                "threadId": args["thread_id"],
                "startFrame": args.get("start_frame", 0),
                "levels": args.get("levels", 0),
            },
        }
        response = await self._send_command(cmd, expect_response=True)
        return self._extract_body(response, {"stackFrames": [], "totalFrames": 0})

    async def _dispatch_variables(self, args: dict[str, Any]) -> dict[str, Any]:
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
            return {"variables": []}
        body = response.get("body", {})
        return {"variables": body.get("variables", [])}

    async def _dispatch_set_variable(self, args: dict[str, Any]) -> dict[str, Any]:
        cmd = {
            "command": "setVariable",
            "arguments": {
                "variablesReference": args["var_ref"],
                "name": args["name"],
                "value": args["value"],
            },
        }
        response = await self._send_command(cmd, expect_response=True)
        return self._extract_body(
            response,
            {"value": args["value"], "type": "string", "variablesReference": 0},
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

    async def _dispatch_evaluate(self, args: dict[str, Any]) -> dict[str, Any]:
        cmd = {
            "command": "evaluate",
            "arguments": {
                "expression": args["expression"],
                "frameId": args.get("frame_id"),
                "context": args.get("context", "hover"),
            },
        }
        response = await self._send_command(cmd, expect_response=True)
        default = {
            "result": f"<evaluation of '{args['expression']}' not available>",
            "type": "string",
            "variablesReference": 0,
        }
        return self._extract_body(response, default)

    async def _dispatch_completions(self, args: dict[str, Any]) -> dict[str, Any]:
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
        return self._extract_body(response, {"targets": []})

    async def _dispatch_exception_info(self, args: dict[str, Any]) -> dict[str, Any]:
        cmd = {
            "command": "exceptionInfo",
            "arguments": {"threadId": args["thread_id"]},
        }
        response = await self._send_command(cmd, expect_response=True)
        if response and "body" in response:
            return response["body"]
        return {}

    async def _dispatch_configuration_done(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        await self._send_command({"command": "configurationDone"})
        return {}

    async def _dispatch_terminate(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        await self._send_command({"command": "terminate"})
        return {}

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
        if not self.is_available():
            return None

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
            return None

        if response_future is None:
            return None

        try:
            return await asyncio.wait_for(response_future, timeout=5.0)
        except asyncio.TimeoutError:
            self._pending_commands.pop(command_id, None)
            return None

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
