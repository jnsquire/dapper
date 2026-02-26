"""Shared hot-reload utilities used by both in-process and external-process paths.

All helpers in this module are pure Python; they do not import from the
dapper adapter or debugger layers so they can safely run inside the debuggee
process (launched by debug_launcher.py) as well as inside the adapter process
(via HotReloadService).

The main entry point is :func:`perform_reload`, which orchestrates the full
sequence: source validation, module resolution, .pyc removal,
``importlib.reload``, function/code rebinding across live frames, and optional
frame-eval cache invalidation.
"""

from __future__ import annotations

import ctypes
import importlib
import importlib.machinery
import linecache
from pathlib import Path
import sys
import types
from typing import TYPE_CHECKING
from typing import TypedDict
from typing import cast

if TYPE_CHECKING:
    from collections.abc import Callable

    from dapper.protocol.requests import HotReloadOptions

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

FunctionType = types.FunctionType
MethodType = types.MethodType
CodeType = types.CodeType
ModuleType = types.ModuleType

# Mapping from ``id(old_function_or_code_object)`` to the new FunctionType
# replacement produced after ``importlib.reload``.
RebindMap = dict[int, FunctionType]

_PYTHON_SOURCE_SUFFIXES: frozenset[str] = frozenset((".py", ".pyw"))


# ---------------------------------------------------------------------------
# Public TypedDicts
# ---------------------------------------------------------------------------


class PerformReloadResult(TypedDict):
    """Return value of :func:`perform_reload`.

    All fields are always present (unlike :class:`HotReloadResponseBody` which
    is ``total=False`` because it is also used as an optional partial structure
    in the protocol layer).
    """

    reloadedModule: str
    reboundFrames: int
    updatedFrameCodes: int
    warnings: list[str]


class RebindResult(TypedDict):
    """Intermediate result from :func:`rebind_stack_frames`."""

    reboundFrames: int
    updatedFrameCodes: int
    warnings: list[str]


# ---------------------------------------------------------------------------
# C-extension suffix helpers
# ---------------------------------------------------------------------------


def _extension_suffixes() -> tuple[str, ...]:
    """Return known C-extension file suffixes in a stable order."""
    defaults: tuple[str, ...] = (".so", ".pyd", ".dll", ".dylib")
    raw = getattr(importlib.machinery, "EXTENSION_SUFFIXES", None)
    if not isinstance(raw, (list, tuple)):
        return defaults
    ordered: dict[str, None] = dict.fromkeys(defaults)
    for s in raw:
        if s:
            ordered[str(s)] = None
    return tuple(ordered)


# ---------------------------------------------------------------------------
# Source validation
# ---------------------------------------------------------------------------


def check_reloadable_source(resolved: Path) -> None:
    """Raise :exc:`ValueError` if *resolved* cannot be reloaded.

    Rejects C extension modules (``.so``, ``.pyd``, etc.) and any file whose
    suffix is not ``.py`` or ``.pyw``.
    """
    ext_sfx = _extension_suffixes()
    if ext_sfx and any(str(resolved).endswith(sfx) for sfx in ext_sfx):
        raise ValueError("Cannot reload C extension module")
    if resolved.suffix.lower() not in _PYTHON_SOURCE_SUFFIXES:
        raise ValueError(f"Not a Python source file: {resolved}")


# ---------------------------------------------------------------------------
# Module resolution (debuggee-side: uses sys.modules)
# ---------------------------------------------------------------------------


def resolve_module_for_path(path: str) -> tuple[str, ModuleType]:
    """Find the :class:`types.ModuleType` in :data:`sys.modules` whose
    ``__file__`` resolves to *path*.

    Both ``.py`` and ``.pyc`` ``__file__`` values are handled; the ``.pyc``
    suffix is stripped before comparing.

    Raises:
        ValueError: If no matching module is found.
    """
    resolved = str(Path(path).resolve())
    for name, mod in list(sys.modules.items()):
        mod_file = getattr(mod, "__file__", None)
        if not isinstance(mod_file, str):
            continue
        candidate = mod_file
        if candidate.endswith(".pyc"):
            candidate = candidate[:-1]
        try:
            if str(Path(candidate).resolve()) == resolved:
                return name, mod
        except (OSError, ValueError):
            continue
    raise ValueError(f"Module not loaded: {path}")


