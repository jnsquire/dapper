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
from typing import NoReturn
from typing import Protocol
from typing import cast

from dapper._frame_eval.telemetry import telemetry

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
    from dapper.adapter.external_backend import ExternalProcessBackend
    from dapper.protocol.requests import HotReloadOptions
    from dapper.protocol.requests import HotReloadResponseBody
    from dapper.protocol.structures import SourceBreakpoint


ModuleType = types.ModuleType
FunctionType = types.FunctionType
MethodType = types.MethodType
CodeType = types.CodeType
RebindMap = dict[int, FunctionType]


class _SupportsFrameCodeUpdate(Protocol):
    f_code: CodeType


class HotReloadService:
    """Executes reload-and-continue operations for a paused debugger."""

    def __init__(self, debugger: PyDebugger) -> None:
        self._debugger = debugger

    async def reload_module(
        self,
        path: str,
        options: HotReloadOptions | None = None,
    ) -> HotReloadResponseBody:
        """Reload *path* in the debuggee (in-process or external) and return results.

        Routes to :meth:`_reload_inprocess` when an in-process backend is
        active, or to :meth:`_reload_via_external_backend` otherwise.
        """
        if self._debugger.get_inprocess_backend() is not None:
            return await self._reload_inprocess(path, options)
        return await self._reload_via_external_backend(path, options)

    async def _reload_inprocess(
        self,
        path: str,
        options: HotReloadOptions | None = None,
    ) -> HotReloadResponseBody:
        start = time.perf_counter()
        warnings: list[str] = []
        module_name = "<unresolved>"
        resolved_path = str(Path(path))
        body: HotReloadResponseBody

        try:
            resolved, module_name, module = self._resolve_reload_target(path)
            resolved_path = str(resolved)
            reloaded, rebound_frames, updated_frame_codes = await self._perform_reload(
                resolved,
                module_name,
                module,
                options,
                warnings,
            )

            duration_ms = (time.perf_counter() - start) * 1000.0
            self._emit_reload_events(
                resolved,
                module_name,
                rebound_frames,
                updated_frame_codes,
                warnings,
                duration_ms,
            )
            self._record_hot_reload_success(
                module_name=module_name,
                path=str(resolved),
                rebound_frames=rebound_frames,
                updated_frame_codes=updated_frame_codes,
                warning_count=len(warnings),
                duration_ms=duration_ms,
            )

            body = {
                "reloadedModule": getattr(reloaded, "__name__", module_name),
                "reloadedPath": str(resolved),
                "reboundFrames": rebound_frames,
                "updatedFrameCodes": updated_frame_codes,
                "patchedInstances": 0,
                "warnings": warnings,
            }
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000.0
            self._record_hot_reload_failure(
                module_name=module_name,
                path=resolved_path,
                error_type=type(exc).__name__,
                error_message=str(exc),
                duration_ms=duration_ms,
            )
            raise

        return body

    async def _reload_via_external_backend(
        self,
        path: str,
        options: HotReloadOptions | None = None,
    ) -> HotReloadResponseBody:
        """Reload *path* by delegating to the external debuggee process via IPC.

        The adapter validates the source path locally (fast-fail for obvious
        errors), then sends a ``hotReload`` command to the debuggee.  The
        debuggee performs the actual ``importlib.reload`` and frame rebinding
        via :func:`~dapper.shared.reload_helpers.perform_reload` and returns a
        structured result body.

        After the round-trip the adapter performs its own housekeeping:
        variable-cache invalidation, frame-eval cache invalidation, breakpoint
        reapplication, and event/telemetry emission.

        Returns:
            A :class:`~dapper.protocol.requests.HotReloadResponseBody`
            populated from the debuggee's response.

        Raises:
            RuntimeError: If no external-process backend is available or the
                debuggee signals a failure.
            ValueError: If *path* is not a reloadable Python source.
            OSError: If the file does not exist on the adapter side.
        """
        start = time.perf_counter()
        resolved_path = str(Path(path))
        reloaded_module: str = "<unresolved>"

        try:
            resolved = Path(path).resolve(strict=True)
            resolved_path = str(resolved)
            self._assert_reloadable_source(resolved)

            backend: ExternalProcessBackend | None = self._debugger.get_external_backend()
            if backend is None:
                self._raise_runtime_error(
                    "No external-process backend is available for hot reload"
                )

            raw: dict[str, Any] = await backend._execute_command(  # noqa: SLF001
                "hot_reload",
                {"path": str(resolved), "options": options or {}},
            )

            reloaded_module = str(raw.get("reloadedModule", "<unknown>"))
            rebound_frames = int(raw.get("reboundFrames", 0))
            updated_frame_codes = int(raw.get("updatedFrameCodes", 0))
            _raw_warnings = raw.get("warnings")
            remote_warnings: list[str] = (
                [str(w) for w in _raw_warnings] if isinstance(_raw_warnings, list) else []
            )

            # Adapter-side housekeeping (same bookkeeping as the in-process path).
            adapter_warnings: list[str] = []
            self._invalidate_variable_caches(adapter_warnings)
            self._invalidate_frame_eval_cache(str(resolved), adapter_warnings)
            breakpoint_lines = await self._reapply_breakpoints(str(resolved))
            if breakpoint_lines:
                self._update_frame_eval_breakpoints(
                    str(resolved), breakpoint_lines, adapter_warnings
                )

            all_warnings = remote_warnings + adapter_warnings
            duration_ms = (time.perf_counter() - start) * 1000.0

            self._emit_reload_events(
                resolved,
                reloaded_module,
                rebound_frames,
                updated_frame_codes,
                all_warnings,
                duration_ms,
            )
            self._record_hot_reload_success(
                module_name=reloaded_module,
                path=str(resolved),
                rebound_frames=rebound_frames,
                updated_frame_codes=updated_frame_codes,
                warning_count=len(all_warnings),
                duration_ms=duration_ms,
            )

            body: HotReloadResponseBody = {
                "reloadedModule": reloaded_module,
                "reloadedPath": str(resolved),
                "reboundFrames": rebound_frames,
                "updatedFrameCodes": updated_frame_codes,
                "patchedInstances": 0,
                "warnings": all_warnings,
            }
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000.0
            self._record_hot_reload_failure(
                module_name=reloaded_module,
                path=resolved_path,
                error_type=type(exc).__name__,
                error_message=str(exc),
                duration_ms=duration_ms,
            )
            raise

        return body

    def _resolve_reload_target(self, path: str) -> tuple[Path, str, ModuleType]:
        resolved = Path(path).resolve(strict=True)
        self._assert_reloadable_source(resolved)

        found = self._debugger._source_introspection.resolve_module_for_path(str(resolved))  # noqa: SLF001
        if found is None:
            self._raise_value_error(f"Module not loaded: {resolved}")

        module_name, module = found
        return resolved, module_name, module

    def _assert_reloadable_source(self, resolved: Path) -> None:
        extension_suffixes = self._extension_suffixes()
        if extension_suffixes and any(
            str(resolved).endswith(suffix) for suffix in extension_suffixes
        ):
            self._raise_value_error("Cannot reload C extension module")

        if resolved.suffix.lower() not in (".py", ".pyw"):
            self._raise_value_error(f"Not a Python source file: {resolved}")

    @staticmethod
    def _raise_value_error(message: str) -> NoReturn:
        raise ValueError(message)

    @staticmethod
    def _raise_runtime_error(message: str) -> NoReturn:
        raise RuntimeError(message)

    async def _perform_reload(
        self,
        resolved: Path,
        module_name: str,
        module: ModuleType,
        options: HotReloadOptions | None,
        warnings: list[str],
    ) -> tuple[ModuleType, int, int]:
        old_functions = self._collect_module_functions(module)

        normalized_options: HotReloadOptions = options or {}
        invalidate_pyc = bool(normalized_options.get("invalidatePycache", True))
        update_frame_code = bool(normalized_options.get("updateFrameCode", True))

        importlib.invalidate_caches()
        linecache.checkcache(str(resolved))

        if invalidate_pyc:
            warnings.extend(self._delete_stale_pyc(resolved))

        reloaded = importlib.reload(module)
        linecache.checkcache(str(resolved))

        rebind_map = self._build_rebind_map(
            old_functions, self._collect_module_functions(reloaded)
        )
        rebound_frames, updated_frame_codes = self._rebind_stack_functions(
            rebind_map,
            warnings,
            module_name=module_name,
            update_frame_code=update_frame_code,
        )
        self._invalidate_variable_caches(warnings)

        self._invalidate_frame_eval_cache(str(resolved), warnings)

        breakpoint_lines = await self._reapply_breakpoints(str(resolved))
        if breakpoint_lines:
            self._update_frame_eval_breakpoints(str(resolved), breakpoint_lines, warnings)

        return reloaded, rebound_frames, updated_frame_codes

    def _emit_reload_events(
        self,
        resolved: Path,
        module_name: str,
        rebound_frames: int,
        updated_frame_codes: int,
        warnings: list[str],
        duration_ms: float,
    ) -> None:
        source = self._debugger._source_introspection.make_source(  # noqa: SLF001
            resolved,
            origin=f"module:{module_name}",
            name=resolved.name,
        )
        self._debugger.emit_event("loadedSource", {"reason": "changed", "source": source})

        event_payload = {
            "module": module_name,
            "path": str(resolved),
            "reboundFrames": rebound_frames,
            "updatedFrameCodes": updated_frame_codes,
            "patchedInstances": 0,
            "warnings": warnings,
            "durationMs": duration_ms,
        }
        self._debugger.emit_event("dapper/hotReloadResult", event_payload)

    def _record_hot_reload_success(
        self,
        *,
        module_name: str,
        path: str,
        rebound_frames: int,
        updated_frame_codes: int,
        warning_count: int,
        duration_ms: float,
    ) -> None:
        try:
            telemetry.record_hot_reload_succeeded(
                module=module_name,
                path=path,
                rebound_frames=rebound_frames,
                updated_frame_codes=updated_frame_codes,
                warning_count=warning_count,
                duration_ms=duration_ms,
            )
        except Exception:
            pass

    def _record_hot_reload_failure(
        self,
        *,
        module_name: str,
        path: str,
        error_type: str,
        error_message: str,
        duration_ms: float,
    ) -> None:
        try:
            telemetry.record_hot_reload_failed(
                module=module_name,
                path=path,
                error_type=error_type,
                error_message=error_message,
                duration_ms=duration_ms,
            )
        except Exception:
            pass

    def _extension_suffixes(self) -> tuple[str, ...]:
        """Return importlib extension suffixes with backwards-compatible fallback."""
        default_suffixes: tuple[str, ...] = (".so", ".pyd", ".dll", ".dylib")
        machinery = getattr(importlib, "machinery", None)
        if machinery is None:
            return default_suffixes

        suffixes = getattr(machinery, "EXTENSION_SUFFIXES", None)
        if isinstance(suffixes, (list, tuple)):
            ordered: dict[str, None] = dict.fromkeys(default_suffixes)
            for suffix in suffixes:
                if suffix:
                    ordered[str(suffix)] = None
            return tuple(ordered)
        return default_suffixes

    def _collect_module_functions(self, module: ModuleType) -> dict[str, FunctionType]:
        module_dict = getattr(module, "__dict__", {})
        if not isinstance(module_dict, dict):
            return {}

        return {
            name: value for name, value in module_dict.items() if isinstance(value, FunctionType)
        }

    def _build_rebind_map(
        self,
        old_functions: dict[str, FunctionType],
        new_functions: dict[str, FunctionType],
    ) -> RebindMap:
        mapping: RebindMap = {}
        for name, old_function in old_functions.items():
            new_function = new_functions.get(name)
            if new_function is None:
                continue
            mapping[id(old_function)] = new_function
            old_code = getattr(old_function, "__code__", None)
            if old_code is not None:
                mapping[id(old_code)] = new_function
        return mapping

    def _rebind_stack_functions(
        self,
        rebind_map: RebindMap,
        warnings: list[str],
        *,
        module_name: str,
        update_frame_code: bool,
    ) -> tuple[int, int]:
        if not rebind_map:
            return 0, 0

        rebound_frames = 0
        updated_frame_codes = 0
        closure_warnings: set[str] = set()
        for frame in self._iter_live_frames():
            if self._maybe_update_frame_code(frame, rebind_map, warnings, update_frame_code):
                updated_frame_codes += 1

            locals_map = getattr(frame, "f_locals", None)
            if not isinstance(locals_map, dict):
                continue

            changed = False
            for local_name, local_value in list(locals_map.items()):
                if self._warn_if_closure(local_value, module_name, warnings, closure_warnings):
                    continue

                replacement = self._replacement_for_value(local_value, rebind_map)
                if replacement is None:
                    continue
                try:
                    locals_map[local_name] = replacement
                except Exception as exc:
                    msg = (
                        f"Failed to rebind local '{local_name}' in frame "
                        f"{getattr(frame, 'f_code', None)}: {exc!s}"
                    )
                    warnings.append(msg)
                    continue
                changed = True

            if changed:
                rebound_frames += 1
                self._flush_frame_locals(frame, warnings)

        return rebound_frames, updated_frame_codes

    def _maybe_update_frame_code(
        self,
        frame: object,
        rebind_map: RebindMap,
        warnings: list[str],
        update_frame_code: bool,
    ) -> bool:
        if not update_frame_code:
            return False

        current_code = getattr(frame, "f_code", None)
        replacement_function = (
            rebind_map.get(id(current_code)) if current_code is not None else None
        )
        new_code = (
            getattr(replacement_function, "__code__", None)
            if replacement_function is not None
            else None
        )
        if (
            not isinstance(current_code, CodeType)
            or replacement_function is None
            or not isinstance(new_code, CodeType)
        ):
            return False

        if self._is_closure_function(replacement_function):
            code_name = getattr(current_code, "co_name", "<unknown>")
            warnings.append(
                "Closure function "
                f"{code_name}() skipped: captured cell variables cannot be safely "
                "rebound"
            )
            return False

        compatible, reason = self._is_code_compatible(current_code, new_code)
        if not compatible:
            code_name = getattr(current_code, "co_name", "<unknown>")
            warnings.append(f"frame.f_code update skipped for {code_name}(): {reason}")
            return False

        updated = False
        try:
            frame_with_code = cast("_SupportsFrameCodeUpdate", frame)
            frame_with_code.f_code = new_code
        except Exception as exc:
            warnings.append(f"Failed to update frame.f_code: {exc!s}")
        else:
            updated = True

        return updated

    def _warn_if_closure(
        self,
        value: object,
        module_name: str,
        warnings: list[str],
        warned: set[str],
    ) -> bool:
        function = self._extract_function(value)
        if function is None:
            return False
        if getattr(function, "__module__", None) != module_name:
            return False
        if not self._is_closure_function(function):
            return False

        function_name = getattr(function, "__name__", "<closure>")
        if function_name not in warned:
            warned.add(function_name)
            warnings.append(
                "Closure function "
                f"{function_name}() skipped: captured cell variables cannot be safely "
                "rebound"
            )
        return True

    def _extract_function(self, value: object) -> FunctionType | None:
        if isinstance(value, FunctionType):
            return value
        if isinstance(value, MethodType):
            return value.__func__
        return None

    def _is_closure_function(self, value: FunctionType) -> bool:
        return bool(getattr(value, "__closure__", None))

    def _is_code_compatible(self, old_code: CodeType, new_code: CodeType) -> tuple[bool, str]:
        for attr in ("co_argcount", "co_posonlyargcount", "co_kwonlyargcount", "co_nlocals"):
            old_value = getattr(old_code, attr, None)
            new_value = getattr(new_code, attr, None)
            if old_value != new_value:
                return False, f"{attr} changed from {old_value} to {new_value}"

        old_varnames = tuple(getattr(old_code, "co_varnames", ()))
        new_varnames = tuple(getattr(new_code, "co_varnames", ()))
        if len(old_varnames) != len(new_varnames):
            return (
                False,
                f"co_varnames length changed from {len(old_varnames)} to {len(new_varnames)}",
            )

        old_freevars = tuple(getattr(old_code, "co_freevars", ()))
        new_freevars = tuple(getattr(new_code, "co_freevars", ()))
        if old_freevars != new_freevars:
            return False, "co_freevars changed"

        old_cellvars = tuple(getattr(old_code, "co_cellvars", ()))
        new_cellvars = tuple(getattr(new_code, "co_cellvars", ()))
        if old_cellvars != new_cellvars:
            return False, "co_cellvars changed"

        return True, ""

    def _replacement_for_value(self, value: object, rebind_map: RebindMap) -> object | None:
        if isinstance(value, FunctionType):
            by_function = rebind_map.get(id(value))
            if by_function is not None:
                return by_function
            return rebind_map.get(id(value.__code__))

        if isinstance(value, MethodType):
            by_function = rebind_map.get(id(value.__func__))
            if by_function is not None:
                return MethodType(by_function, value.__self__)
            by_code = rebind_map.get(id(value.__func__.__code__))
            if by_code is not None:
                return MethodType(by_code, value.__self__)

        return None

    def _iter_live_frames(self) -> list[object]:
        return list(self._debugger.iter_live_frames())

    def _flush_frame_locals(self, frame: object, warnings: list[str]) -> None:
        if not hasattr(types, "FrameType") or not isinstance(frame, types.FrameType):
            return

        try:
            locals_to_fast = ctypes.pythonapi.PyFrame_LocalsToFast
            locals_to_fast.argtypes = [ctypes.py_object, ctypes.c_int]
            locals_to_fast.restype = None
            locals_to_fast(frame, 1)
        except Exception as exc:
            warnings.append(f"Failed to flush frame locals for live frame: {exc!s}")

    def _invalidate_variable_caches(self, warnings: list[str]) -> None:
        try:
            self._debugger.variable_manager.clear()
        except Exception as exc:
            warnings.append(f"Failed to clear variable references: {exc!s}")

        try:
            self._debugger.session_facade.current_stack_frames.clear()
        except Exception as exc:
            warnings.append(f"Failed to clear cached stack frames: {exc!s}")

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
