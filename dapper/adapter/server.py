"""
Implementation of integrated Python debugger components.

This module contains the debugger orchestration (`PyDebugger`) and helper
managers used by the adapter server core.
"""

# ruff: noqa: SLF001

from __future__ import annotations

import asyncio
import contextlib
import importlib
import inspect
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from dapper.adapter.external_backend import ExternalProcessBackend
from dapper.adapter.inprocess_backend import InProcessBackend
from dapper.adapter.inprocess_bridge import InProcessBridge
from dapper.adapter.payload_extractor import extract_payload
from dapper.adapter.source_tracker import LoadedSourceTracker
from dapper.adapter.types import BreakpointDict
from dapper.adapter.types import BreakpointResponse
from dapper.adapter.types import PyDebuggerThread
from dapper.adapter.types import SourceDict
from dapper.core.inprocess_debugger import InProcessDebugger
from dapper.ipc import TransportConfig
from dapper.ipc.ipc_manager import IPCManager
from dapper.protocol.structures import Source
from dapper.protocol.structures import SourceBreakpoint
from dapper.shared.command_handlers import MAX_VALUE_REPR_LEN

try:
    # Optional integration module; may not be present on all platforms.
    from dapper._frame_eval.debugger_integration import integrate_py_debugger
except Exception:  # pragma: no cover - optional feature
    integrate_py_debugger = None


if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Sequence

    from dapper.adapter.types import CompletionsResponseBody
    from dapper.config import DapperConfig
    from dapper.protocol.capabilities import ExceptionFilterOptions
    from dapper.protocol.capabilities import ExceptionOptions
    from dapper.protocol.data_breakpoints import DataBreakpointInfoResponseBody
    from dapper.protocol.debugger_protocol import Variable
    from dapper.protocol.requests import ContinueResponseBody
    from dapper.protocol.requests import EvaluateResponseBody
    from dapper.protocol.requests import ExceptionDetails
    from dapper.protocol.requests import ExceptionInfoResponseBody
    from dapper.protocol.requests import FunctionBreakpoint
    from dapper.protocol.requests import Module
    from dapper.protocol.requests import SetVariableResponseBody
    from dapper.protocol.requests import StackTraceResponseBody
    from dapper.protocol.structures import Breakpoint
    from dapper.protocol.structures import Scope
    from dapper.protocol.structures import Thread


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event loop acquisition helpers
# ---------------------------------------------------------------------------
def _acquire_event_loop(
    preferred: asyncio.AbstractEventLoop | None = None,
) -> tuple[asyncio.AbstractEventLoop, bool]:
    """Return an event loop avoiding deprecated APIs.

    Order of preference:
    1. A caller-supplied loop (never marked owned).
    2. A currently running loop (``asyncio.get_running_loop``).
    3. A freshly created loop (marked owned so the debugger can close it).

    We intentionally avoid ``asyncio.get_event_loop`` to silence deprecation
    warnings under Python 3.12+ when no loop is set for the current thread.
    """
    if preferred is not None:
        return preferred, False
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is not None:
        return running, False
    new_loop = asyncio.new_event_loop()
    return new_loop, True


class _PyDebuggerEventRouter:
    """Routes and applies debuggee events for a ``PyDebugger`` instance."""

    def __init__(self, debugger: PyDebugger):
        self._debugger = debugger

    def handle_event_stopped(self, data: dict[str, Any]) -> None:
        """Handle stopped event state updates."""
        thread_id = data.get("threadId", 1)
        reason = data.get("reason", "breakpoint")

        with self._debugger.lock:
            thread = self._debugger.threads.get(thread_id)
            if thread is None:
                self._debugger.threads[thread_id] = thread = PyDebuggerThread(
                    thread_id, f"Thread {thread_id}"
                )
            thread.is_stopped = True
            thread.stop_reason = reason

        try:
            self._debugger.stopped_event.set()
        except Exception:
            try:
                self._debugger.loop.call_soon_threadsafe(self._debugger.stopped_event.set)
            except Exception:
                with contextlib.suppress(Exception):
                    self._debugger.stopped_event.set()

    def handle_event_thread(self, data: dict[str, Any]) -> None:
        """Handle thread started/exited state updates."""
        thread_id = data.get("threadId", 1)
        reason = data.get("reason", "started")

        if reason == "started":
            with self._debugger.lock:
                if thread_id not in self._debugger.threads:
                    default_name = f"Thread {thread_id}"
                    thread_name = data.get("name", default_name)
                    self._debugger.threads[thread_id] = PyDebuggerThread(thread_id, thread_name)
        else:
            with self._debugger.lock:
                if thread_id in self._debugger.threads:
                    del self._debugger.threads[thread_id]

    def handle_event_exited(self, data: dict[str, Any]) -> None:
        """Handle debuggee exited event and schedule cleanup."""
        exit_code = data.get("exitCode", 0)
        self._debugger.is_terminated = True
        self._debugger.schedule_program_exit(exit_code)

    def handle_event_stacktrace(self, data: dict[str, Any]) -> None:
        """Cache stack trace data from the debuggee."""
        thread_id = data.get("threadId", 1)
        stack_frames = data.get("stackFrames", [])
        with self._debugger.lock:
            self._debugger.current_stack_frames[thread_id] = stack_frames

    def handle_event_variables(self, data: dict[str, Any]) -> None:
        """Cache variables payload from the debuggee."""
        var_ref = data.get("variablesReference", 0)
        variables = data.get("variables", [])
        with self._debugger.lock:
            self._debugger.var_refs[var_ref] = variables

    def handle_debug_message(self, message: str) -> None:
        """Handle a debug protocol message from the debuggee."""
        try:
            data: dict[str, Any] = json.loads(message)
        except Exception:
            logger.exception("Error handling debug message")
            return

        # Handle command responses
        command_id = data.get("id")
        if command_id is not None and self._debugger.has_pending_command(command_id):
            future = self._debugger.pop_pending_command(command_id)
            if future is not None:
                self._debugger.resolve_pending_response(future, data)
            return

        event_type: str | None = data.get("event")
        if event_type is None:
            return

        # Events that require state updates before forwarding
        if event_type == "stopped":
            self.handle_event_stopped(data)
        elif event_type == "thread":
            self.handle_event_thread(data)
        elif event_type == "exited":
            self.handle_event_exited(data)
            return  # exited schedules its own events
        # Events that only cache state (no forwarding)
        elif event_type == "stackTrace":
            self.handle_event_stacktrace(data)
            return
        elif event_type == "variables":
            self.handle_event_variables(data)
            return

        # Forward all events that have payload extractors
        payload = extract_payload(event_type, data)
        if payload is not None:
            self._debugger.emit_event(event_type, payload)