# ---------------------------------------------------------------------------
# Function / code collection
# ---------------------------------------------------------------------------


def collect_module_functions(module: ModuleType) -> dict[str, FunctionType]:
    """Return every :class:`types.FunctionType` in ``module.__dict__``."""
    d = getattr(module, "__dict__", {})
    if not isinstance(d, dict):
        return {}
    return {k: v for k, v in d.items() if isinstance(v, FunctionType)}


def build_rebind_map(
    old_functions: dict[str, FunctionType],
    new_functions: dict[str, FunctionType],
) -> RebindMap:
    """Build a mapping from old function/code identities to new functions.

    Both ``id(old_fn)`` and ``id(old_fn.__code__)`` are stored so that callers
    can look up a replacement using either identity.
    """
    mapping: RebindMap = {}
    for name, old_fn in old_functions.items():
        new_fn = new_functions.get(name)
        if new_fn is None:
            continue
        mapping[id(old_fn)] = new_fn
        old_code = getattr(old_fn, "__code__", None)
        if old_code is not None:
            mapping[id(old_code)] = new_fn
    return mapping


# ---------------------------------------------------------------------------
# Code-object compatibility gate
# ---------------------------------------------------------------------------


def is_code_compatible(old_code: CodeType, new_code: CodeType) -> tuple[bool, str]:
    """Return ``(True, "")`` when *old_code* and *new_code* are compatible for
    an in-place ``frame.f_code`` swap, otherwise ``(False, reason_string)``.

    Compatibility is checked by comparing argcounts, co_varnames length,
    co_freevars, and co_cellvars.  Any mismatch would corrupt the frame's
    local variable layout.
    """
    for attr in ("co_argcount", "co_posonlyargcount", "co_kwonlyargcount", "co_nlocals"):
        old_val = getattr(old_code, attr, None)
        new_val = getattr(new_code, attr, None)
        if old_val != new_val:
            return False, f"{attr} changed from {old_val!r} to {new_val!r}"

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


# ---------------------------------------------------------------------------
# Frame rebinding internals
# ---------------------------------------------------------------------------


def _is_closure(fn: FunctionType) -> bool:
    """Return True when *fn* captures cell variables via ``__closure__``."""
    return bool(getattr(fn, "__closure__", None))


def _replacement_for_value(value: object, rebind_map: RebindMap) -> object | None:
    """Return the rebind-map replacement for *value*, or ``None`` if none exists."""
    if isinstance(value, FunctionType):
        by_fn = rebind_map.get(id(value))
        if by_fn is not None:
            return by_fn
        return rebind_map.get(id(value.__code__))

    if isinstance(value, MethodType):
        by_fn = rebind_map.get(id(value.__func__))
        if by_fn is not None:
            return MethodType(by_fn, value.__self__)
        by_code = rebind_map.get(id(value.__func__.__code__))
        if by_code is not None:
            return MethodType(by_code, value.__self__)

    return None


def _flush_frame_locals(frame: types.FrameType, warnings: list[str]) -> None:
    """Push the Python-level ``f_locals`` dict back into C fast-locals."""
    try:
        fn = ctypes.pythonapi.PyFrame_LocalsToFast
        fn.argtypes = [ctypes.py_object, ctypes.c_int]
        fn.restype = None
        fn(frame, 1)
    except Exception as exc:  # pragma: no cover – ctypes rarely fails
        warnings.append(f"Failed to flush frame locals: {exc!s}")


