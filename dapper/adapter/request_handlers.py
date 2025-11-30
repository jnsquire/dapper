"""DAP request handlers.

This module contains the RequestHandler class that processes incoming
Debug Adapter Protocol requests and routes them to appropriate handlers.
"""

from __future__ import annotations

import inspect
import logging
import mimetypes
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from dapper.config import DapperConfig
from dapper.errors import ConfigurationError
from dapper.errors import async_handle_adapter_errors
from dapper.errors import create_dap_response
from dapper.shared import debug_shared

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from collections.abc import Callable

    from dapper.adapter.server import DebugAdapterServer
    from dapper.adapter.types import DAPRequest
    from dapper.adapter.types import DAPResponse
    from dapper.protocol.data_breakpoints import DataBreakpointInfoRequest
    from dapper.protocol.data_breakpoints import DataBreakpointInfoResponse
    from dapper.protocol.data_breakpoints import DataBreakpointInfoResponseBody
    from dapper.protocol.data_breakpoints import SetDataBreakpointsRequest
    from dapper.protocol.data_breakpoints import SetDataBreakpointsResponse
    from dapper.protocol.requests import AttachRequest
    from dapper.protocol.requests import AttachResponse
    from dapper.protocol.requests import ConfigurationDoneRequest
    from dapper.protocol.requests import ConfigurationDoneResponse
    from dapper.protocol.requests import ContinueRequest
    from dapper.protocol.requests import ContinueResponse
    from dapper.protocol.requests import DisconnectRequest
    from dapper.protocol.requests import DisconnectResponse
    from dapper.protocol.requests import EvaluateRequest
    from dapper.protocol.requests import EvaluateResponse
    from dapper.protocol.requests import EvaluateResponseBody
    from dapper.protocol.requests import ExceptionInfoRequest
    from dapper.protocol.requests import ExceptionInfoResponse
    from dapper.protocol.requests import ExceptionInfoResponseBody
    from dapper.protocol.requests import InitializeRequest
    from dapper.protocol.requests import LaunchRequest
    from dapper.protocol.requests import LaunchResponse
    from dapper.protocol.requests import LoadedSourcesRequest
    from dapper.protocol.requests import LoadedSourcesResponse
    from dapper.protocol.requests import Module
    from dapper.protocol.requests import ModuleSourceRequest
    from dapper.protocol.requests import ModuleSourceResponse
    from dapper.protocol.requests import ModuleSourceResponseBody
    from dapper.protocol.requests import ModulesRequest
    from dapper.protocol.requests import ModulesResponse
    from dapper.protocol.requests import NextRequest
    from dapper.protocol.requests import NextResponse
    from dapper.protocol.requests import PauseRequest
    from dapper.protocol.requests import PauseResponse
    from dapper.protocol.requests import RestartRequest
    from dapper.protocol.requests import RestartResponse
    from dapper.protocol.requests import ScopesRequest
    from dapper.protocol.requests import ScopesResponse
    from dapper.protocol.requests import SetBreakpointsRequest
    from dapper.protocol.requests import SetBreakpointsResponse
    from dapper.protocol.requests import SetFunctionBreakpointsRequest
    from dapper.protocol.requests import SetFunctionBreakpointsResponse
    from dapper.protocol.requests import SetVariableRequest
    from dapper.protocol.requests import SetVariableResponse
    from dapper.protocol.requests import SetVariableResponseBody
    from dapper.protocol.requests import SourceRequest
    from dapper.protocol.requests import SourceResponse
    from dapper.protocol.requests import SourceResponseBody
    from dapper.protocol.requests import StackTraceRequest
    from dapper.protocol.requests import StackTraceResponse
    from dapper.protocol.requests import StepInRequest
    from dapper.protocol.requests import StepInResponse
    from dapper.protocol.requests import StepOutRequest
    from dapper.protocol.requests import StepOutResponse
    from dapper.protocol.requests import TerminateRequest
    from dapper.protocol.requests import TerminateResponse
    from dapper.protocol.requests import ThreadsRequest
    from dapper.protocol.requests import ThreadsResponse
    from dapper.protocol.requests import VariablesRequest
    from dapper.protocol.requests import VariablesResponse
    from dapper.protocol.structures import Breakpoint
    from dapper.protocol.structures import Scope
    from dapper.protocol.structures import StackFrame
    from dapper.protocol.structures import Thread
    from dapper.protocol.structures import Variable

# Re-export for type checking - these are used in method signatures/bodies
__all__ = ["RequestHandler"]


logger = logging.getLogger(__name__)


