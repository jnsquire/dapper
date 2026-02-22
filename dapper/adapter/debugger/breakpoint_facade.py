from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from dapper.adapter.types import BreakpointDict
from dapper.protocol.structures import SourceBreakpoint
from dapper.shared.command_handlers import MAX_VALUE_REPR_LEN

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dapper.adapter.debugger.py_debugger import PyDebugger
    from dapper.protocol.capabilities import ExceptionFilterOptions
    from dapper.protocol.capabilities import ExceptionOptions
    from dapper.protocol.data_breakpoints import DataBreakpointInfoResponseBody
    from dapper.protocol.requests import FunctionBreakpoint
    from dapper.protocol.structures import Breakpoint

logger = logging.getLogger(__name__)


class _PyDebuggerBreakpointFacade:
    """Breakpoint/data-breakpoint logic extracted from PyDebugger."""

    def __init__(self, debugger: PyDebugger):
        self._debugger = debugger

    def data_breakpoint_info(self, *, name: str, frame_id: int) -> DataBreakpointInfoResponseBody:
        """Return minimal data breakpoint info for a variable in a frame."""
        data_id = f"frame:{frame_id}:var:{name}"
        body: DataBreakpointInfoResponseBody = {
            "dataId": data_id,
            "description": f"Variable '{name}' in frame {frame_id}",
            "accessTypes": ["write"],
            "canPersist": False,
        }

        try:
            frame = getattr(self._debugger, "current_frame", None) or getattr(
                self._debugger,
                "botframe",
                None,
            )
            if frame is None and getattr(self._debugger, "_inproc_bridge", None) is not None:
                bridge = getattr(self._debugger, "_inproc_bridge", None)
                inproc_dbg = getattr(bridge, "debugger", None)
                frame = getattr(inproc_dbg, "current_frame", None) or getattr(
                    inproc_dbg,
                    "botframe",
                    None,
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
            logger.debug("Variable lookup failed for %r", name, exc_info=True)

        return body

    def set_data_breakpoints(self, breakpoints: list[dict[str, Any]]) -> list[Breakpoint]:
        """Register a set of data breakpoints (bookkeeping only)."""
        self._debugger.clear_data_watch_containers()

        results: list[Breakpoint] = []
        frame_id_parts_expected = 4
        watch_names: set[str] = set()
        watch_meta: list[tuple[str, dict[str, Any]]] = []
        for bp in breakpoints:
            data_id = bp.get("dataId")
            if not data_id or not isinstance(data_id, str):
                results.append({"verified": False, "message": "Missing dataId"})
                continue
            frame_id = None
            parts = data_id.split(":")
            if len(parts) >= frame_id_parts_expected and parts[0] == "frame" and parts[2] == "var":
                try:
                    frame_id = int(parts[1])
                except ValueError:
                    frame_id = None
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
            self._debugger.set_data_watch(data_id, meta)
            if "var:" in data_id:
                try:
                    watch_meta.append((parts[3], meta))
                except Exception:  # pragma: no cover - defensive
                    pass
            if frame_id is not None:
                self._debugger.add_frame_watch(frame_id, data_id)
            results.append({"verified": True})
        try:
            inproc = getattr(self._debugger, "_inproc", None)
            if inproc is not None and hasattr(inproc, "debugger"):
                dbg = getattr(inproc, "debugger", None)
                register = getattr(dbg, "register_data_watches", None)
                if callable(register):
                    register(sorted(watch_names), watch_meta)
        except Exception:  # pragma: no cover - defensive
            logger.debug("Failed bridging data watches to BDB", exc_info=True)
        return results

    def process_breakpoints(
        self,
        breakpoints: Sequence[SourceBreakpoint],
    ) -> tuple[list[SourceBreakpoint], list[BreakpointDict]]:
        """Process breakpoints into spec and storage lists."""
        spec_list: list[SourceBreakpoint] = []
        storage_list: list[BreakpointDict] = []

        for bp in breakpoints:
            line_val = int(bp.get("line", 0))

            optional_fields = {}
            for field in ["condition", "hitCondition", "logMessage"]:
                value = bp.get(field)
                if value is not None:
                    optional_fields[field] = str(value) if field != "logMessage" else value

            spec_list.append(SourceBreakpoint(line=line_val, **optional_fields))
            storage_list.append(BreakpointDict(line=line_val, verified=True, **optional_fields))

        return spec_list, storage_list

    def forward_breakpoint_events(self, storage_list: list[BreakpointDict]) -> None:
        """Forward breakpoint-changed events to clients."""
        try:
            for bp in storage_list:
                self._debugger.emit_event(
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
        self,
        breakpoints: list[FunctionBreakpoint],
    ) -> list[FunctionBreakpoint]:
        """Set breakpoints for functions."""
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

        self._debugger.function_breakpoints = storage_funcs

        backend = self._debugger.get_active_backend()
        if backend is not None:
            return await backend.set_function_breakpoints(spec_funcs)
        return [{"verified": bp.get("verified", True)} for bp in storage_funcs]

    async def set_exception_breakpoints(
        self,
        filters: list[str],
        filter_options: list[ExceptionFilterOptions] | None = None,
        exception_options: list[ExceptionOptions] | None = None,
    ) -> list[Breakpoint]:
        """Set exception breakpoints."""
        self._debugger.exception_breakpoints_raised = "raised" in filters
        self._debugger.exception_breakpoints_uncaught = "uncaught" in filters

        backend = self._debugger.get_active_backend()
        if backend is not None:
            return await backend.set_exception_breakpoints(
                filters,
                cast("list[dict[str, Any]] | None", filter_options),
                exception_options,  # type: ignore[arg-type]
            )

        return [{"verified": True} for _ in filters]
