from __future__ import annotations

from pathlib import Path
import time
from typing import TYPE_CHECKING
from typing import cast

from dapper.adapter.types import BreakpointResponse

if TYPE_CHECKING:
    from dapper.adapter.debugger.py_debugger import PyDebugger
    from dapper.adapter.types import SourceDict
    from dapper.protocol.debugger_protocol import Variable
    from dapper.protocol.requests import EvaluateResponseBody
    from dapper.protocol.requests import SetVariableResponseBody
    from dapper.protocol.requests import StackTraceResponseBody
    from dapper.protocol.structures import Scope
    from dapper.protocol.structures import SourceBreakpoint


class _PyDebuggerStateManager:
    """Handles breakpoint/state-inspection operations for ``PyDebugger``."""

    def __init__(self, debugger: PyDebugger):
        self._debugger = debugger

    async def set_breakpoints(
        self,
        source: SourceDict | str,
        breakpoints: list[SourceBreakpoint],
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
        self._debugger.breakpoint_manager.clear_line_meta_for_file(path)
        for bp in storage_list:
            line = bp.get("line")
            if line is None:
                continue

            condition = bp.get("condition")
            hit_condition = bp.get("hitCondition")
            log_message = bp.get("logMessage")

            extra_meta = {
                k: v
                for k, v in bp.items()
                if k not in ("line", "condition", "hitCondition", "logMessage")
            }

            self._debugger.breakpoint_manager.record_line_breakpoint(
                path,
                int(line),
                condition=condition,
                hit_condition=hit_condition,
                log_message=log_message,
                **extra_meta,
            )

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
            "progressStart",
            {"progressId": progress_id, "title": "Setting breakpoints"},
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
        self,
        thread_id: int,
        start_frame: int = 0,
        levels: int = 0,
    ) -> StackTraceResponseBody:
        """Get stack trace for a thread."""
        # Check whether this is an asyncio task pseudo-thread managed by the
        # task registry.  If so, serve the pre-built coroutine frames directly
        # without forwarding to the backend (which has no knowledge of them).
        task_registry = self._debugger.task_registry
        if task_registry is not None and task_registry.is_task_thread_id(thread_id):
            frames = task_registry.get_task_frames(thread_id, start_frame, levels)
            total = task_registry.get_task_frame_count(thread_id)
            return {"stackFrames": frames, "totalFrames": total}

        backend = self._debugger.get_active_backend()
        if backend is not None:
            result = await backend.get_stack_trace(thread_id, start_frame, levels)
            if result.get("stackFrames"):
                return result

        stack_frames = []
        total_frames = 0

        with self._debugger.lock:
            frames = self._debugger.session_facade.get_cached_stack_frames(thread_id)
            if frames is not None:
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
        # Use VariableManager to allocate scope references
        var_ref = self._debugger.variable_manager.allocate_scope_ref(frame_id, "locals")
        global_var_ref = self._debugger.variable_manager.allocate_scope_ref(frame_id, "globals")

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
        self,
        variables_reference: int,
        filter_type: str = "",
        start: int = 0,
        count: int = 0,
    ) -> list[Variable]:
        """Get variables for the given reference."""
        backend = self._debugger.get_active_backend()
        if backend is not None:
            result = await backend.get_variables(variables_reference, filter_type, start, count)
            if result:
                return result

        variables: list[Variable] = []
        with self._debugger.lock:
            var_entry = self._debugger.variable_manager.get_ref(variables_reference)
            object_tuple_len = 2
            if (
                isinstance(var_entry, tuple)
                and len(var_entry) == object_tuple_len
                and var_entry[0] == "object"
            ):
                var_entry = var_entry[1]
            if isinstance(var_entry, list):
                variables = cast("list[Variable]", var_entry)

        return variables

    async def set_variable(self, var_ref: int, name: str, value: str) -> SetVariableResponseBody:
        """Set a variable value in the specified scope."""
        with self._debugger.lock:
            if not self._debugger.variable_manager.has_ref(var_ref):
                msg = f"Invalid variable reference: {var_ref}"
                raise ValueError(msg)

            ref_info = self._debugger.variable_manager.get_ref(var_ref)

        scope_ref_tuple_len = 2
        if (
            isinstance(ref_info, tuple)
            and len(ref_info) == scope_ref_tuple_len
            and isinstance(ref_info[0], int)
            and ref_info[1] in ("locals", "globals")
        ):
            backend = self._debugger.get_active_backend()
            if backend is not None:
                return await backend.set_variable(var_ref, name, value)
            return {"value": value, "type": "string", "variablesReference": 0}

        msg = f"Cannot set variable in reference type: {type(ref_info)}"
        raise ValueError(msg)

    async def evaluate(
        self,
        expression: str,
        frame_id: int | None = None,
        context: str | None = None,
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
