"""DAP request handlers.

This module contains the RequestHandler class that processes incoming
Debug Adapter Protocol requests and routes them to appropriate handlers.
"""

from __future__ import annotations

import inspect
import logging
import mimetypes
from pathlib import Path
import re
import sys
from typing import TYPE_CHECKING
from typing import Any
from typing import TypeVar

from dapper.adapter.types import DAPResponse
from dapper.config import DapperConfig
from dapper.errors import ConfigurationError
from dapper.errors import create_dap_response
from dapper.protocol.data_breakpoints import DataBreakpointInfoResponse
from dapper.protocol.data_breakpoints import SetDataBreakpointsResponse
from dapper.protocol.requests import AttachResponse
from dapper.protocol.requests import CompletionsResponse
from dapper.protocol.requests import ConfigurationDoneResponse
from dapper.protocol.requests import ContinueResponse
from dapper.protocol.requests import DisconnectResponse
from dapper.protocol.requests import EvaluateResponse
from dapper.protocol.requests import ExceptionInfoResponse
from dapper.protocol.requests import LaunchResponse
from dapper.protocol.requests import LoadedSourcesResponse
from dapper.protocol.requests import ModuleSourceResponse
from dapper.protocol.requests import ModulesResponse
from dapper.protocol.requests import NextResponse
from dapper.protocol.requests import PauseResponse
from dapper.protocol.requests import RestartResponse
from dapper.protocol.requests import ScopesResponse
from dapper.protocol.requests import SetBreakpointsResponse
from dapper.protocol.requests import SetFunctionBreakpointsResponse
from dapper.protocol.requests import SetVariableResponse
from dapper.protocol.requests import SourceResponse
from dapper.protocol.requests import StackTraceResponse
from dapper.protocol.requests import StepInResponse
from dapper.protocol.requests import StepOutResponse
from dapper.protocol.requests import TerminateResponse
from dapper.protocol.requests import ThreadsResponse
from dapper.protocol.requests import VariablesResponse
from dapper.shared import debug_shared

if TYPE_CHECKING:
    from dapper.adapter.server_core import DebugAdapterServer
    from dapper.adapter.types import DAPRequest
    from dapper.protocol.data_breakpoints import DataBreakpointInfoRequest
    from dapper.protocol.data_breakpoints import DataBreakpointInfoResponseBody
    from dapper.protocol.data_breakpoints import SetDataBreakpointsRequest
    from dapper.protocol.requests import AttachRequest
    from dapper.protocol.requests import CompletionsRequest
    from dapper.protocol.requests import ConfigurationDoneRequest
    from dapper.protocol.requests import ContinueRequest
    from dapper.protocol.requests import DisconnectRequest
    from dapper.protocol.requests import EvaluateRequest
    from dapper.protocol.requests import ExceptionInfoRequest
    from dapper.protocol.requests import InitializeRequest
    from dapper.protocol.requests import LaunchRequest
    from dapper.protocol.requests import LoadedSourcesRequest
    from dapper.protocol.requests import ModuleSourceRequest
    from dapper.protocol.requests import ModuleSourceResponseBody
    from dapper.protocol.requests import ModulesRequest
    from dapper.protocol.requests import NextRequest
    from dapper.protocol.requests import PauseRequest
    from dapper.protocol.requests import RestartRequest
    from dapper.protocol.requests import ScopesRequest
    from dapper.protocol.requests import SetBreakpointsRequest
    from dapper.protocol.requests import SetFunctionBreakpointsRequest
    from dapper.protocol.requests import SetVariableRequest
    from dapper.protocol.requests import SourceRequest
    from dapper.protocol.requests import SourceResponseBody
    from dapper.protocol.requests import StackTraceRequest
    from dapper.protocol.requests import StepInRequest
    from dapper.protocol.requests import StepOutRequest
    from dapper.protocol.requests import TerminateRequest
    from dapper.protocol.requests import ThreadsRequest
    from dapper.protocol.requests import VariablesRequest

# Re-export for type checking - these are used in method signatures/bodies
__all__ = ["RequestHandler"]

_R = TypeVar("_R")

logger = logging.getLogger(__name__)


