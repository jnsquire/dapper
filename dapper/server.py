"""
Implementation of the Debug Adapter Protocol Server
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import TYPE_CHECKING
from typing import Any
from typing import Awaitable
from typing import Callable
from typing import Dict
from typing import cast

from dapper.debugger import PyDebugger
from dapper.protocol import ProtocolHandler

if TYPE_CHECKING:
    from dapper.connection import ConnectionBase
    from dapper.protocol_types import ExceptionInfoRequest
    from dapper.protocol_types import Request


class RequestHandler:
    """
    Handles incoming requests from the DAP client and routes them to the
    appropriate handler methods.
    """

    def __init__(self, server: DebugAdapterServer):
        self.server = server

    async def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """
        Handle a DAP request and return a response.
        """
        command = request["command"]
        handler_method = getattr(self, f"_handle_{command}", self._handle_unknown)
        return await handler_method(request)

    async def _handle_unknown(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle an unknown request command."""
        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": False,
            "command": request["command"],
            "message": f"Unsupported command: {request['command']}",
        }

    async def _handle_initialize(self, request: dict[str, Any]) -> None:
        """Handle initialize request."""
        # Directly send the response for initialize
        response = {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "initialize",
            "body": {
                "supportsConfigurationDoneRequest": True,
                "supportsFunctionBreakpoints": True,
                "supportsConditionalBreakpoints": True,
                "supportsHitConditionalBreakpoints": True,
                "supportsEvaluateForHovers": True,
                "exceptionBreakpointFilters": [
                    {
                        "filter": "raised",
                        "label": "Raised Exceptions",
                        "default": False,
                    },
                    {
                        "filter": "uncaught",
                        "label": "Uncaught Exceptions",
                        "default": True,
                    },
                ],
                "supportsStepInTargetsRequest": True,
                "supportsGotoTargetsRequest": True,
                "supportsCompletionsRequest": True,
                "supportsModulesRequest": True,
                "supportsLoadedSourcesRequest": True,
                "supportsRestartRequest": True,
                "supportsExceptionOptions": True,
                "supportsValueFormattingOptions": True,
                "supportsExceptionInfoRequest": True,
                "supportTerminateDebuggee": True,
                "supportsDelayedStackTraceLoading": True,
                "supportsLogPoints": True,
                "supportsSetVariable": True,
                "supportsSetExpression": True,
                "supportsDisassembleRequest": True,
                "supportsSteppingGranularity": True,
                "supportsInstructionBreakpoints": True,
            },
        }
        await self.server.send_message(response)
        # Send the initialized event
        await self.server.send_event("initialized")

    async def _handle_launch(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle launch request."""
        args = request.get("arguments", {})
        program = args.get("program")
        if not program:
            return {
                "type": "response",
                "request_seq": request["seq"],
                "success": False,
                "command": "launch",
                "message": "Missing required argument 'program'.",
            }

        program_args = args.get("args", [])
        stop_on_entry = args.get("stopOnEntry", False)
        no_debug = args.get("noDebug", False)
        in_process = args.get("inProcess", False)
        use_ipc = args.get("useIpc", False)
        # Optional IPC transport details (used only when useIpc is True)
        ipc_transport = args.get("ipcTransport")
        ipc_pipe_name = args.get("ipcPipeName")

        # Only include the in_process/use_ipc kwargs if explicitly enabled to
        # keep backward-compat tests (which assert four positional args) happy.
        if in_process or use_ipc:
            launch_kwargs: dict[str, Any] = {}
            if in_process:
                launch_kwargs["in_process"] = True
            if use_ipc:
                launch_kwargs["use_ipc"] = True
                if ipc_transport is not None:
                    launch_kwargs["ipc_transport"] = ipc_transport
                if ipc_pipe_name is not None:
                    launch_kwargs["ipc_pipe_name"] = ipc_pipe_name

            await self.server.debugger.launch(
                program,
                program_args,
                stop_on_entry,
                no_debug,
                **launch_kwargs,
            )
        else:
            await self.server.debugger.launch(
                program,
                program_args,
                stop_on_entry,
                no_debug,
            )

        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "launch",
        }

    async def _handle_attach(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle attach request.

        MVP attach connects to an existing debuggee IPC endpoint.
        The client should specify useIpc and the endpoint coordinates
        (transport + host/port or path or pipe name).
        """
        args = request.get("arguments", {})

        use_ipc: bool = bool(args.get("useIpc", False))
        ipc_transport = args.get("ipcTransport")
        ipc_host = args.get("ipcHost")
        ipc_port = args.get("ipcPort")
        ipc_path = args.get("ipcPath")
        ipc_pipe_name = args.get("ipcPipeName")

        try:
            await self.server.debugger.attach(
                use_ipc=use_ipc,
                ipc_transport=ipc_transport,
                ipc_host=ipc_host,
                ipc_port=ipc_port,
                ipc_path=ipc_path,
                ipc_pipe_name=ipc_pipe_name,
            )
        except Exception as e:  # pragma: no cover - exercised by error tests
            logging.getLogger(__name__).exception("attach failed")
            return {
                "type": "response",
                "request_seq": request["seq"],
                "success": False,
                "command": "attach",
                "message": f"Attach failed: {e!s}",
            }

        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "attach",
        }

    async def _handle_set_breakpoints(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle setBreakpoints request."""
        args = request.get("arguments", {})
        source = args.get("source", {})
        path = source.get("path")
        breakpoints = args.get("breakpoints", [])

        verified_breakpoints = await self.server.debugger.set_breakpoints(path, breakpoints)

        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "setBreakpoints",
            "body": {"breakpoints": verified_breakpoints},
        }

    async def _handle_continue(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle continue request."""
        thread_id = request["arguments"]["threadId"]
        continued = await self.server.debugger.continue_execution(thread_id)
        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "continue",
            "body": {"allThreadsContinued": continued},
        }

    async def _handle_next(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle next request."""
        thread_id = request["arguments"]["threadId"]
        # Map DAP 'next' to debugger.step_over when available for tests,
        # otherwise fall back to debugger.next.
        step_over = getattr(self.server.debugger, "step_over", None)
        if callable(step_over):
            await cast("Callable[[int], Awaitable[Any]]", step_over)(thread_id)
        else:
            await self.server.debugger.next(thread_id)
        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "next",
        }

    async def _handle_step_in(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle stepIn request."""
        args = request["arguments"]
        thread_id = args["threadId"]
        target_id = args.get("targetId")
        # Pass targetId if provided for compatibility with tests
        step_in = self.server.debugger.step_in
        if target_id is not None:
            await cast("Callable[..., Awaitable[Any]]", step_in)(thread_id, target_id)
        else:
            await cast("Callable[..., Awaitable[Any]]", step_in)(thread_id)
        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "stepIn",
        }

    async def _handle_step_out(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle stepOut request."""
        thread_id = request["arguments"]["threadId"]
        await self.server.debugger.step_out(thread_id)
        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "stepOut",
        }

    async def _handle_disconnect(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle disconnect request."""
        await self.server.debugger.shutdown()
        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "disconnect",
        }

    async def _handle_terminate(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle terminate request - force terminate the debugged program."""
        try:
            await self.server.debugger.terminate()
            return {
                "type": "response",
                "request_seq": request["seq"],
                "success": True,
                "command": "terminate",
            }
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.exception("Error handling terminate request")
            return {
                "type": "response",
                "request_seq": request["seq"],
                "success": False,
                "command": "terminate",
                "message": f"Terminate failed: {e!s}",
            }

    async def _handle_restart(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle restart request.

        Semantics: terminate current debuggee and emit a terminated event with
        restart=true so the client restarts the session. Resources are cleaned
        up via the debugger's shutdown.
        """
        try:
            # Delegate to debugger which will send the terminated(restart=true)
            await self.server.debugger.restart()
            return {
                "type": "response",
                "request_seq": request["seq"],
                "success": True,
                "command": "restart",
            }
        except Exception as e:  # pragma: no cover - defensive
            logger = logging.getLogger(__name__)
            logger.exception("Error handling restart request")
            return {
                "type": "response",
                "request_seq": request["seq"],
                "success": False,
                "command": "restart",
                "message": f"Restart failed: {e!s}",
            }

    async def _handle_configurationDone(  # noqa: N802
        self, request: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle configurationDone request."""
        try:
            result = self.server.debugger.configuration_done_request()
            # Only await if it's an awaitable (tests may provide a plain Mock)
            if inspect.isawaitable(result):
                await result
            return {
                "type": "response",
                "request_seq": request["seq"],
                "success": True,
                "command": "configurationDone",
            }
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.exception("Error handling configurationDone request")
            return {
                "type": "response",
                "request_seq": request["seq"],
                "success": False,
                "command": "configurationDone",
                "message": f"Configuration done failed: {e!s}",
            }

    async def _handle_threads(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle threads request."""
        threads = await self.server.debugger.get_threads()
        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "threads",
            "body": {"threads": threads},
        }

    async def _handle_loaded_sources(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle loadedSources request."""
        loaded_sources = await self.server.debugger.get_loaded_sources()
        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "loadedSources",
            "body": {"sources": loaded_sources},
        }

    async def _handle_modules(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle modules request."""
        args = request.get("arguments", {})
        start_module = args.get("startModule", 0)
        module_count = args.get("moduleCount")
        
        # Get all loaded modules from the debugger
        all_modules = await self.server.debugger.get_modules()
        
        # Apply paging
        if module_count is not None:
            end_module = start_module + module_count
            modules = all_modules[start_module:end_module]
        else:
            modules = all_modules[start_module:]
        
        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "modules",
            "body": {"modules": modules},
        }

    async def _handle_stack_trace(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle stackTrace request."""
        args = request["arguments"]
        thread_id = args["threadId"]
        start_frame = args.get("startFrame", 0)
        levels = args.get("levels", 20)
        stack_frames = await self.server.debugger.get_stack_trace(thread_id, start_frame, levels)
        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "stackTrace",
            "body": {
                "stackFrames": stack_frames,
                "totalFrames": len(stack_frames),
            },
        }

    async def _handle_scopes(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle scopes request."""
        frame_id = request["arguments"]["frameId"]
        scopes = await self.server.debugger.get_scopes(frame_id)
        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "scopes",
            "body": {"scopes": scopes},
        }

    async def _handle_variables(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle variables request."""
        args = request["arguments"]
        variables_reference = args["variablesReference"]
        filter_ = args.get("filter")
        start = args.get("start")
        count = args.get("count")
        variables = await self.server.debugger.get_variables(
            variables_reference, filter_, start, count
        )
        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "variables",
            "body": {"variables": variables},
        }

    async def _handle_setVariable(  # noqa: N802
        self, request: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle setVariable request."""
        try:
            args = request["arguments"]
            variables_reference = args["variablesReference"]
            name = args["name"]
            value = args["value"]

            result = await self.server.debugger.set_variable(variables_reference, name, value)

            return {
                "type": "response",
                "request_seq": request["seq"],
                "success": True,
                "command": "setVariable",
                "body": result,
            }
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.exception("Error handling setVariable request")
            return {
                "type": "response",
                "request_seq": request["seq"],
                "success": False,
                "command": "setVariable",
                "message": f"Set variable failed: {e!s}",
            }

    async def _handle_evaluate(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle evaluate request."""
        args = request["arguments"]
        expression = args["expression"]
        frame_id = args.get("frameId")
        context = args.get("context")
        result = await self.server.debugger.evaluate(expression, frame_id, context)
        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "evaluate",
            "body": result,
        }

    async def _handle_exceptionInfo(  # noqa: N802
        self, request: ExceptionInfoRequest
    ) -> dict[str, Any]:
        """Handle exceptionInfo request."""
        try:
            args = request["arguments"]
            thread_id = args["threadId"]

            body = await self.server.debugger.get_exception_info(thread_id)

            return {
                "type": "response",
                "seq": 0,  # Will be set by protocol handler
                "request_seq": request["seq"],
                "success": True,
                "command": "exceptionInfo",
                "body": body,
            }
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.exception("Error handling exceptionInfo request")
            return {
                "type": "response",
                "seq": 0,  # Will be set by protocol handler
                "request_seq": request["seq"],
                "success": False,
                "command": "exceptionInfo",
                "message": f"exceptionInfo failed: {e!s}",
            }


logger = logging.getLogger(__name__)


class DebugAdapterServer:
    """
    Debug adapter server that communicates with a DAP client
    """

    def __init__(
        self,
        connection: ConnectionBase,
        loop: asyncio.AbstractEventLoop | None = None,
    ):
        self.connection = connection
        self.request_handler = RequestHandler(self)
        self.loop = loop or asyncio.get_event_loop()
        self.debugger = PyDebugger(self, self.loop)
        self.running = False
        self.sequence_number = 0
        self.protocol_handler = ProtocolHandler()

    @property
    def next_seq(self) -> int:
        """Get the next sequence number for messages"""
        self.sequence_number += 1
        return self.sequence_number

    async def start(self) -> None:
        """Start the debug adapter server"""
        try:
            await self.connection.accept()
            self.running = True
            await self._message_loop()
        except Exception:
            logger.exception("Error starting debug adapter")
            raise
        finally:
            await self._cleanup()

    async def stop(self) -> None:
        """Stop the debug adapter server"""
        logger.info("Stopping debug adapter server")
        self.running = False
        await self._cleanup()

    async def _cleanup(self) -> None:
        """Clean up resources"""
        if self.debugger:
            await self.debugger.shutdown()

        if self.connection and self.connection.is_connected:
            await self.connection.close()

    async def _message_loop(self) -> None:
        """Main message processing loop"""
        logger.info("Starting message processing loop")
        message: dict[str, Any] | None = None
        while self.running and self.connection.is_connected:
            try:
                message = await self.connection.read_message()
                if not message:
                    logger.info("Client disconnected")
                    break

                await self._process_message(message)
            except asyncio.CancelledError:
                logger.info("Message loop cancelled")
                break
            except Exception as e:
                logger.exception("Error processing message")
                # Send error response if this was a request
                if message is not None and ("type" in message and message["type"] == "request"):
                    await self.send_error_response(message, str(e))

        logger.info("Message loop ended")

    async def _process_message(self, message: dict[str, Any]) -> None:
        """Process an incoming DAP message"""
        if "type" not in message:
            logger.error("Invalid message, missing 'type': %s", message)
            return

        message_type = message["type"]

        if message_type == "request":
            await self._handle_request(message)
        elif message_type == "response":
            logger.warning("Received unexpected response: %s", message)
        elif message_type == "event":
            logger.warning("Received unexpected event: %s", message)
        else:
            logger.error("Unknown message type: %s", message_type)

    async def _handle_request(self, request: dict[str, Any]) -> None:
        """Handle an incoming DAP request"""
        if "command" not in request:
            logger.error("Invalid request, missing 'command': %s", request)
            return

        command = request["command"]
        logger.info("Handling request: %s (seq: %s)", command, request.get("seq", "?"))

        try:
            response = await self.request_handler.handle_request(request)
            if response:
                await self.send_message(response)
        except Exception as e:
            logger.exception("Error handling request %s", command)
            await self.send_error_response(request, str(e))

    async def send_message(self, message: dict[str, Any]) -> None:
        """Send a DAP message to the client"""
        if not self.connection or not self.connection.is_connected:
            logger.warning("Cannot send message: No active connection")
            return

        if "seq" not in message:
            message["seq"] = self.next_seq

        try:
            await self.connection.write_message(message)
        except Exception:
            logger.exception("Error sending message")

    async def send_response(
        self, request: dict[str, Any], body: dict[str, Any] | None = None
    ) -> None:
        """Send a success response to a request"""
        response = self.protocol_handler.create_response(cast("Request", request), True, body)
        await self.send_message(cast("Dict[str, Any]", response))

    async def send_error_response(self, request: dict[str, Any], error_message: str) -> None:
        """Send an error response to a request"""
        response = self.protocol_handler.create_response(
            cast("Request", request), False, None, error_message
        )
        await self.send_message(cast("Dict[str, Any]", response))

    async def send_event(self, event_name: str, body: dict[str, Any] | None = None) -> None:
        """Send an event to the client"""
        event = self.protocol_handler.create_event(event_name, body)
        await self.send_message(cast("Dict[str, Any]", event))