class _PyDebuggerLifecycleManager:
    """Handles launch/attach lifecycle orchestration for ``PyDebugger``."""

    def __init__(self, debugger: PyDebugger):
        self._debugger = debugger

    async def launch(self, config: DapperConfig) -> None:
        """Launch a new Python program for debugging using centralized configuration."""
        config.validate()

        if self._debugger.program_running:
            msg = "A program is already being debugged"
            raise RuntimeError(msg)

        # Update server state from config
        self._debugger.program_path = str(Path(config.debuggee.program).resolve())
        self._debugger.stop_on_entry = config.debuggee.stop_on_entry
        self._debugger.no_debug = config.debuggee.no_debug
        self._debugger.in_process = config.in_process

        # Optional in-process mode
        if config.in_process:
            await self.launch_in_process()
            return

        # Create a new subprocess running the debugged program
        debug_args = [
            sys.executable,
            "-m",
            "dapper.launcher.debug_launcher",
            "--program",
            self._debugger.program_path,
        ]

        # Pass other arguments
        for arg in config.debuggee.args:
            debug_args.extend(["--arg", arg])

        if config.debuggee.stop_on_entry:
            debug_args.append("--stop-on-entry")

        if config.debuggee.no_debug:
            debug_args.append("--no-debug")

        # If IPC is requested, prepare a listener and pass coordinates.
        # IPC is now mandatory; always enable it.
        self._debugger.enable_ipc_mode()

        # Create transport config for the factory
        transport_config = TransportConfig(
            transport=config.ipc.transport,
            pipe_name=config.ipc.pipe_name,
            host=config.ipc.host,
            port=config.ipc.port,
            path=config.ipc.path,
            use_binary=config.ipc.use_binary,
        )

        debug_args.extend(self._debugger.ipc.create_listener(config=transport_config))
        if transport_config.use_binary:
            debug_args.append("--ipc-binary")

        logger.info("Launching program: %s", self._debugger.program_path)
        logger.debug("Debug command: %s", " ".join(debug_args))

        # Start the subprocess in a worker thread to avoid blocking.
        if self._debugger.is_test_mode_enabled():
            threading.Thread(
                target=self._debugger._start_debuggee_process,
                args=(debug_args,),
                daemon=True,
            ).start()
        else:
            try:
                await self._debugger.loop.run_in_executor(
                    None, self._debugger._start_debuggee_process, debug_args
                )
            except Exception:
                await asyncio.to_thread(self._debugger._start_debuggee_process, debug_args)

        # Accept the IPC connection from the launcher (IPC is mandatory)
        if self._debugger.ipc.is_enabled:
            self._debugger.start_ipc_reader(accept=True)

        # Create the external process backend
        self._debugger.create_external_backend()

        self._debugger.program_running = True

        # Send event to tell the client the process has started
        process_event = {
            "name": Path(self._debugger.program_path).name,
            "systemProcessId": self._debugger.process.pid if self._debugger.process else None,
            "isLocalProcess": True,
            "startMethod": "launch",
        }
        await self._debugger.server.send_event("process", process_event)

        # If we need to stop on entry, we should wait for the stopped event
        if self._debugger.stop_on_entry and not self._debugger.no_debug:
            await self._debugger.await_stop_event()

    async def launch_in_process(self) -> None:
        """Initialize in-process debugging bridge and emit process event."""
        self._debugger.in_process = True
        inproc = InProcessDebugger()
        self._debugger.create_inprocess_bridge(
            inproc,
            on_stopped=self._debugger.handle_event_stopped,
            on_thread=self._debugger.handle_event_thread,
            on_exited=self._debugger.handle_event_exited,
            on_output=self._debugger.handle_inprocess_output,
        )
        self._debugger.create_inprocess_backend()

        # Mark running and emit process event for current interpreter
        self._debugger.program_running = True
        proc_event = {
            "name": Path(self._debugger.program_path or "").name,
            "systemProcessId": os.getpid(),
            "isLocalProcess": True,
            "startMethod": "launch",
        }
        await self._debugger.server.send_event("process", proc_event)

    async def attach(self, config: DapperConfig) -> None:
        """Attach to an already running debuggee via IPC using centralized configuration."""
        config.validate()

        # Create transport config for the factory
        transport_config = TransportConfig(
            transport=config.ipc.transport,
            pipe_name=config.ipc.pipe_name,
            host=config.ipc.host,
            port=config.ipc.port,
            path=config.ipc.path,
            use_binary=config.ipc.use_binary,
        )

        # Connect using the new transport configuration
        self._debugger.ipc.connect(transport_config)

        # Start reader thread (connection already established)
        self._debugger.start_ipc_reader(accept=False)

        # Create the external process backend
        self._debugger.create_external_backend()

        # Mark running and send a generic process event
        self._debugger.program_running = True
        await self._debugger.server.send_event(
            "process",
            {
                "name": self._debugger.program_path or "attached",
                "isLocalProcess": True,
                "startMethod": "attach",
            },
        )