def _maybe_update_frame_code(
    frame: types.FrameType,
    rebind_map: RebindMap,
    warnings: list[str],
    *,
    update_frame_code: bool,
) -> bool:
    """Attempt to swap ``frame.f_code`` to the new :class:`types.CodeType`.

    Returns ``True`` when the code object was successfully replaced.
    """
    if not update_frame_code:
        return False

    current_code: CodeType | None = getattr(frame, "f_code", None)
    replacement_fn = (
        rebind_map.get(id(current_code)) if current_code is not None else None
    )
    new_code: CodeType | None = (
        getattr(replacement_fn, "__code__", None) if replacement_fn is not None else None
    )

    if (
        not isinstance(current_code, CodeType)
        or replacement_fn is None
        or not isinstance(new_code, CodeType)
    ):
        return False

    if _is_closure(replacement_fn):
        fn_name = getattr(current_code, "co_name", "<unknown>")
        warnings.append(
            f"Closure function {fn_name}() skipped: captured cell variables "
            "cannot be safely rebound"
        )
        return False

    compatible, reason = is_code_compatible(current_code, new_code)
    if not compatible:
        fn_name = getattr(current_code, "co_name", "<unknown>")
        warnings.append(f"frame.f_code update skipped for {fn_name}(): {reason}")
        return False

    try:
        # CPython allows direct f_code assignment on stopped frames.
        frame.f_code = new_code  # type: ignore[assignment]
    except Exception as exc:
        warnings.append(f"Failed to update frame.f_code: {exc!s}")
        return False

    return True