class RequestHandler:
    """Handles incoming requests from the DAP client and routes them to the
    appropriate handler methods.
    """

    def __init__(self, server: DebugAdapterServer):
        self.server = server

    async def handle_request(self, request: DAPRequest) -> DAPResponse | None:
        """Handle a DAP request and return a response."""
        command = request["command"]
        handler_method = getattr(self, f"_handle_{command}", None)
        if handler_method is None:
            # DAP command names are camelCase (e.g. "configurationDone"); convert
            # to snake_case so they match the handler method naming convention.
            snake = re.sub(r"(?<!^)([A-Z])", r"_\1", command).lower()
            handler_method = getattr(self, f"_handle_{snake}", self._handle_unknown)
        return await handler_method(request)

    def _make_response(
        self,
        request: Any,
        command: str,
        response_type: type[_R],  # noqa: ARG002
        *,
        success: bool = True,
        body: Any | None = None,
        message: str | None = None,
    ) -> _R:
        """Build a standard DAP response object used across handlers.

        The ``response_type`` parameter binds the generic return type so
        callers receive the exact response TypedDict they expect without
        needing an explicit ``cast``.  The parameter is not used at
        runtime — it exists solely to guide the type checker.
        """
        resp: dict[str, Any] = {
            "seq": 0,
            "type": "response",
            "request_seq": request["seq"],
            "success": success,
            "command": command,
        }
        if body is not None:
            resp["body"] = body
        elif not success and message is not None:
            resp["body"] = {
                "error": "RequestError",
                "details": {"command": command},
            }
        if message is not None:
            resp["message"] = message
        return resp  # type: ignore[return-value]

    async def _handle_unknown(self, request: DAPRequest) -> DAPResponse:
        """Handle an unknown request command."""
        return self._make_response(
            request,
            request["command"],
            DAPResponse,
            success=False,
            message=f"Unsupported command: {request['command']}",
        )

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
            return create_dap_response(e, request["seq"], "launch")

        try:
            await self.server.debugger.launch(config)
        except Exception as e:
            return create_dap_response(e, request["seq"], "launch")

        return self._make_response(request, "launch", LaunchResponse)

    async def _handle_attach(self, request: AttachRequest) -> AttachResponse:
        """Handle attach request.

        Attach connects to an existing debuggee via IPC endpoint.
        The client should specify the endpoint coordinates
        (transport + host/port or path or pipe name).
        IPC is always required for attach.
        """
        try:
            config = DapperConfig.from_attach_request(request)
            config.validate()
        except ConfigurationError as e:
            return create_dap_response(e, request["seq"], "attach")

        try:
            await self.server.debugger.attach(config)
        except Exception as e:
            return create_dap_response(e, request["seq"], "attach")

        return self._make_response(request, "attach", AttachResponse)

    async def _handle_set_breakpoints(
        self,
        request: SetBreakpointsRequest,
    ) -> SetBreakpointsResponse:
        """Handle setBreakpoints request."""
        args = request.get("arguments", {})
        source = args.get("source", {})
        path = source.get("path")
        breakpoints = args.get("breakpoints", [])

        verified_breakpoints = await self.server.debugger.set_breakpoints(path, breakpoints)

        return self._make_response(
            request,
            "setBreakpoints",
            SetBreakpointsResponse,
            body={"breakpoints": verified_breakpoints},
        )

    async def _handle_set_function_breakpoints(
        self,
        request: SetFunctionBreakpointsRequest,
    ) -> SetFunctionBreakpointsResponse:
        """Handle setFunctionBreakpoints request.

        This replaces all existing function breakpoints with the provided set,
        mirroring DAP semantics. Returns verification info per breakpoint.
        """
        args = request.get("arguments", {})
        breakpoints = args.get("breakpoints", [])

        verified = await self.server.debugger.set_function_breakpoints(breakpoints)

        return self._make_response(
            request,
            "setFunctionBreakpoints",
            SetFunctionBreakpointsResponse,
            body={"breakpoints": verified},
        )

    async def _handle_continue(self, request: ContinueRequest) -> ContinueResponse:
        """Handle continue request."""
        thread_id = request["arguments"]["threadId"]
        continued = await self.server.debugger.continue_execution(thread_id)
        return self._make_response(request, "continue", ContinueResponse, body=continued)

    async def _handle_next(self, request: NextRequest) -> NextResponse:
        """Handle next request."""
        args = request["arguments"]
        thread_id = args["threadId"]
        granularity: str = args.get("granularity") or "line"
        await self.server.debugger.next(thread_id, granularity=granularity)
        return self._make_response(request, "next", NextResponse)

    async def _handle_step_in(self, request: StepInRequest) -> StepInResponse:
        """Handle stepIn request."""
        args = request["arguments"]
        thread_id = args["threadId"]
        target_id = args.get("targetId")
        granularity: str = args.get("granularity") or "line"
        await self.server.debugger.step_in(thread_id, target_id, granularity=granularity)
        return self._make_response(request, "stepIn", StepInResponse)

    async def _handle_step_out(self, request: StepOutRequest) -> StepOutResponse:
        """Handle stepOut request."""
        args = request["arguments"]
        thread_id = args["threadId"]
        granularity: str = args.get("granularity") or "line"
        await self.server.debugger.step_out(thread_id, granularity=granularity)
        return self._make_response(request, "stepOut", StepOutResponse)

    async def _handle_pause(self, request: PauseRequest) -> PauseResponse:
        """Handle pause request by delegating to the debugger.pause method.

        Accepts an optional `threadId` argument per the DAP spec.
        """
        args = request.get("arguments", {}) or {}
        thread_id: int = args["threadId"]

        try:
            # Support sync or async implementations of pause()
            success = await self.server.debugger.pause(thread_id)

            return self._make_response(request, "pause", PauseResponse, success=success)
        except Exception as e:  # pragma: no cover - defensive
            logger.exception("Error handling pause request")
            return self._make_response(
                request,
                "pause",
                PauseResponse,
                success=False,
                message=f"Pause failed: {e!s}",
            )

    async def _handle_disconnect(self, request: DisconnectRequest) -> DisconnectResponse:
        """Handle disconnect request."""
        await self.server.debugger.shutdown()
        return self._make_response(request, "disconnect", DisconnectResponse)

    async def _handle_terminate(self, request: TerminateRequest) -> TerminateResponse:
        """Handle terminate request - force terminate the debugged program."""
        try:
            await self.server.debugger.terminate()
            return self._make_response(request, "terminate", TerminateResponse)
        except Exception as e:
            logger.exception("Error handling terminate request")
            return self._make_response(
                request,
                "terminate",
                TerminateResponse,
                success=False,
                message=f"Terminate failed: {e!s}",
            )

    async def _handle_restart(self, request: RestartRequest) -> RestartResponse:
        """Handle restart request.

        Semantics: terminate current debuggee and emit a terminated event with
        restart=true so the client restarts the session. Resources are cleaned
        up via the debugger's shutdown.
        """
        try:
            # Delegate to debugger which will send the terminated(restart=true)
            await self.server.debugger.restart()
            return self._make_response(request, "restart", RestartResponse)
        except Exception as e:  # pragma: no cover - defensive
            logger.exception("Error handling restart request")
            return self._make_response(
                request,
                "restart",
                RestartResponse,
                success=False,
                message=f"Restart failed: {e!s}",
            )

    async def _handle_configuration_done(
        self,
        request: ConfigurationDoneRequest,
    ) -> ConfigurationDoneResponse:
        """Handle configurationDone request."""
        try:
            await self.server.debugger.configuration_done_request()
            return self._make_response(request, "configurationDone", ConfigurationDoneResponse)
        except Exception as e:
            logger.exception("Error handling configurationDone request")
            return self._make_response(
                request,
                "configurationDone",
                ConfigurationDoneResponse,
                success=False,
                message=f"configurationDone failed: {e!s}",
            )

    async def _handle_threads(self, request: ThreadsRequest) -> ThreadsResponse:
        """Handle threads request."""
        threads = await self.server.debugger.get_threads()
        return self._make_response(request, "threads", ThreadsResponse, body={"threads": threads})

    async def _handle_loaded_sources(self, request: LoadedSourcesRequest) -> LoadedSourcesResponse:
        """Handle loadedSources request."""
        loaded_sources = await self.server.debugger.get_loaded_sources()
        return self._make_response(
            request,
            "loadedSources",
            LoadedSourcesResponse,
            body={"sources": loaded_sources},
        )

    async def _resolve_by_ref(self, source_reference: int) -> tuple[str | None, str | None]:
        """Resolve source content and optional path by sourceReference.

        Returns (content, path) where either may be None on failure.
        """
        dbg = self.server.debugger
        active_session = debug_shared.get_active_session()
        content: str | None = None
        path: str | None = None

        # Try debugger-provided getter first (sync or async)
        getter = getattr(dbg, "get_source_content_by_ref", None)
        if callable(getter):
            try:
                res = getter(source_reference)
                if inspect.isawaitable(res):
                    res_val = await res
                else:
                    res_val = res
                # Only accept string content; otherwise fall back
                content = res_val if isinstance(res_val, str) else None
            except Exception:
                content = None

        # Fallback to shared state
        if content is None:
            try:
                content = active_session.get_source_content_by_ref(source_reference)
            except Exception:
                content = None

        # Try to recover path from meta
        getter_meta = getattr(dbg, "get_source_meta", None)
        try:
            if callable(getter_meta):
                res_meta = getter_meta(source_reference)
                if inspect.isawaitable(res_meta):
                    meta = await res_meta
                else:
                    meta = res_meta
            else:
                meta = active_session.get_source_meta(source_reference)
            if isinstance(meta, dict):
                path = meta.get("path") or path
        except Exception:
            # ignore meta errors
            pass

        return content, path

    async def _resolve_by_path(self, path: str) -> str | None:
        """Resolve source content by path, prefer debugger helper then shared state."""
        dbg = self.server.debugger
        active_session = debug_shared.get_active_session()
        content: str | None = None

        getter = getattr(dbg, "get_source_content_by_path", None)
        if callable(getter):
            try:
                res = getter(path)
                if inspect.isawaitable(res):
                    res_val = await res
                else:
                    res_val = res
                # Only accept string content; otherwise fall back
                content = res_val if isinstance(res_val, str) else None
            except Exception:
                content = None

        if content is None:
            try:
                content = active_session.get_source_content_by_path(path)
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
            return self._make_response(
                request,
                "source",
                SourceResponse,
                success=False,
                message="Could not load source content",
            )

        mime_type = self._guess_mime_type(path, content)

        body: SourceResponseBody = {"content": content}
        if mime_type:
            body["mimeType"] = mime_type

        return self._make_response(request, "source", SourceResponse, body=body)

    async def _handle_module_source(self, request: ModuleSourceRequest) -> ModuleSourceResponse:
        """Handle moduleSource request: return source content for a given module id.

        The server's `modules` response uses stringified id(module) as the
        module id. This handler accepts either that id or a module name and
        returns file contents for the module if available.
        """
        args = request.get("arguments", {}) or {}
        module_id = args.get("moduleId") or args.get("module")
        body, message = self._prepare_module_source_body(module_id)
        success = body is not None
        return self._make_response(
            request,
            "moduleSource",
            ModuleSourceResponse,
            success=success,
            message=message,
            body=body,
        )

    def _prepare_module_source_body(
        self,
        module_id: str | int | None,
    ) -> tuple[ModuleSourceResponseBody | None, str | None]:
        if not module_id:
            return None, "Missing moduleId"

        found = self._find_module_by_id(module_id)
        if found is None:
            return None, "Module not found"

        resolved, message = self._resolve_module_path(found)
        if resolved is None:
            return None, message

        content, message = self._read_module_content(resolved)
        if content is None:
            return None, message

        return {"content": content}, None

    def _find_module_by_id(self, module_id: str | int) -> object | None:
        for name, mod in list(sys.modules.items()):
            if mod is None:
                continue
            try:
                if str(id(mod)) == str(module_id) or name == module_id:
                    return mod
            except Exception:
                continue
        return None

    def _resolve_module_path(self, module: object) -> tuple[Path | None, str | None]:
        path = getattr(module, "__file__", None)
        if not path:
            return None, "Module has no file path"
        try:
            resolved = Path(path).resolve(strict=True)
        except (OSError, ValueError):
            return None, "Module file path could not be resolved"
        if not resolved.is_file():
            return None, "Module path is not a regular file"
        if resolved.suffix.lower() not in (".py", ".pyw"):
            return None, "Module path is not a Python source file"
        return resolved, None

    def _read_module_content(self, resolved: Path) -> tuple[str | None, str | None]:
        try:
            with resolved.open("rb") as f:
                data = f.read()
        except Exception as exc:
            return None, f"Failed to read module source: {exc!s}"
        try:
            return data.decode("utf-8"), None
        except Exception:
            return data.decode("latin-1"), None

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

        return self._make_response(request, "modules", ModulesResponse, body={"modules": modules})

    async def _handle_stack_trace(self, request: StackTraceRequest) -> StackTraceResponse:
        """Handle stackTrace request."""
        args = request["arguments"]
        thread_id = args["threadId"]
        start_frame = args.get("startFrame", 0)
        levels = args.get("levels", 20)
        stack_frames = await self.server.debugger.get_stack_trace(thread_id, start_frame, levels)
        return self._make_response(
            request,
            "stackTrace",
            StackTraceResponse,
            body={
                "stackFrames": stack_frames,
                "totalFrames": len(stack_frames),
            },
        )

    async def _handle_scopes(self, request: ScopesRequest) -> ScopesResponse:
        """Handle scopes request."""
        frame_id = request["arguments"]["frameId"]
        scopes = await self.server.debugger.get_scopes(frame_id)
        return self._make_response(request, "scopes", ScopesResponse, body={"scopes": scopes})

    async def _handle_variables(self, request: VariablesRequest) -> VariablesResponse:
        """Handle variables request."""
        args = request["arguments"]
        variables_reference = args["variablesReference"]
        filter_ = args.get("filter", "")
        start = args.get("start", 0)
        count = args.get("count", 0)
        variables = await self.server.debugger.get_variables(
            variables_reference,
            filter_,
            start,
            count,
        )
        return self._make_response(
            request,
            "variables",
            VariablesResponse,
            body={"variables": variables},
        )

    async def _handle_set_variable(self, request: SetVariableRequest) -> SetVariableResponse:
        """Handle setVariable request."""
        try:
            args = request["arguments"]
            variables_reference = args["variablesReference"]
            name = args["name"]
            value = args["value"]

            result = await self.server.debugger.set_variable(variables_reference, name, value)

            return self._make_response(request, "setVariable", SetVariableResponse, body=result)
        except Exception as e:
            logger.exception("Error handling setVariable request")
            return self._make_response(
                request,
                "setVariable",
                SetVariableResponse,
                success=False,
                message=f"Set variable failed: {e!s}",
            )

    async def _handle_evaluate(self, request: EvaluateRequest) -> EvaluateResponse:
        """Handle evaluate request."""
        args = request["arguments"]
        expression = args["expression"]
        frame_id = args.get("frameId")
        context = args.get("context")
        result = await self.server.debugger.evaluate(expression, frame_id, context)
        return self._make_response(request, "evaluate", EvaluateResponse, body=result)

    async def _handle_data_breakpoint_info(
        self,
        request: DataBreakpointInfoRequest,
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
            body = self.server.debugger.data_breakpoint_info(name=name, frame_id=frame_id)
        return self._make_response(
            request,
            "dataBreakpointInfo",
            DataBreakpointInfoResponse,
            body=body,
        )

    async def _handle_set_data_breakpoints(
        self,
        request: SetDataBreakpointsRequest,
    ) -> SetDataBreakpointsResponse:
        """Handle setDataBreakpoints request (full replace)."""
        args = request.get("arguments", {})
        bps = args.get("breakpoints", [])
        results = self.server.debugger.set_data_breakpoints(bps)
        return self._make_response(
            request,
            "setDataBreakpoints",
            SetDataBreakpointsResponse,
            body={"breakpoints": results},
        )

    async def _handle_exception_info(self, request: ExceptionInfoRequest) -> ExceptionInfoResponse:
        """Handle exceptionInfo request."""
        try:
            args = request["arguments"]
            thread_id = args["threadId"]

            body = await self.server.debugger.get_exception_info(thread_id)

            return self._make_response(request, "exceptionInfo", ExceptionInfoResponse, body=body)
        except Exception as e:
            logger.exception("Error handling exceptionInfo request")
            return self._make_response(
                request,
                "exceptionInfo",
                ExceptionInfoResponse,
                success=False,
                message=f"exceptionInfo failed: {e!s}",
            )

    async def _handle_completions(self, request: CompletionsRequest) -> CompletionsResponse:
        """Handle completions request for expression auto-complete.

        Provides intelligent completions for the debug console and watch
        expressions based on runtime frame context when available.
        """
        try:
            args = request["arguments"]
            text = args["text"]
            column = args["column"]
            frame_id = args.get("frameId")
            line = args.get("line", 1)

            body = await self.server.debugger.completions(
                text=text,
                column=column,
                frame_id=frame_id,
                line=line,
            )

            return self._make_response(request, "completions", CompletionsResponse, body=body)
        except Exception as e:
            logger.exception("Error handling completions request")
            return self._make_response(
                request,
                "completions",
                CompletionsResponse,
                success=False,
                message=f"Completions failed: {e!s}",
            )