class _PyDebuggerStateManager:
    """Handles breakpoint/state-inspection operations for ``PyDebugger``."""

    def __init__(self, debugger: PyDebugger):
        self._debugger = debugger

    async def set_breakpoints(
        self, source: SourceDict | str, breakpoints: list[SourceBreakpoint]
    ) -> list[BreakpointResponse]:
        """Set breakpoints for a source file."""
        path = source if isinstance(source, str) else source.get("path")
        if not path:
            return [
                BreakpointResponse(verified=False, message="Source path is required")
                for _ in breakpoints
            ]
        path = str(Path(path).resolve())

        spec_list, storage_list = self._debugger.process_breakpoints(breakpoints)
        self._debugger.breakpoints[path] = storage_list

        backend = self._debugger.get_active_backend()
        if backend is None:
            return [
                BreakpointResponse(
                    verified=bp.get("verified", False),
                    **{
                        k: v
                        for k, v in {
                            "message": bp.get("message"),
                            "line": bp.get("line"),
                            "condition": bp.get("condition"),
                            "hitCondition": bp.get("hitCondition"),
                            "logMessage": bp.get("logMessage"),
                        }.items()
                        if v is not None
                    },
                )
                for bp in storage_list
            ]

        inproc_backend = self._debugger.get_inprocess_backend()
        if inproc_backend is not None:
            backend_result = await inproc_backend.set_breakpoints(path, spec_list)
            return [
                BreakpointResponse(
                    verified=bp.get("verified", False),
                    **{
                        k: v
                        for k, v in {
                            "line": bp.get("line"),
                            "condition": bp.get("condition"),
                            "hitCondition": bp.get("hitCondition"),
                            "logMessage": bp.get("logMessage"),
                        }.items()
                        if v is not None
                    },
                )
                for bp in backend_result
            ]

        try:
            progress_id = f"setBreakpoints:{path}:{int(time.time() * 1000)}"
        except Exception:
            progress_id = f"setBreakpoints:{path}"

        self._debugger.emit_event(
            "progressStart", {"progressId": progress_id, "title": "Setting breakpoints"}
        )

        await backend.set_breakpoints(path, spec_list)
        self._debugger.forward_breakpoint_events(storage_list)

        self._debugger.emit_event("progressEnd", {"progressId": progress_id})

        return [
            BreakpointResponse(
                verified=bp.get("verified", False),
                **{
                    k: v
                    for k, v in {
                        "message": bp.get("message"),
                        "line": bp.get("line"),
                        "condition": bp.get("condition"),
                        "hitCondition": bp.get("hitCondition"),
                        "logMessage": bp.get("logMessage"),
                    }.items()
                    if v is not None
                },
            )
            for bp in storage_list
        ]

    async def get_stack_trace(
        self, thread_id: int, start_frame: int = 0, levels: int = 0
    ) -> StackTraceResponseBody:
        """Get stack trace for a thread."""
        backend = self._debugger.get_active_backend()
        if backend is not None:
            result = await backend.get_stack_trace(thread_id, start_frame, levels)
            if result.get("stackFrames"):
                return result

        stack_frames = []
        total_frames = 0

        with self._debugger.lock:
            if thread_id in self._debugger.current_stack_frames:
                frames = self._debugger.current_stack_frames[thread_id]
                total_frames = len(frames)

                if levels > 0:
                    end_frame = min(start_frame + levels, total_frames)
                    frames = frames[start_frame:end_frame]
                else:
                    frames = frames[start_frame:]

                stack_frames = frames

        return {"stackFrames": stack_frames, "totalFrames": total_frames}

    async def get_scopes(self, frame_id: int) -> list[Scope]:
        """Get variable scopes for a stack frame."""
        var_ref = self._debugger.next_var_ref
        self._debugger.next_var_ref += 1

        global_var_ref = self._debugger.next_var_ref
        self._debugger.next_var_ref += 1

        self._debugger.var_refs[var_ref] = (frame_id, "locals")
        self._debugger.var_refs[global_var_ref] = (frame_id, "globals")

        return [
            {
                "name": "Local",
                "variablesReference": var_ref,
                "expensive": False,
            },
            {
                "name": "Global",
                "variablesReference": global_var_ref,
                "expensive": True,
            },
        ]

    async def get_variables(
        self, variables_reference: int, filter_type: str = "", start: int = 0, count: int = 0
    ) -> list[Variable]:
        """Get variables for the given reference."""
        backend = self._debugger.get_active_backend()
        if backend is not None:
            result = await backend.get_variables(variables_reference, filter_type, start, count)
            if result:
                return result

        variables: list[Variable] = []
        with self._debugger.lock:
            if variables_reference in self._debugger.var_refs and isinstance(
                self._debugger.var_refs[variables_reference], list
            ):
                variables = cast("list[Variable]", self._debugger.var_refs[variables_reference])

        return variables

    async def set_variable(self, var_ref: int, name: str, value: str) -> SetVariableResponseBody:
        """Set a variable value in the specified scope."""
        with self._debugger.lock:
            if var_ref not in self._debugger.var_refs:
                msg = f"Invalid variable reference: {var_ref}"
                raise ValueError(msg)

            ref_info = self._debugger.var_refs[var_ref]

        scope_ref_tuple_len = 2
        if isinstance(ref_info, tuple) and len(ref_info) == scope_ref_tuple_len:
            backend = self._debugger.get_active_backend()
            if backend is not None:
                return await backend.set_variable(var_ref, name, value)
            return {"value": value, "type": "string", "variablesReference": 0}

        msg = f"Cannot set variable in reference type: {type(ref_info)}"
        raise ValueError(msg)

    async def evaluate(
        self, expression: str, frame_id: int | None = None, context: str | None = None
    ) -> EvaluateResponseBody:
        """Evaluate an expression in a specific context."""
        backend = self._debugger.get_active_backend()
        if backend is not None:
            return await backend.evaluate(expression, frame_id, context)
        return {
            "result": f"<evaluation of '{expression}' not available>",
            "type": "string",
            "variablesReference": 0,
        }