class RequestHandler:
    """
    Handles incoming requests from the DAP client and routes them to the
    appropriate handler methods.
    """

    def __init__(self, server: DebugAdapterServer):
        self.server = server

    async def handle_request(self, request: DAPRequest) -> DAPResponse | None:
        """
        Handle a DAP request and return a response.
        """
        command = request["command"]
        handler_method = getattr(self, f"_handle_{command}", None)
        if handler_method is None:
            # Attempt snake_case fallback for camelCase DAP commands (e.g. setBreakpoints -> set_breakpoints)
            snake = re.sub(r"(?<!^)([A-Z])", r"_\1", command).lower()
            handler_method = getattr(self, f"_handle_{snake}", self._handle_unknown)
        return await handler_method(request)

    async def _handle_unknown(self, request: DAPRequest) -> DAPResponse:
        """Handle an unknown request command."""
        return {
            "type": "response",
            "request_seq": request["seq"],
            "success": False,
            "command": request["command"],
            "message": f"Unsupported command: {request['command']}",
        }

    async def _handle_initialize(self, request: InitializeRequest) -> None:
        """Handle initialize request."""
        # Directly send the response for initialize
        response = {
            "seq": 0,
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
                "supportsDataBreakpoints": True,
                "supportsDataBreakpointInfo": True,
            },
        }
        await self.server.send_message(response)
        # Send the initialized event
        await self.server.send_event("initialized")

    async def _handle_launch(self, request: LaunchRequest) -> LaunchResponse:
        """Handle launch request."""
        try:
            config = DapperConfig.from_launch_request(request)
            config.validate()
        except ConfigurationError as e:
            return cast("LaunchResponse", create_dap_response(e, request["seq"], "launch"))

        try:
            await self.server.debugger.launch(config)
        except Exception as e:
            return cast("LaunchResponse", create_dap_response(e, request["seq"], "launch"))

        return {
            "seq": 0,
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "launch",
        }

    @async_handle_adapter_errors("attach")
    async def _handle_attach(self, request: AttachRequest) -> AttachResponse:
        """Handle attach request.

        Attach connects to an existing debuggee via IPC endpoint.
        The client should specify the endpoint coordinates
        (transport + host/port or path or pipe name).
        IPC is always required for attach.
        """
        config = DapperConfig.from_attach_request(request)
        config.validate()
        
        await self.server.debugger.attach(config)

        return {
            "seq": 0,
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "attach",
        }

    async def _handle_set_breakpoints(self, request: SetBreakpointsRequest) -> SetBreakpointsResponse:
        """Handle setBreakpoints request."""
        args = request.get("arguments", {})
        source = args.get("source", {})
        path = source.get("path")
        breakpoints = args.get("breakpoints", [])

        verified_breakpoints = await self.server.debugger.set_breakpoints(path, breakpoints)

        return {
            "seq": 0,
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "setBreakpoints",
            "body": {"breakpoints": cast("list[Breakpoint]", verified_breakpoints)},
        }

    async def _handle_set_function_breakpoints(
        self, request: SetFunctionBreakpointsRequest
    ) -> SetFunctionBreakpointsResponse:
        """Handle setFunctionBreakpoints request.

        This replaces all existing function breakpoints with the provided set,
        mirroring DAP semantics. Returns verification info per breakpoint.
        """
        args = request.get("arguments", {})
        breakpoints = args.get("breakpoints", [])

        verified = await self.server.debugger.set_function_breakpoints(breakpoints)

        return {
            "seq": 0,
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "setFunctionBreakpoints",
            "body": {"breakpoints": cast("list[Breakpoint]", verified)},
        }

    async def _handle_continue(self, request: ContinueRequest) -> ContinueResponse:
        """Handle continue request."""
        thread_id = request["arguments"]["threadId"]
        continued = await self.server.debugger.continue_execution(thread_id)
        return {
            "seq": 0,
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "continue",
            "body": continued,
        }

    async def _handle_next(self, request: NextRequest) -> NextResponse:
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
            "seq": 0,
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "next",
        }

    async def _handle_step_in(self, request: StepInRequest) -> StepInResponse:
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
            "seq": 0,
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "stepIn",
        }

    async def _handle_step_out(self, request: StepOutRequest) -> StepOutResponse:
        """Handle stepOut request."""
        thread_id = request["arguments"]["threadId"]
        await self.server.debugger.step_out(thread_id)
        return {
            "seq": 0,
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "stepOut",
        }

    async def _handle_pause(self, request: PauseRequest) -> PauseResponse:
        """Handle pause request by delegating to the debugger.pause method.

        Accepts an optional `threadId` argument per the DAP spec.
        """
        args = request.get("arguments", {}) or {}
        thread_id: int = args["threadId"]

        try:
            # Support sync or async implementations of pause()
            success = await self.server.debugger.pause(thread_id)

            return {
                "seq": 0,
                "type": "response",
                "request_seq": request["seq"],
                "success": success,
                "command": "pause",
            }
        except Exception as e:  # pragma: no cover - defensive
            logger.exception("Error handling pause request")
            return {
                "seq": 0,
                "type": "response",
                "request_seq": request["seq"],
                "success": False,
                "command": "pause",
                "message": f"Pause failed: {e!s}",
            }

    async def _handle_disconnect(self, request: DisconnectRequest) -> DisconnectResponse:
        """Handle disconnect request."""
        await self.server.debugger.shutdown()
        return {
            "seq": 0,
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "disconnect",
        }

    async def _handle_terminate(self, request: TerminateRequest) -> TerminateResponse:
        """Handle terminate request - force terminate the debugged program."""
        try:
            await self.server.debugger.terminate()
            return {
                "seq": 0,
                "type": "response",
                "request_seq": request["seq"],
                "success": True,
                "command": "terminate",
            }
        except Exception as e:
            logger.exception("Error handling terminate request")
            return {
                "seq": 0,
                "type": "response",
                "request_seq": request["seq"],
                "success": False,
                "command": "terminate",
                "message": f"Terminate failed: {e!s}",
            }

    async def _handle_restart(self, request: RestartRequest) -> RestartResponse:
        """Handle restart request.

        Semantics: terminate current debuggee and emit a terminated event with
        restart=true so the client restarts the session. Resources are cleaned
        up via the debugger's shutdown.
        """
        try:
            # Delegate to debugger which will send the terminated(restart=true)
            await self.server.debugger.restart()
            return {
                "seq": 0,
                "type": "response",
                "request_seq": request["seq"],
                "success": True,
                "command": "restart",
            }
        except Exception as e:  # pragma: no cover - defensive
            logger.exception("Error handling restart request")
            return {
                "seq": 0,
                "type": "response",
                "request_seq": request["seq"],
                "success": False,
                "command": "restart",
                "message": f"Restart failed: {e!s}",
            }

    async def _handle_configurationDone(  # noqa: N802
        self, request: ConfigurationDoneRequest
    ) -> ConfigurationDoneResponse:
        """Handle configurationDone request."""
        try:
            result = self.server.debugger.configuration_done_request()
            # Only await if it's an awaitable (tests may provide a plain Mock)
            if inspect.isawaitable(result):
                await result
            return cast(
                "ConfigurationDoneResponse",
                {
                    "seq": 0,
                    "type": "response",
                    "request_seq": request["seq"],
                    "success": True,
                    "command": "configurationDone",
                },
            )
        except Exception as e:
            logger.exception("Error handling configurationDone request")
            return cast(
                "ConfigurationDoneResponse",
                {
                    "seq": 0,
                    "type": "response",
                    "request_seq": request["seq"],
                    "success": False,
                    "command": "configurationDone",
                    "message": f"configurationDone failed: {e!s}",
                },
            )

    async def _handle_threads(self, request: ThreadsRequest) -> ThreadsResponse:
        """Handle threads request."""
        threads = await self.server.debugger.get_threads()
        return {
            "seq": 0,
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "threads",
            "body": {"threads": cast("list[Thread]", threads)},
        }

    async def _handle_loaded_sources(self, request: LoadedSourcesRequest) -> LoadedSourcesResponse:
        """Handle loadedSources request."""
        loaded_sources = await self.server.debugger.get_loaded_sources()
        return {
            "seq": 0,
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "loadedSources",
            "body": {"sources": loaded_sources},
        }

    async def _resolve_by_ref(self, source_reference: int) -> tuple[str | None, str | None]:
        """Resolve source content and optional path by sourceReference.

        Returns (content, path) where either may be None on failure.
        """
        dbg = self.server.debugger
        content: str | None = None
        path: str | None = None

        # Try debugger-provided getter first (sync or async)
        getter = getattr(dbg, "get_source_content_by_ref", None)
        if callable(getter):
            try:
                res = getter(source_reference)
                res_val = await res if inspect.isawaitable(res) else res
                # Only accept string content; otherwise fall back
                content = res_val if isinstance(res_val, str) else None
            except Exception:
                content = None

        # Fallback to shared state
        if content is None:
            try:
                content = debug_shared.state.get_source_content_by_ref(source_reference)
            except Exception:
                content = None

        # Try to recover path from meta
        getter_meta = getattr(dbg, "get_source_meta", None)
        try:
            if callable(getter_meta):
                meta = getter_meta(source_reference)
            else:
                meta = debug_shared.state.get_source_meta(source_reference)
            if inspect.isawaitable(meta):
                meta = await meta
            if isinstance(meta, dict):
                path = meta.get("path") or path
        except Exception:
            # ignore meta errors
            pass

        return content, path

    async def _resolve_by_path(self, path: str) -> str | None:
        """Resolve source content by path, prefer debugger helper then shared state."""
        dbg = self.server.debugger
        content: str | None = None

        getter = getattr(dbg, "get_source_content_by_path", None)
        if callable(getter):
            try:
                res = getter(path)
                res_val = await res if inspect.isawaitable(res) else res
                # Only accept string content; otherwise fall back
                content = res_val if isinstance(res_val, str) else None
            except Exception:
                content = None

        if content is None:
            try:
                content = debug_shared.state.get_source_content_by_path(path)
            except Exception:
                content = None

        return content

    def _guess_mime_type(self, path: str | None, content: str) -> str | None:
        """Return a conservative mimeType for textual content when possible."""
        if not path:
            return None
        if "\x00" in content:
            return None

        guessed, _ = mimetypes.guess_type(path)
        if guessed:
            return guessed
        if path.endswith((".py", ".pyw", ".txt", ".md")):
            return "text/plain; charset=utf-8"
        return None

    async def _handle_source(self, request: SourceRequest) -> SourceResponse:
        """Handle source request: return source content by path or sourceReference.

        This mirrors the behavior of the module-level handler in
        `dapper.dap_command_handlers` but runs in the async server context.
        """
        args = request.get("arguments", {}) or {}
        source = args.get("source") or {}
        source_reference = source.get("sourceReference") or args.get("sourceReference")
        path = source.get("path") or args.get("path")

        content: str | None = None

        if source_reference and isinstance(source_reference, int) and source_reference > 0:
            content, recovered_path = await self._resolve_by_ref(source_reference)
            if recovered_path and not path:
                path = recovered_path
        elif path:
            content = await self._resolve_by_path(path)

        if content is None:
            return {
                "seq": 0,
                "type": "response",
                "request_seq": request["seq"],
                "success": False,
                "command": "source",
                "message": "Could not load source content",
            }

        mime_type = self._guess_mime_type(path, content)

        body: SourceResponseBody = {"content": content}
        if mime_type:
            body["mimeType"] = mime_type

        return {
            "seq": 0,
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "source",
            "body": body,
        }

    async def _handle_module_source(self, request: ModuleSourceRequest) -> ModuleSourceResponse:
        """Handle moduleSource request: return source content for a given module id.

        The server's `modules` response uses stringified id(module) as the
        module id. This handler accepts either that id or a module name and
        returns file contents for the module if available.
        """
        args = request.get("arguments", {}) or {}
        module_id = args.get("moduleId") or args.get("module")
        if not module_id:
            return {
                "seq": 0,
                "type": "response",
                "request_seq": request["seq"],
                "success": False,
                "command": "moduleSource",
                "message": "Missing moduleId",
            }

        found = None
        for name, mod in list(sys.modules.items()):
            if mod is None:
                continue
            try:
                if str(id(mod)) == str(module_id) or name == module_id:
                    found = mod
                    break
            except Exception:
                continue

        if found is None:
            return {
                "seq": 0,
                "type": "response",
                "request_seq": request["seq"],
                "success": False,
                "command": "moduleSource",
                "message": "Module not found",
            }

        path = getattr(found, "__file__", None)
        if not path:
            return {
                "seq": 0,
                "type": "response",
                "request_seq": request["seq"],
                "success": False,
                "command": "moduleSource",
                "message": "Module has no file path",
            }

        try:
            with Path(path).open("rb") as f:
                data = f.read()
            # Try to decode as utf-8; if it fails preserve bytes as latin-1 to
            # keep a 1:1 mapping so NUL bytes survive for downstream checks.
            try:
                content = data.decode("utf-8")
            except Exception:
                content = data.decode("latin-1")
        except Exception as e:
            return {
                "seq": 0,
                "type": "response",
                "request_seq": request["seq"],
                "success": False,
                "command": "moduleSource",
                "message": f"Failed to read module source: {e!s}",
            }

        body: ModuleSourceResponseBody = {"content": content}
        return {
            "seq": 0,
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "moduleSource",
            "body": body,
        }

    async def _handle_modules(self, request: ModulesRequest) -> ModulesResponse:
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
            "seq": 0,
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "modules",
            "body": {"modules": cast("list[Module]", modules)}
        }

    async def _handle_stack_trace(self, request: StackTraceRequest) -> StackTraceResponse:
        """Handle stackTrace request."""
        args = request["arguments"]
        thread_id = args["threadId"]
        start_frame = args.get("startFrame", 0)
        levels = args.get("levels", 20)
        stack_frames = await self.server.debugger.get_stack_trace(thread_id, start_frame, levels)
        return {
            "seq": 0,
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "stackTrace",
            "body": {
                "stackFrames": cast("list[StackFrame]", stack_frames),
                "totalFrames": len(stack_frames),
            },
        }

    async def _handle_scopes(self, request: ScopesRequest) -> ScopesResponse:
        """Handle scopes request."""
        frame_id = request["arguments"]["frameId"]
        scopes = await self.server.debugger.get_scopes(frame_id)
        return {
            "seq": 0,
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "scopes",
            "body": {"scopes": cast("list[Scope]", scopes)},
        }

    async def _handle_variables(self, request: VariablesRequest) -> VariablesResponse:
        """Handle variables request."""
        args = request["arguments"]
        variables_reference = args["variablesReference"]
        filter_ = args.get("filter", "")
        start = args.get("start", 0)
        count = args.get("count", 0)
        variables = await self.server.debugger.get_variables(
            variables_reference, filter_, start, count
        )
        return {
            "seq": 0,
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "variables",
            "body": {"variables": cast("list[Variable]", variables)},
        }

    async def _handle_setVariable(  # noqa: N802
        self, request: SetVariableRequest
    ) -> SetVariableResponse:
        """Handle setVariable request."""
        try:
            args = request["arguments"]
            variables_reference = args["variablesReference"]
            name = args["name"]
            value = args["value"]

            result = await self.server.debugger.set_variable(variables_reference, name, value)

            return {
                "seq": 0,
                "type": "response",
                "request_seq": request["seq"],
                "success": True,
                "command": "setVariable",
                "body": cast("SetVariableResponseBody", result),
            }
        except Exception as e:
            logger.exception("Error handling setVariable request")
            return {
                "seq": 0,
                "type": "response",
                "request_seq": request["seq"],
                "success": False,
                "command": "setVariable",
                "message": f"Set variable failed: {e!s}",
            }

    async def _handle_evaluate(self, request: EvaluateRequest) -> EvaluateResponse:
        """Handle evaluate request."""
        args = request["arguments"]
        expression = args["expression"]
        frame_id = args.get("frameId")
        context = args.get("context")
        result = await self.server.debugger.evaluate(expression, frame_id, context)
        return {
            "seq": 0,
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "evaluate",
            "body": cast("EvaluateResponseBody", result),
        }

    async def _handle_dataBreakpointInfo(  # noqa: N802
        self, request: DataBreakpointInfoRequest
    ) -> DataBreakpointInfoResponse:
        """Handle dataBreakpointInfo request (subset: variable name + frameId)."""
        args = request.get("arguments", {})
        name = args.get("name")
        frame_id = args.get("frameId")
        if name is None or frame_id is None:
            body: DataBreakpointInfoResponseBody = {
                "dataId": None,
                "description": "Data breakpoint unsupported for missing name/frameId",
                "accessTypes": ["write"],
                "canPersist": False,
            }
        else:
            body = cast(
                "DataBreakpointInfoResponseBody",
                self.server.debugger.data_breakpoint_info(name=name, frame_id=frame_id),
            )
        return {
            "seq": 0,
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "dataBreakpointInfo",
            "body": body,
        }

    async def _handle_setDataBreakpoints(  # noqa: N802
        self, request: SetDataBreakpointsRequest
    ) -> SetDataBreakpointsResponse:
        """Handle setDataBreakpoints request (full replace)."""
        args = request.get("arguments", {})
        bps = args.get("breakpoints", [])
        results = self.server.debugger.set_data_breakpoints(bps)
        return {
            "seq": 0,
            "type": "response",
            "request_seq": request["seq"],
            "success": True,
            "command": "setDataBreakpoints",
            "body": {"breakpoints": cast("list[Breakpoint]", results)},
        }

    async def _handle_exceptionInfo(  # noqa: N802
        self, request: ExceptionInfoRequest
    ) -> ExceptionInfoResponse:
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
                "body": cast("ExceptionInfoResponseBody", body),
            }
        except Exception as e:
            logger.exception("Error handling exceptionInfo request")
            return {
                "type": "response",
                "seq": 0,  # Will be set by protocol handler
                "request_seq": request["seq"],
                "success": False,
                "command": "exceptionInfo",
                "message": f"exceptionInfo failed: {e!s}",
            }
