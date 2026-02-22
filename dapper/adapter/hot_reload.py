"""Hot reload runtime service for in-process debug sessions."""

from __future__ import annotations

import ctypes
import importlib
import linecache
from pathlib import Path
import time
import types
from typing import TYPE_CHECKING
from typing import Any

try:
    from dapper._frame_eval.cache_manager import invalidate_breakpoints as _invalidate_breakpoints
except Exception:  # pragma: no cover - optional frame-eval integration
    _invalidate_breakpoints = None

try:
    from dapper._frame_eval.selective_tracer import update_breakpoints as _update_breakpoints
except Exception:  # pragma: no cover - optional frame-eval integration
    _update_breakpoints = None

if TYPE_CHECKING:
    from dapper.adapter.debugger.py_debugger import PyDebugger
    from dapper.protocol.requests import HotReloadOptions
    from dapper.protocol.requests import HotReloadResponseBody
    from dapper.protocol.structures import SourceBreakpoint


class HotReloadService:
    """Executes reload-and-continue operations for a paused debugger."""

    def __init__(self, debugger: PyDebugger) -> None:
        self._debugger = debugger

    async def reload_module(
        self,
        path: str,
        options: HotReloadOptions | None = None,
    ) -> HotReloadResponseBody:
        start = time.perf_counter()
        warnings: list[str] = []

        resolved = Path(path).resolve(strict=True)
        if resolved.suffix.lower() not in (".py", ".pyw"):
            msg = f"Not a Python source file: {resolved}"
            raise ValueError(msg)

        backend = self._debugger.get_inprocess_backend()
        if backend is None:
            msg = "Hot reload currently requires an in-process debug session"
            raise RuntimeError(msg)

        found = self._debugger._source_introspection.resolve_module_for_path(str(resolved))  # noqa: SLF001
        if found is None:
            msg = f"Module not loaded: {resolved}"
            raise ValueError(msg)
        module_name, module = found
        old_functions = self._collect_module_functions(module)

        normalized_options: HotReloadOptions = options or {}
        invalidate_pyc = bool(normalized_options.get("invalidatePycache", True))

        importlib.invalidate_caches()
        linecache.checkcache(str(resolved))

        if invalidate_pyc:
            warnings.extend(self._delete_stale_pyc(resolved))

        reloaded = importlib.reload(module)
        linecache.checkcache(str(resolved))

        rebind_map = self._build_rebind_map(
            old_functions, self._collect_module_functions(reloaded)
        )
        rebound_frames = self._rebind_stack_functions(rebind_map, warnings)

        self._invalidate_frame_eval_cache(str(resolved), warnings)

        breakpoint_lines = await self._reapply_breakpoints(str(resolved))

        if breakpoint_lines:
            self._update_frame_eval_breakpoints(str(resolved), breakpoint_lines, warnings)

        source = self._debugger._source_introspection.make_source(  # noqa: SLF001
            resolved,
            origin=f"module:{module_name}",
            name=resolved.name,
        )
        self._debugger.emit_event("loadedSource", {"reason": "changed", "source": source})

        duration_ms = (time.perf_counter() - start) * 1000.0
        event_payload = {
            "module": module_name,
            "path": str(resolved),
            "reboundFrames": rebound_frames,
            "updatedFrameCodes": 0,
            "patchedInstances": 0,
            "warnings": warnings,
            "durationMs": duration_ms,
        }
        self._debugger.emit_event("dapper/hotReloadResult", event_payload)

        body: HotReloadResponseBody = {
            "reloadedModule": getattr(reloaded, "__name__", module_name),
            "reloadedPath": str(resolved),
            "reboundFrames": rebound_frames,
            "updatedFrameCodes": 0,
            "patchedInstances": 0,
            "warnings": warnings,
        }
        return body

    def _collect_module_functions(self, module: object) -> dict[str, Any]:
        module_dict = getattr(module, "__dict__", {})
        if not isinstance(module_dict, dict):
            return {}

        return {
            name: value
            for name, value in module_dict.items()
            if callable(value) and hasattr(value, "__code__")
        }

    def _build_rebind_map(
        self,
        old_functions: dict[str, Any],
        new_functions: dict[str, Any],
    ) -> dict[int, Any]:
        mapping: dict[int, Any] = {}
        for name, old_function in old_functions.items():
            new_function = new_functions.get(name)
            if new_function is None or not hasattr(new_function, "__code__"):
                continue
            mapping[id(old_function)] = new_function
            old_code = getattr(old_function, "__code__", None)
            if old_code is not None:
                mapping[id(old_code)] = new_function
        return mapping

    def _rebind_stack_functions(self, rebind_map: dict[int, Any], warnings: list[str]) -> int:
        if not rebind_map:
            return 0

        rebound_frames = 0
        for frame in self._iter_live_frames():
            locals_map = getattr(frame, "f_locals", None)
            if not isinstance(locals_map, dict):
                continue

            changed = False
            for local_name, local_value in list(locals_map.items()):
                replacement = self._replacement_for_value(local_value, rebind_map)
                if replacement is None:
                    continue
                try:
                    locals_map[local_name] = replacement
                except Exception as exc:
                    warnings.append(
                        f"Failed to rebind local '{local_name}' in frame {getattr(frame, 'f_code', None)}: {exc!s}",
                    )
                    continue
                changed = True

            if changed:
                rebound_frames += 1
                self._flush_frame_locals(frame, warnings)

        return rebound_frames

    def _replacement_for_value(self, value: Any, rebind_map: dict[int, Any]) -> Any | None:
        if isinstance(value, types.FunctionType):
            by_function = rebind_map.get(id(value))
            if by_function is not None:
                return by_function
            return rebind_map.get(id(value.__code__))

        if isinstance(value, types.MethodType):
            by_function = rebind_map.get(id(value.__func__))
            if by_function is not None:
                return types.MethodType(by_function, value.__self__)
            by_code = rebind_map.get(id(value.__func__.__code__))
            if by_code is not None:
                return types.MethodType(by_code, value.__self__)

        return None

    def _iter_live_frames(self) -> list[Any]:
        backend = self._debugger.get_inprocess_backend()
        if backend is None:
            return []

        bridge = getattr(backend, "bridge", None)
        inproc = getattr(bridge, "debugger", None)
        bdb = getattr(inproc, "debugger", None)
        if bdb is None:
            return []

        frames: list[Any] = []
        try:
            frame_map = getattr(bdb.thread_tracker, "frame_id_to_frame", {})
            frames.extend(frame_map.values())
        except Exception:
            pass

        current_frame = getattr(getattr(bdb, "stepping_controller", None), "current_frame", None)
        if current_frame is not None:
            frames.append(current_frame)

        unique_frames: list[Any] = []
        seen: set[int] = set()
        for frame in frames:
            frame_id = id(frame)
            if frame_id in seen:
                continue
            seen.add(frame_id)
            unique_frames.append(frame)
        return unique_frames

    def _flush_frame_locals(self, frame: Any, warnings: list[str]) -> None:
        if not hasattr(types, "FrameType") or not isinstance(frame, types.FrameType):
            return

        try:
            locals_to_fast = ctypes.pythonapi.PyFrame_LocalsToFast
            locals_to_fast.argtypes = [ctypes.py_object, ctypes.c_int]
            locals_to_fast.restype = None
            locals_to_fast(frame, 1)
        except Exception as exc:
            warnings.append(f"Failed to flush frame locals for live frame: {exc!s}")

    def _delete_stale_pyc(self, source_path: Path) -> list[str]:
        warnings: list[str] = []
        pycache_dir = source_path.parent / "__pycache__"
        if not pycache_dir.is_dir():
            return warnings

        stem = source_path.stem
        for pyc in pycache_dir.glob(f"{stem}*.pyc"):
            error = self._try_unlink(pyc)
            if error is not None:
                warnings.append(f"Failed to delete stale .pyc: {pyc} ({error})")

        return warnings

    def _try_unlink(self, pyc: Path) -> str | None:
        try:
            pyc.unlink()
        except Exception as exc:
            return str(exc)
        else:
            return None

    def _invalidate_frame_eval_cache(self, path: str, warnings: list[str]) -> None:
        try:
            if _invalidate_breakpoints is not None:
                _invalidate_breakpoints(path)
        except Exception as exc:
            warnings.append(f"Frame-eval cache invalidation failed: {exc!s}")

    async def _reapply_breakpoints(self, path: str) -> set[int]:
        per_path = self._debugger.breakpoint_manager._line_meta_by_path.get(path, {})  # noqa: SLF001

        breakpoints: list[SourceBreakpoint] = []
        lines: set[int] = set()
        for line, meta in sorted(per_path.items()):
            bp: SourceBreakpoint = {"line": int(line)}
            condition = meta.get("condition")
            hit_condition = meta.get("hitCondition")
            log_message = meta.get("logMessage")
            if condition:
                bp["condition"] = condition
            if hit_condition:
                bp["hitCondition"] = hit_condition
            if log_message:
                bp["logMessage"] = log_message
            breakpoints.append(bp)
            lines.add(int(line))

        await self._debugger.set_breakpoints(path, breakpoints)
        return lines

    def _update_frame_eval_breakpoints(
        self,
        path: str,
        lines: set[int],
        warnings: list[str],
    ) -> None:
        try:
            if _update_breakpoints is not None:
                _update_breakpoints(path, lines)
        except Exception as exc:
            warnings.append(f"Frame-eval breakpoint refresh failed: {exc!s}")