class _PyDebuggerRuntimeManager:
    """Handles IPC/process/backend runtime primitives for ``PyDebugger``."""

    def __init__(self, debugger: PyDebugger):
        self._debugger = debugger

    def start_ipc_reader(self, *, accept: bool) -> None:
        """Start IPC reader with message handling suitable for selected transport."""

        def _handle_ipc_message(message: dict[str, Any]) -> None:
            """Handle IPC message that may be already parsed (binary) or string."""
            if isinstance(message, dict):
                asyncio.run_coroutine_threadsafe(
                    self._debugger.handle_debug_message(message), self._debugger.loop
                )
            else:
                self._debugger._handle_debug_message(message)

        self._debugger.ipc.start_reader(_handle_ipc_message, accept=accept)

    def create_external_backend(self) -> None:
        """Create and register the external-process backend."""
        self._debugger._external_backend = ExternalProcessBackend(
            ipc=self._debugger.ipc,
            loop=self._debugger.loop,
            get_process_state=self._debugger._get_process_state,
            pending_commands=self._debugger._pending_commands,
            lock=self._debugger.lock,
            get_next_command_id=self._debugger._get_next_command_id,
        )

    def start_debuggee_process(self, debug_args: list[str]) -> None:
        """Start the debuggee process and forward lifecycle/output events."""
        try:
            self._debugger.process = subprocess.Popen(
                debug_args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

            stdout = cast("Any", self._debugger.process.stdout)
            stderr = cast("Any", self._debugger.process.stderr)
            threading.Thread(
                target=self.read_output,
                args=(stdout, "stdout"),
                daemon=True,
            ).start()
            threading.Thread(
                target=self.read_output,
                args=(stderr, "stderr"),
                daemon=True,
            ).start()

            exit_code = self._debugger.process.wait()

            if not self._debugger.is_terminated:
                self._debugger.is_terminated = True

            self._debugger.spawn_threadsafe(
                lambda c=exit_code: self._debugger._handle_program_exit(c)
            )
        except Exception:
            logger.exception("Error starting debuggee")
            self._debugger.is_terminated = True
            self._debugger.spawn_threadsafe(lambda: self._debugger._handle_program_exit(1))

    def read_output(self, stream, category: str) -> None:
        """Read output from debuggee stdout/stderr and forward to DAP output events."""
        try:
            while True:
                line = stream.readline()
                if not line:
                    break

                self._debugger._emit_event("output", {"category": category, "output": line})
        except Exception:
            logger.exception("Error reading %s", category)

    def create_inprocess_bridge(
        self,
        inproc: InProcessDebugger,
        *,
        on_stopped: Callable[[dict[str, Any]], None],
        on_thread: Callable[[dict[str, Any]], None],
        on_exited: Callable[[dict[str, Any]], None],
        on_output: Callable[[str, str], None],
    ) -> None:
        """Create and register the in-process bridge."""
        self._debugger._inproc_bridge = InProcessBridge(
            inproc,
            on_stopped=on_stopped,
            on_thread=on_thread,
            on_exited=on_exited,
            on_output=on_output,
        )

    def create_inprocess_backend(self) -> None:
        """Create and register the in-process backend."""
        if self._debugger._inproc_bridge is None:
            msg = "In-process bridge must be created before backend initialization"
            raise RuntimeError(msg)
        self._debugger._inproc_backend = InProcessBackend(self._debugger._inproc_bridge)


class _PyDebuggerExecutionManager:
    """Handles execution-control and lifecycle termination operations."""

    def __init__(self, debugger: PyDebugger):
        self._debugger = debugger

    async def continue_execution(self, thread_id: int) -> ContinueResponseBody:
        if not self._debugger.program_running or self._debugger.is_terminated:
            return {"allThreadsContinued": False}

        self._debugger.stopped_event.clear()

        with self._debugger.lock:
            if thread_id in self._debugger.threads:
                self._debugger.threads[thread_id].is_stopped = False

        if self._debugger._backend is not None:
            return await self._debugger._backend.continue_(thread_id)

        return {"allThreadsContinued": False}

    async def next(self, thread_id: int) -> None:
        if not self._debugger.program_running or self._debugger.is_terminated:
            return

        self._debugger.stopped_event.clear()

        if self._debugger._backend is not None:
            await self._debugger._backend.next_(thread_id)

    async def step_in(self, thread_id: int, target_id: int | None = None) -> None:
        if not self._debugger.program_running or self._debugger.is_terminated:
            return

        self._debugger.stopped_event.clear()

        if self._debugger._backend is not None:
            await self._debugger._backend.step_in(thread_id, target_id)

    async def step_out(self, thread_id: int) -> None:
        if not self._debugger.program_running or self._debugger.is_terminated:
            return

        self._debugger.stopped_event.clear()

        if self._debugger._backend is not None:
            await self._debugger._backend.step_out(thread_id)

    async def pause(self, thread_id: int) -> bool:
        if not self._debugger.program_running or self._debugger.is_terminated:
            return False

        if self._debugger._backend is not None:
            return await self._debugger._backend.pause(thread_id)
        return False

    async def get_threads(self) -> list[Thread]:
        threads: list[Thread] = []
        with self._debugger.lock:
            for thread_id, thread in self._debugger.threads.items():
                threads.append({"id": thread_id, "name": thread.name})
        return threads

    async def exception_info(self, thread_id: int) -> ExceptionInfoResponseBody:
        if self._debugger._backend is not None:
            return await self._debugger._backend.exception_info(thread_id)

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

    async def configuration_done_request(self) -> None:
        self._debugger.configuration_done.set()

        if self._debugger._backend is not None:
            await self._debugger._backend.configuration_done()

    async def disconnect(self, terminate_debuggee: bool = False) -> None:
        if self._debugger.program_running:
            if terminate_debuggee and self._debugger.process:
                try:
                    await self.terminate()
                    await asyncio.sleep(0.5)
                    if self._debugger.process.poll() is None:
                        self._debugger.process.kill()
                except Exception:
                    logger.exception("Error terminating debuggee")

            self._debugger.program_running = False

        await self._debugger.shutdown()

    async def terminate(self) -> None:
        if self._debugger._backend is not None:
            await self._debugger._backend.terminate()

        if self._debugger.in_process:
            try:
                self._debugger.is_terminated = True
                self._debugger.program_running = False
                await self._debugger.server.send_event("terminated")
            except Exception:
                logger.exception("in-process terminate failed")
            return

        if self._debugger.program_running and self._debugger.process:
            try:
                self._debugger.process.terminate()
                self._debugger.is_terminated = True
                self._debugger.program_running = False
            except Exception:
                logger.exception("Error terminating process")

    async def restart(self) -> None:
        try:
            await self._debugger.server.send_event("terminated", {"restart": True})
        except Exception:
            logger.exception("failed to send terminated(restart=true) event")

        try:
            if self._debugger.program_running and self._debugger.process:
                try:
                    self._debugger.process.terminate()
                except Exception:
                    logger.debug("process.terminate() failed during restart")
        except Exception:
            logger.debug("error during restart termination path")

        self._debugger.is_terminated = True
        self._debugger.program_running = False

        await self._debugger.shutdown()

    async def send_command_to_debuggee(self, command: str) -> None:
        if not self._debugger.process or self._debugger.is_terminated:
            msg = "No debuggee process"
            raise RuntimeError(msg)

        try:
            await asyncio.to_thread(
                lambda: (
                    self._debugger.process.stdin.write(f"{command}\n")
                    if self._debugger.process and self._debugger.process.stdin
                    else None
                ),
            )
        except Exception:
            logger.exception("Error sending command to debuggee")


class PyDebugger:
    """
    Main debugger class that integrates with Python's built-in debugging tools
    and communicates back to the DebugAdapterServer.
    """

    def __init__(
        self,
        server: DebugAdapterServer,
        loop: asyncio.AbstractEventLoop | None = None,
        enable_frame_eval: bool = False,
    ):
        """Initialize the PyDebugger.

        Args:
            server: The debug adapter server instance
            loop: Optional event loop to use. If not provided, gets the current event loop.
            enable_frame_eval: Whether to enable frame evaluation optimization.
        """
        self.server: DebugAdapterServer = server
        self.loop: asyncio.AbstractEventLoop
        self._owns_loop: bool
        self.loop, self._owns_loop = _acquire_event_loop(loop)

        if enable_frame_eval and integrate_py_debugger is not None:
            # Optional integration - resolved at import time to avoid dynamic
            # imports at runtime. The integration function may be None if the
            # frame-eval module is not available on this platform.
            integrate_py_debugger(self)

        # Core state
        self.threads: dict[int, PyDebuggerThread] = {}
        self.main_thread_id: int | None = None
        self.next_thread_id: int = 1
        self.next_var_ref: int = 1000
        self.var_refs: dict[int, object] = {}
        self.breakpoints: dict[str, list[BreakpointDict]] = {}
        # store function breakpoints as list[FunctionBreakpoint] at runtime for flexibility
        self.function_breakpoints: list[FunctionBreakpoint] = []
        # Exception breakpoint flags (two booleans for clarity)
        self.exception_breakpoints_uncaught: bool = False
        self.exception_breakpoints_raised: bool = False
        self.process: subprocess.Popen | None = None
        self.debugger_thread: threading.Thread | None = None
        self.is_terminated: bool = False
        self.program_running: bool = False
        self.stop_on_entry: bool = False
        self.no_debug: bool = False
        self.current_stack_frames: dict[int, list] = {}
        self._source_introspection = LoadedSourceTracker()
        self.thread_exit_events: dict[int, object] = {}
        self.lock: threading.RLock = threading.RLock()
        # Use thread-safe Event objects for synchronization. Tests and
        # asyncio code may await these — the helper `_await_event` will
        # bridge the synchronous wait to an awaitable when needed.
        self.stopped_event = threading.Event()
        self.configuration_done = threading.Event()

        # Keep references to background tasks so they don't get GC'd
        self._bg_tasks: set[asyncio.Task] = set()

        # Test mode flag (used by tests to start debuggee in a real thread)
        self._test_mode: bool = False

        # Command tracking for request/response
        self._next_command_id: int = 1
        self._pending_commands: dict[int, asyncio.Future] = {}
        # In-process debugging support (optional/opt-in)
        self.in_process: bool = False
        self._inproc_bridge: InProcessBridge | None = None

        # Backend for debugging operations (set in launch/attach)
        self._inproc_backend: InProcessBackend | None = None
        self._external_backend: ExternalProcessBackend | None = None

        # Optional IPC transport context (initialized lazily in launch)
        self._use_ipc: bool = False
        self.ipc: IPCManager = IPCManager()

        # Data breakpoint containers
        self._data_watches: dict[str, dict[str, Any]] = {}  # dataId -> watch metadata
        self._frame_watches: dict[int, list[str]] = {}  # frameId -> list of dataIds
        # Optional current frame reference for runtime helpers and tests
        # May hold a real frame (types.FrameType) or a frame-like object used in tests
        self.current_frame: Any | None = None

        # Event routing/decomposition
        self._event_router = _PyDebuggerEventRouter(self)
        # Launch/attach lifecycle decomposition
        self._lifecycle_manager = _PyDebuggerLifecycleManager(self)
        # Breakpoint/state-inspection decomposition
        self._state_manager = _PyDebuggerStateManager(self)
        # Runtime/process/IPC decomposition
        self._runtime_manager = _PyDebuggerRuntimeManager(self)
        # Execution-control/lifecycle decomposition
        self._execution_manager = _PyDebuggerExecutionManager(self)

    @property
    def program_path(self) -> str | None:
        """Get the program path being debugged."""
        return self._source_introspection.program_path

    @program_path.setter
    def program_path(self, value: str | None) -> None:
        """Set the program path being debugged."""
        self._source_introspection.program_path = value

    @property
    def _backend(self) -> InProcessBackend | ExternalProcessBackend | None:
        """Get the active debugger backend."""
        if self._inproc_backend is not None:
            return self._inproc_backend
        return self._external_backend

    def _get_next_command_id(self) -> int:
        """Get the next command ID and increment the counter."""
        cmd_id = self._next_command_id
        self._next_command_id += 1
        return cmd_id

    def _get_process_state(self) -> tuple[subprocess.Popen | None, bool]:
        """Get the current process state for the external backend."""
        return self.process, self.is_terminated

    def spawn_threadsafe(self, callback: Callable[[], Any]) -> None:
        """Schedule a (possibly coroutine-producing) callback on the debugger loop.

        The callback is always executed on the event loop thread. If it returns
        an awaitable, we wrap it in a Task and track it for shutdown. This
        avoids creating coroutines on worker threads which can cause 'never
        awaited' warnings.
        """

        def _run_on_loop() -> None:
            try:
                result = callback()
            except Exception:
                logger.exception("Error in spawn_threadsafe callback")
                return
            if inspect.isawaitable(result):
                try:
                    task = asyncio.ensure_future(result)
                except Exception:
                    logger.exception("error creating task for awaitable")
                else:
                    self._bg_tasks.add(task)
                    task.add_done_callback(self._bg_tasks.discard)

        try:
            self.loop.call_soon_threadsafe(_run_on_loop)
        except Exception:  # pragma: no cover - defensive
            logger.debug("spawn_threadsafe drop (loop closed)")
            return

    async def _await_event(self, ev: object) -> None:
        """Await a blocking or patched event.wait() in an asyncio-friendly way.

        This helper inspects the event.wait attribute and either runs the
        blocking wait in an executor (threading.Event) or directly awaits a
        patched awaitable-returning stub.
        """
        wait = getattr(ev, "wait", None)
        if wait is None:
            return

        try:
            bound_self = getattr(wait, "__self__", None)
            if isinstance(bound_self, threading.Event):
                await self.loop.run_in_executor(None, wait)
                return
        except Exception:
            logger.debug("Event introspection failed, trying fallback", exc_info=True)

        try:
            res = wait()
        except Exception:
            await self.loop.run_in_executor(None, wait)
            return

        if inspect.isawaitable(res):
            await res
            return

        return

    def data_breakpoint_info(self, *, name: str, frame_id: int) -> DataBreakpointInfoResponseBody:
        """Return minimal data breakpoint info for a variable in a frame."""
        data_id = f"frame:{frame_id}:var:{name}"
        body: DataBreakpointInfoResponseBody = {
            "dataId": data_id,
            "description": f"Variable '{name}' in frame {frame_id}",
            "accessTypes": ["write"],
            "canPersist": False,
        }

        # Try to enrich with type/value if we can access a matching frame
        try:
            # Prefer the current debugger frame if available (self is the debugger)
            frame = getattr(self, "current_frame", None) or getattr(self, "botframe", None)
            # If this debugger is acting as a bridge to an in-process backend,
            # fall back to the inproc debugger's current_frame if present.
            if frame is None and getattr(self, "_inproc_bridge", None) is not None:
                inproc_dbg = getattr(self._inproc_bridge, "debugger", None)
                frame = getattr(inproc_dbg, "current_frame", None) or getattr(
                    inproc_dbg, "botframe", None
                )
            if frame is not None:
                locals_map = getattr(frame, "f_locals", None)
                if locals_map is not None and name in locals_map:
                    val = locals_map[name]
                    body["type"] = type(val).__name__
                    try:
                        s = repr(val)
                        if len(s) > MAX_VALUE_REPR_LEN:
                            s = s[: MAX_VALUE_REPR_LEN - 3] + "..."
                        body["value"] = s
                    except Exception:
                        logger.debug("repr() failed for variable %r", name, exc_info=True)
        except Exception:
            # Not fatal — return minimal information
            logger.debug("Variable lookup failed for %r", name, exc_info=True)

        return body

    def set_data_breakpoints(self, breakpoints: list[dict[str, Any]]) -> list[Breakpoint]:
        """Register a set of data breakpoints (bookkeeping only)."""
        # Clear existing watches (DAP semantics: full replace)
        self._data_watches.clear()
        self._frame_watches.clear()

        results: list[Breakpoint] = []
        frame_id_parts_expected = 4  # pattern: frame:{id}:var:{name}
        watch_names: set[str] = set()
        watch_meta: list[tuple[str, dict[str, Any]]] = []
        for bp in breakpoints:
            data_id = bp.get("dataId")
            if not data_id or not isinstance(data_id, str):
                results.append({"verified": False, "message": "Missing dataId"})
                continue
            # Parse frame id for indexing (best-effort extraction)
            frame_id = None
            parts = data_id.split(":")
            # Expect pattern frame:{fid}:var:{name}
            if len(parts) >= frame_id_parts_expected and parts[0] == "frame" and parts[2] == "var":
                try:
                    frame_id = int(parts[1])
                except ValueError:
                    frame_id = None
                # capture variable name portion for runtime detection bridging
                if len(parts) >= frame_id_parts_expected:
                    var_name = parts[3]
                    watch_names.add(var_name)
            meta = {
                "dataId": data_id,
                "accessType": bp.get("accessType", "write"),
                "condition": bp.get("condition"),
                "hitCondition": bp.get("hitCondition"),
                "hit": 0,
                "verified": True,
            }
            self._data_watches[data_id] = meta
            # store meta for bridging keyed by variable name
            if "var:" in data_id:
                try:
                    watch_meta.append((parts[3], meta))
                except Exception:  # pragma: no cover - defensive
                    pass
            if frame_id is not None:
                self._frame_watches.setdefault(frame_id, []).append(data_id)
            results.append({"verified": True})
        # Bridge to in-process debugger (if active) so it can detect changes by name
        try:
            inproc = getattr(self, "_inproc", None)
            if inproc is not None and hasattr(inproc, "debugger"):
                dbg = getattr(inproc, "debugger", None)
                register = getattr(dbg, "register_data_watches", None)
                if callable(register):
                    register(sorted(watch_names), watch_meta)
        except Exception:  # pragma: no cover - defensive
            logger.debug("Failed bridging data watches to BDB", exc_info=True)
        return results

    def _emit_event(self, event_name: str, payload: dict[str, Any]) -> None:
        """Schedule an event to be sent to the DAP client.

        This is the preferred way to send events from synchronous callbacks
        and background threads. The event is scheduled on the event loop
        via spawn_threadsafe.
        """
        self.spawn_threadsafe(lambda: self.server.send_event(event_name, payload))

    async def launch(self, config: DapperConfig) -> None:
        """Launch a new Python program for debugging using centralized configuration."""
        await self._lifecycle_manager.launch(config)

    def _handle_inproc_output(self, category: str, output: str) -> None:
        """Forward output events from in-process debugger to the server."""
        try:
            self._emit_event("output", {"category": category, "output": output})
        except Exception:
            logger.exception("error in on_output callback")

    async def attach(self, config: DapperConfig) -> None:
        """Attach to an already running debuggee via IPC using centralized configuration."""
        await self._lifecycle_manager.attach(config)

    def is_test_mode_enabled(self) -> bool:
        """Return whether test mode is enabled for launch orchestration."""
        return getattr(self, "_test_mode", False)

    def start_ipc_reader(self, *, accept: bool) -> None:
        """Start IPC reader with message handling suitable for selected transport."""
        self._runtime_manager.start_ipc_reader(accept=accept)

    def create_external_backend(self) -> None:
        """Create and register the external-process backend."""
        self._runtime_manager.create_external_backend()

    def get_active_backend(self) -> InProcessBackend | ExternalProcessBackend | None:
        """Return the currently active backend (in-process preferred)."""
        return self._backend

    def get_inprocess_backend(self) -> InProcessBackend | None:
        """Return in-process backend when active."""
        return self._inproc_backend

    def process_breakpoints(
        self, breakpoints: Sequence[SourceBreakpoint]
    ) -> tuple[list[SourceBreakpoint], list[BreakpointDict]]:
        """Public wrapper for breakpoint normalization logic."""
        return self._process_breakpoints(breakpoints)

    def forward_breakpoint_events(self, storage_list: list[BreakpointDict]) -> None:
        """Public wrapper for breakpoint-change event forwarding."""
        self._forward_breakpoint_events(storage_list)

    def start_debuggee_process(self, debug_args: list[str]) -> None:
        """Public wrapper to start the debuggee process for lifecycle components."""
        self._runtime_manager.start_debuggee_process(debug_args)

    def _start_debuggee_process(self, debug_args: list[str]) -> None:
        """Compatibility alias for tests that patch the legacy private method."""
        self.start_debuggee_process(debug_args)

    def schedule_program_exit(self, exit_code: int) -> None:
        """Schedule process-exit handling on the debugger event loop."""
        self.spawn_threadsafe(lambda c=exit_code: self._handle_program_exit(c))

    async def await_stop_event(self) -> None:
        """Await the debugger stopped-event in an asyncio-friendly way."""
        await self._await_event(self.stopped_event)

    def enable_ipc_mode(self) -> None:
        """Enable IPC mode for launch lifecycle orchestration."""
        self._use_ipc = True

    def has_pending_command(self, command_id: int) -> bool:
        """Return whether a command id has a pending response future."""
        with self.lock:
            return command_id in self._pending_commands

    def pop_pending_command(self, command_id: int) -> asyncio.Future[dict[str, Any]] | None:
        """Pop and return pending command future for a command id."""
        with self.lock:
            return self._pending_commands.pop(command_id, None)

    def resolve_pending_response(
        self, future: asyncio.Future[dict[str, Any]], data: dict[str, Any]
    ) -> None:
        """Resolve a pending response on the debugger loop."""
        if future.done():
            return

        def _set_result() -> None:
            if not future.done():
                future.set_result(data)

        try:
            if asyncio.get_running_loop() is self.loop:
                _set_result()
                return
        except RuntimeError:
            pass

        try:
            self.loop.call_soon_threadsafe(_set_result)
        except Exception:
            logger.debug("failed to schedule resolution on debugger loop")

    def emit_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Public event emission wrapper for extracted components."""
        self._emit_event(event_type, payload)

    def handle_event_stopped(self, data: dict[str, Any]) -> None:
        """Public wrapper for stopped-event handling."""
        self._event_router.handle_event_stopped(data)

    def handle_event_thread(self, data: dict[str, Any]) -> None:
        """Public wrapper for thread-event handling."""
        self._event_router.handle_event_thread(data)

    def handle_event_exited(self, data: dict[str, Any]) -> None:
        """Public wrapper for exited-event handling."""
        self._event_router.handle_event_exited(data)

    def handle_inprocess_output(self, category: str, output: str) -> None:
        """Public wrapper for in-process output forwarding."""
        self._handle_inproc_output(category, output)

    def create_inprocess_bridge(
        self,
        inproc: InProcessDebugger,
        *,
        on_stopped: Callable[[dict[str, Any]], None],
        on_thread: Callable[[dict[str, Any]], None],
        on_exited: Callable[[dict[str, Any]], None],
        on_output: Callable[[str, str], None],
    ) -> None:
        """Create and register the in-process bridge."""
        self._runtime_manager.create_inprocess_bridge(
            inproc,
            on_stopped=on_stopped,
            on_thread=on_thread,
            on_exited=on_exited,
            on_output=on_output,
        )

    def create_inprocess_backend(self) -> None:
        """Create and register the in-process backend."""
        self._runtime_manager.create_inprocess_backend()

    def _handle_debug_message(self, message: str) -> None:
        """Handle a debug protocol message from the debuggee."""
        self._event_router.handle_debug_message(message)

    async def _handle_program_exit(self, exit_code: int) -> None:
        """Handle the debuggee program exit"""
        if self.program_running:
            self.program_running = False
            self.is_terminated = True

            await self.server.send_event("exited", {"exitCode": exit_code})
            await self.server.send_event("terminated")

    async def set_breakpoints(
        self, source: SourceDict | str, breakpoints: list[SourceBreakpoint]
    ) -> list[BreakpointResponse]:
        """Set breakpoints for a source file."""
        return await self._state_manager.set_breakpoints(source, breakpoints)

    def _process_breakpoints(
        self, breakpoints: Sequence[SourceBreakpoint]
    ) -> tuple[list[SourceBreakpoint], list[BreakpointDict]]:
        """Process breakpoints into spec and storage lists.

        Args:
            breakpoints: List of breakpoint specifications

        Returns:
            Tuple of (spec_list, storage_list)
        """
        spec_list: list[SourceBreakpoint] = []
        storage_list: list[BreakpointDict] = []

        for bp in breakpoints:
            line_val = int(bp.get("line", 0))

            # Extract optional fields
            optional_fields = {}
            for field in ["condition", "hitCondition", "logMessage"]:
                value = bp.get(field)
                if value is not None:
                    optional_fields[field] = str(value) if field != "logMessage" else value

            # Create spec entry for debugger API
            spec_list.append(SourceBreakpoint(line=line_val, **optional_fields))

            # Create storage entry for response
            storage_list.append(BreakpointDict(line=line_val, verified=True, **optional_fields))

        return spec_list, storage_list

    def _forward_breakpoint_events(self, storage_list: list[BreakpointDict]) -> None:
        """Forward breakpoint-changed events to clients."""
        try:
            for bp in storage_list:
                self._emit_event(
                    "breakpoint",
                    {
                        "reason": "changed",
                        "breakpoint": {
                            "verified": bp.get("verified", True),
                            "line": bp.get("line"),
                        },
                    },
                )
        except Exception:
            logger.debug("Failed to forward breakpoint events")

    async def set_function_breakpoints(
        self, breakpoints: list[FunctionBreakpoint]
    ) -> list[FunctionBreakpoint]:
        """Set breakpoints for functions"""
        spec_funcs: list[FunctionBreakpoint] = []
        storage_funcs: list[FunctionBreakpoint] = []
        for bp in breakpoints:
            name = str(bp.get("name", ""))
            spec_entry: FunctionBreakpoint = {"name": name}
            cond = bp.get("condition")
            if cond is not None:
                spec_entry["condition"] = str(cond)
            hc = bp.get("hitCondition")
            if hc is not None:
                spec_entry["hitCondition"] = str(hc)
            spec_funcs.append(spec_entry)

            storage_entry: FunctionBreakpoint = {"name": name, "verified": True}
            if cond is not None:
                storage_entry["condition"] = str(cond)
            if hc is not None:
                storage_entry["hitCondition"] = str(hc)
            storage_funcs.append(storage_entry)

        # Store runtime representation (with verified flag) for IPC and state
        self.function_breakpoints = storage_funcs

        if self._backend is not None:
            return await self._backend.set_function_breakpoints(spec_funcs)
        return [{"verified": bp.get("verified", True)} for bp in storage_funcs]

    async def set_exception_breakpoints(
        self,
        filters: list[str],
        filter_options: list[ExceptionFilterOptions] | None = None,
        exception_options: list[ExceptionOptions] | None = None,
    ) -> list[Breakpoint]:
        """Set exception breakpoints.

        Accepts the DAP-shaped arguments: `filters`, optional `filterOptions`,
        and optional `exceptionOptions`. For in-process debuggers we currently
        only apply the boolean flags derived from `filters`; the optional
        options are forwarded to an external debuggee process when present.
        """
        # Update runtime flags derived from the simple `filters` list.
        self.exception_breakpoints_raised = "raised" in filters
        self.exception_breakpoints_uncaught = "uncaught" in filters

        if self._backend is not None:
            return await self._backend.set_exception_breakpoints(
                filters,
                filter_options,
                exception_options,  # type: ignore[arg-type]
            )

        # Best-effort: assume the breakpoints were set when no backend available
        return [{"verified": True} for _ in filters]

    async def continue_execution(self, thread_id: int) -> ContinueResponseBody:
        """Continue execution of the specified thread"""
        return await self._execution_manager.continue_execution(thread_id)

    async def next(self, thread_id: int) -> None:
        """Step over to the next line"""
        await self._execution_manager.next(thread_id)

    async def step_in(self, thread_id: int, target_id: int | None = None) -> None:
        """Step into a function.

        Args:
            thread_id: The thread to step in.
            target_id: Optional target ID for stepping into a specific call target.
        """
        await self._execution_manager.step_in(thread_id, target_id)

    async def step_out(self, thread_id: int) -> None:
        """Step out of the current function"""
        await self._execution_manager.step_out(thread_id)

    async def pause(self, thread_id: int) -> bool:
        """Pause execution of the specified thread"""
        return await self._execution_manager.pause(thread_id)

    async def get_threads(self) -> list[Thread]:
        """Get all threads"""
        return await self._execution_manager.get_threads()

    async def get_loaded_sources(self) -> list[Source]:
        """Get all loaded source files."""
        return self._source_introspection.get_loaded_sources()

    async def get_modules(self) -> list[Module]:
        """Get all loaded Python modules."""
        return self._source_introspection.get_modules()

    async def get_stack_trace(
        self, thread_id: int, start_frame: int = 0, levels: int = 0
    ) -> StackTraceResponseBody:
        """Get stack trace for a thread."""
        return await self._state_manager.get_stack_trace(thread_id, start_frame, levels)

    async def get_scopes(self, frame_id: int) -> list[Scope]:
        """Get variable scopes for a stack frame."""
        return await self._state_manager.get_scopes(frame_id)

    async def get_variables(
        self, variables_reference: int, filter_type: str = "", start: int = 0, count: int = 0
    ) -> list[Variable]:
        """Get variables for the given reference."""
        return await self._state_manager.get_variables(
            variables_reference, filter_type, start, count
        )

    async def set_variable(
        self,
        var_ref: int,
        name: str,
        value: str,
    ) -> SetVariableResponseBody:
        """Set a variable value in the specified scope."""
        return await self._state_manager.set_variable(var_ref, name, value)

    async def evaluate(
        self, expression: str, frame_id: int | None = None, context: str | None = None
    ) -> EvaluateResponseBody:
        """Evaluate an expression in a specific context."""
        return await self._state_manager.evaluate(expression, frame_id, context)

    async def completions(
        self,
        text: str,
        column: int,
        frame_id: int | None = None,
        line: int = 1,
    ) -> CompletionsResponseBody:
        """Get expression completions for the debug console.

        Provides intelligent auto-completions based on runtime frame context
        when stopped at a breakpoint. Falls back to static analysis when
        runtime introspection is not available.

        Args:
            text: The input text to complete (may be multi-line)
            column: Cursor position within the text (1-based, UTF-16 code units)
            frame_id: Stack frame for scope context (None = global scope)
            line: Line number within text (1-based, default 1)

        Returns:
            CompletionsResponseBody with list of completion targets
        """
        if self._backend is not None:
            result = await self._backend.completions(text, column, frame_id, line)
            return cast("CompletionsResponseBody", result)
        return {"targets": []}

    async def exception_info(self, thread_id: int) -> ExceptionInfoResponseBody:
        """Get exception information for a thread"""
        return await self._execution_manager.exception_info(thread_id)

    async def get_exception_info(self, thread_id: int) -> ExceptionInfoResponseBody:
        """Get exception information for a thread (convenience method)"""
        return await self.exception_info(thread_id)

    async def configuration_done_request(self) -> None:
        """Signal that configuration is done and debugging can start"""
        await self._execution_manager.configuration_done_request()

    async def disconnect(self, terminate_debuggee: bool = False) -> None:
        """Disconnect from the debuggee"""
        await self._execution_manager.disconnect(terminate_debuggee)

    async def terminate(self) -> None:
        """Terminate the debuggee"""
        await self._execution_manager.terminate()

    async def restart(self) -> None:
        """Request a session restart by signaling terminated(restart=true)."""
        await self._execution_manager.restart()

    async def evaluate_expression(
        self, expression: str, frame_id: int, context: str = "hover"
    ) -> EvaluateResponseBody:
        """Evaluate an expression (alias for evaluate)"""
        return await self.evaluate(expression, frame_id, context)

    async def handle_debug_message(self, message) -> None:
        """Handle a debug protocol message (alias for _handle_debug_message)"""
        if isinstance(message, dict):
            message = json.dumps(message)
        self._handle_debug_message(message)

    async def handle_program_exit(self, exit_code: int) -> None:
        """Handle program exit (alias for _handle_program_exit)"""
        await self._handle_program_exit(exit_code)

    async def send_command_to_debuggee(self, command: str) -> None:
        """Send a raw command string to the debuggee"""
        await self._execution_manager.send_command_to_debuggee(command)

    async def shutdown(self) -> None:
        """Shut down the debugger and clean up resources."""
        # Cancel background tasks
        for task in list(self._bg_tasks):
            task.cancel()

        # Fail all pending command futures
        with self.lock:
            pending = dict(self._pending_commands)
            self._pending_commands.clear()

        shutdown_error = RuntimeError("Debugger shutdown")
        for cid, fut in pending.items():
            if fut.done():
                continue
            try:
                fut.set_exception(shutdown_error)
            except Exception:
                # Future may be on a different loop; try thread-safe scheduling
                try:
                    self.loop.call_soon_threadsafe(
                        lambda f=fut: f.done() or f.set_exception(shutdown_error)
                    )
                except Exception:
                    logger.debug("failed to fail pending future %s", cid)

        # Clean up event loop if we own it
        if self.loop:
            with contextlib.suppress(Exception):
                await self.loop.shutdown_asyncgens()

            if getattr(self, "_owns_loop", False):
                with contextlib.suppress(Exception):
                    if self.loop.is_running():
                        self.loop.stop()
                with contextlib.suppress(Exception):
                    if not self.loop.is_closed():
                        self.loop.close()

        # Close process stdio streams
        proc = self.process
        if proc is not None:
            for stream_name in ("stdin", "stdout", "stderr"):
                stream = getattr(proc, stream_name, None)
                if stream is not None:
                    stream.close()

            self.ipc.cleanup()

        # Clear state
        self.var_refs.clear()
        self.threads.clear()
        self.breakpoints.clear()
        self.function_breakpoints.clear()
        self.current_stack_frames.clear()
        self.program_running = False
        self.is_terminated = True


if TYPE_CHECKING:
    from dapper.adapter.request_handlers import RequestHandler
    from dapper.adapter.server_core import DebugAdapterServer

__all__ = ["DebugAdapterServer", "PyDebugger", "RequestHandler"]


def __getattr__(name: str):
    if name == "DebugAdapterServer":
        return importlib.import_module("dapper.adapter.server_core").DebugAdapterServer
    if name == "RequestHandler":
        return importlib.import_module("dapper.adapter.request_handlers").RequestHandler
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