def rebind_stack_frames(
    frames: list[types.FrameType],
    rebind_map: RebindMap,
    *,
    module_name: str,
    update_frame_code: bool,
) -> RebindResult:
    """Rebind live stack-frame locals and optionally update ``f_code`` objects.

    For every frame in *frames*:
    - Attempts an in-place ``f_code`` swap when *update_frame_code* is True.
    - Replaces any local variable that holds an old function/method with the
      reloaded version, then flushes fast-locals back to the C frame.

    Closure functions from the reloaded module are skipped with a warning
    because their cell variables cannot be safely re-targeted.

    Returns:
        A :class:`RebindResult` dict with ``reboundFrames``,
        ``updatedFrameCodes``, and ``warnings``.
    """
    if not rebind_map:
        return RebindResult(reboundFrames=0, updatedFrameCodes=0, warnings=[])

    warnings: list[str] = []
    rebound_frames = 0
    updated_frame_codes = 0
    closure_warned: set[str] = set()

    for frame in frames:
        if _maybe_update_frame_code(
            frame, rebind_map, warnings, update_frame_code=update_frame_code
        ):
            updated_frame_codes += 1

        f_locals = getattr(frame, "f_locals", None)
        if not isinstance(f_locals, dict):
            continue

        changed = False
        for local_name, local_value in list(f_locals.items()):
            # Closure guard: warn-and-skip closures from the reloaded module.
            raw_fn: FunctionType | None = None
            if isinstance(local_value, FunctionType):
                raw_fn = local_value
            elif isinstance(local_value, MethodType):
                raw_fn = local_value.__func__
            if (
                raw_fn is not None
                and getattr(raw_fn, "__module__", None) == module_name
                and _is_closure(raw_fn)
            ):
                fn_name = getattr(raw_fn, "__name__", "<closure>")
                if fn_name not in closure_warned:
                    closure_warned.add(fn_name)
                    warnings.append(
                        f"Closure function {fn_name}() skipped: captured cell "
                        "variables cannot be safely rebound"
                    )
                continue

            replacement = _replacement_for_value(local_value, rebind_map)
            if replacement is None:
                continue

            try:
                f_locals[local_name] = replacement
                changed = True
            except Exception as exc:
                co = getattr(frame, "f_code", None)
                fname = getattr(co, "co_name", "<?>")
                warnings.append(
                    f"Failed to rebind local '{local_name}' in frame {fname}: {exc!s}"
                )

        if changed:
            rebound_frames += 1
            _flush_frame_locals(frame, warnings)

    return RebindResult(
        reboundFrames=rebound_frames,
        updatedFrameCodes=updated_frame_codes,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# .pyc deletion
# ---------------------------------------------------------------------------


def delete_stale_pyc(source_path: Path) -> list[str]:
    """Delete stale ``__pycache__/*.pyc`` files matching *source_path*.

    Returns a list of warning strings for any files that could not be removed.
    """
    warnings: list[str] = []
    pycache = source_path.parent / "__pycache__"
    if not pycache.is_dir():
        return warnings
    stem = source_path.stem
    for pyc in pycache.glob(f"{stem}*.pyc"):
        try:
            pyc.unlink()
        except Exception as exc:
            warnings.append(f"Failed to delete stale .pyc: {pyc} ({exc!s})")
    return warnings


# ---------------------------------------------------------------------------
# Optional frame-eval cache invalidation
# ---------------------------------------------------------------------------


def _try_invalidate_frame_eval(path: str, warnings: list[str]) -> None:
    """Best-effort: invalidate the dapper frame-eval breakpoint cache for *path*."""
    try:
        from dapper._frame_eval.cache_manager import (  # noqa: PLC0415
            invalidate_breakpoints,
        )

        invalidate_breakpoints(path)
    except Exception as exc:
        warnings.append(f"Frame-eval cache invalidation failed: {exc!s}")


# ---------------------------------------------------------------------------
# Default live-frame source (external-process use)
# ---------------------------------------------------------------------------


def _get_all_frames() -> list[types.FrameType]:
    """Return every live Python frame in the current process.

    Walks :func:`sys._current_frames` for all threads, following ``f_back``
    links so that the full call stack of each thread is included.
    """
    seen: set[int] = set()
    result: list[types.FrameType] = []
    for root_frame in sys._current_frames().values():  # noqa: SLF001
        f: types.FrameType | None = root_frame
        while f is not None:
            fid = id(f)
            if fid in seen:
                break
            seen.add(fid)
            result.append(f)
            f = f.f_back
    return result


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------


def perform_reload(
    path: str,
    options: HotReloadOptions | None,
    *,
    get_frames_fn: Callable[[], list[types.FrameType]] | None = None,
) -> PerformReloadResult:
    """Reload the Python source file at *path* in the **current** process.

    This is the primary entry point used by both the in-process
    :class:`~dapper.adapter.hot_reload.HotReloadService` (via the external
    backend path) and the debuggee-side ``@command_handler("hotReload")``
    registered in :mod:`dapper.shared.command_handlers`.

    The full sequence is:

    1. Resolve and validate the source path (:func:`check_reloadable_source`).
    2. Find the already-loaded module via :func:`resolve_module_for_path`.
    3. Optionally delete stale ``.pyc`` cache files.
    4. Invalidate ``importlib`` caches and ``linecache``.
    5. Call :func:`importlib.reload` to obtain fresh code objects.
    6. Build a rebind map (old-function/code id → new function).
    7. Walk live frames and rebind locals / swap ``f_code`` objects.
    8. Best-effort frame-eval breakpoint cache invalidation.

    Args:
        path: Absolute file-system path to the ``.py`` file to reload.
        options: Optional per-request behaviour overrides.  ``None`` accepts
            all defaults (pyc deletion, frame-code update enabled).
        get_frames_fn: Callable returning the live frames to rebind.  Defaults
            to :func:`_get_all_frames` which walks
            :func:`sys._current_frames`.  Override in tests or for the
            in-process path to supply frames from the debugger's thread
            tracker.

    Returns:
        A fully-populated :class:`PerformReloadResult`.

    Raises:
        ValueError: Source is not reloadable or has not been imported.
        OSError: ``Path.resolve(strict=True)`` failed (file not found).
    """
    if get_frames_fn is None:
        get_frames_fn = _get_all_frames

    resolved = Path(path).resolve(strict=True)
    check_reloadable_source(resolved)

    module_name, module = resolve_module_for_path(str(resolved))

    opts: HotReloadOptions = cast("HotReloadOptions", options or {})
    invalidate_pyc = bool(opts.get("invalidatePycache", True))
    update_frame_code = bool(opts.get("updateFrameCode", True))

    warnings: list[str] = []

    importlib.invalidate_caches()
    linecache.checkcache(str(resolved))

    if invalidate_pyc:
        warnings.extend(delete_stale_pyc(resolved))

    old_functions = collect_module_functions(module)
    reloaded = importlib.reload(module)
    linecache.checkcache(str(resolved))
    new_functions = collect_module_functions(reloaded)

    rebind_map = build_rebind_map(old_functions, new_functions)
    rebind_result = rebind_stack_frames(
        get_frames_fn(),
        rebind_map,
        module_name=module_name,
        update_frame_code=update_frame_code,
    )
    warnings.extend(rebind_result["warnings"])

    _try_invalidate_frame_eval(str(resolved), warnings)

    return PerformReloadResult(
        reloadedModule=getattr(reloaded, "__name__", module_name),
        reboundFrames=rebind_result["reboundFrames"],
        updatedFrameCodes=rebind_result["updatedFrameCodes"],
        warnings=warnings,
    )
