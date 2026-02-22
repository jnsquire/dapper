# Reload-and-Continue — Implementation Plan

> **Feature:** When stopped at a breakpoint, allow the user to edit source and
> apply the change without restarting.  Use `importlib.reload` + targeted
> frame-locals rebinding for functions already on the call stack.

---

## Overview

The feature adds a custom DAP request (`dapper/hotReload`) that accepts a
source file path, reloads the corresponding Python module, invalidates all
relevant caches, re-applies breakpoints against the new code objects, and
optionally rebinds function references on live stack frames.

### Data flow

```
VS Code (or DAP client)
  │  request: "dapper/hotReload" { source: { path: "/foo/bar.py" } }
  ▼
RequestHandler._handle_dapper_hot_reload()
  │  validates debugger is stopped, resolves module from path
  ▼
PyDebugger.hot_reload(module_path)
  │  ┌──────────────────────────────────────────────┐
  │  │ 1. Resolve sys.modules entry from file path  │
  │  │ 2. importlib.invalidate_caches()              │
  │  │ 3. Delete stale .pyc from __pycache__         │
  │  │ 4. linecache.checkcache(path)                 │
  │  │ 5. importlib.reload(module)                   │
  │  │ 6. Invalidate frame-eval caches for file      │
  │  │ 7. Clear + re-set bdb breakpoints             │
  │  │ 8. Rebind frame locals on call stack           │
  │  │ 9. Emit "loadedSource" { reason: "changed" }  │
  │  └──────────────────────────────────────────────┘
  ▼
Client receives response + loadedSource event
  → editor refreshes gutter decorations & breakpoint markers
```

---

## Phases

### Phase 1 — Minimum viable reload (module-level)

Covers reloading a single-file module and re-synchronising breakpoints.
No frame-locals rebinding yet; the user resumes execution after the reload
and new code is picked up on the next function call.

| Step | What | Where | Notes |
|------|------|-------|-------|
| 1.1 | Add `HotReloadArguments` / `HotReloadResponse` TypedDicts | `protocol/requests.py` | Custom request; namespace as `dapper/hotReload` |
| 1.2 | Add `supportsHotReload` capability flag | `protocol/capabilities.py` → `request_handlers.py` `_handle_initialize` | Advertise in initialize response |
| 1.3 | Add `_handle_dapper_hot_reload()` to `RequestHandler` | `adapter/request_handlers.py` | Validates stopped state via `LifecycleManager`, delegates to `PyDebugger` |
| 1.4 | Implement `PyDebugger.hot_reload(path) → HotReloadResult` | `adapter/debugger/py_debugger.py` | Orchestrator; calls steps 1.5–1.9 |
| 1.5 | Module resolver: `path → module` | new utility in `adapter/source_tracker.py` or a helper on `LoadedSourceTracker` | Iterate `sys.modules`, match `getattr(mod, '__file__', None)` to `os.path.realpath(path)` |
| 1.6 | Perform the reload | inside `PyDebugger.hot_reload` | `importlib.invalidate_caches()` → delete `.pyc` → `linecache.checkcache(path)` → `importlib.reload(module)` |
| 1.7 | Invalidate frame-eval caches | `_frame_eval/cache_manager.py` | Call `invalidate_breakpoints(path)` + `CacheManager.invalidate_file(path)` (new method, see below) |
| 1.8 | Re-set breakpoints | `core/breakpoint_manager.py`, `core/debugger_bdb.py` | `clear_breaks_for_file(path)` → re-apply from saved `BreakpointManager.line_meta` |
| 1.9 | Emit `loadedSource` changed event | `PyDebugger._emit_event()` | `{"reason": "changed", "source": {"name": …, "path": …}}` |
| 1.10 | Add `CacheManager.invalidate_file(path)` | `_frame_eval/cache_manager.py` | Clears `_func_code_cache` entries whose code originated from `path`; clears `BreakpointCache` for `path` |
| 1.11 | Unit tests for phase 1 | `tests/unit/test_hot_reload.py` | Mock `sys.modules`, verify cache invalidation, breakpoint re-set, event emission |
| 1.12 | Integration test | `tests/integration/test_hot_reload.py` | Temp module on disk → set breakpoint → edit file → hot reload → verify new source executes |

**Deliverable:** User can trigger reload from a DAP client; the next function
call executes the updated code.  Breakpoints survive the reload.

---

### Phase 2 — Frame-locals rebinding

Update function references on live stack frames so that resuming execution
(continue / step) uses the new code immediately — even for functions
currently mid-execution.

| Step | What | Where | Notes |
|------|------|-------|-------|
| 2.1 | Build old→new function map | `PyDebugger.hot_reload` | Before reload, snapshot `{name: func for name, func in module.__dict__.items() if callable(func)}`. After reload, build `old_code_id → new_func` mapping by qualified name. |
| 2.2 | Walk call stack, rebind locals | new helper `_rebind_stack_functions(thread, mapping)` | For each frame on the stopped thread(s): scan `frame.f_locals` for values whose `__code__` id is in `mapping`; replace with new function object. Use `ctypes` frame-locals write-back on 3.9–3.12; use `frame.f_locals` proxy on 3.13+. |
| 2.3 | Update `frame.f_code` (3.12+) | same helper | On CPython ≥3.12, if the new code object is structurally compatible (same `co_varnames` length, same `co_freevars`), assign `frame.f_code = new_code`. Fall back to skip with a warning otherwise. |
| 2.4 | Patch class instances | optional, behind config flag | For each frame local that is an instance whose `__class__.__module__` == reloaded module: `obj.__class__ = new_module.ClassName`. Risky — guard with try/except. |
| 2.5 | Refresh `VariableManager` references | `core/variable_manager.py` | Invalidate cached var-refs for frames whose locals were rebound, so the next `variables` request reflects new values. |
| 2.6 | Tests for frame rebinding | `tests/unit/test_hot_reload.py` | Synthetic frames with mock functions; verify locals are updated. |

**Deliverable:** After reload, stepping continues with the new code in the
current frame (where structurally possible).

---

### Phase 3 — UX polish and safety

| Step | What | Where | Notes |
|------|------|-------|-------|
| 3.1 | Structural compatibility check | `PyDebugger.hot_reload` | Before attempting `frame.f_code` assignment, compare `co_varnames`, `co_freevars`, `co_cellvars`, `co_argcount`. Report incompatibilities in the response `warnings` list. |
| 3.2 | Guard: C extension modules | module resolver | Reject reload if `module.__file__` ends in `.so` / `.pyd`. Return error in response. |
| 3.3 | Guard: module-level side effects | config flag `hotReload.reExecuteModuleBody` (default `true`) | Document that `importlib.reload` re-runs top-level code. Optionally offer a "functions only" mode that patches `__dict__` entries without re-executing the module body (advanced — deferred). |
| 3.4 | VS Code extension command | `vscode/extension/` | Add a `dapper.hotReload` command and keybinding that triggers the custom DAP request on the current file. |
| 3.5 | Guard: only while stopped | `RequestHandler` | Return `ErrorResponse` if lifecycle state is not `STOPPED`. |
| 3.6 | Closure handling | frame rebinding helper | Detect functions with `__closure__`; skip rebinding with a warning rather than silently breaking captured variables. |
| 3.7 | Telemetry event | `_frame_eval/telemetry.py` | Record reload events: module name, duration, success/failure, rebinding count. |
| 3.8 | Documentation | `doc/reference/hot-reload.md` | User-facing docs: usage, limitations, known edge cases. |

---

## Key Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| `frame.f_code` is read-only on <3.12 | Frame rebinding is limited to function locals, not the executing code | Phase 2 degrades gracefully: update `__code__` on function objects (affects future calls) but skip frame mutation; document the limitation |
| `importlib.reload` re-executes module body | Duplicate side effects (registrations, singleton reinit) | Document clearly; offer opt-out config in Phase 3 |
| Closures reference old cells | Silent data inconsistency after rebinding | Detect closures and skip rebinding with a diagnostic warning (Phase 3.6) |
| Stale `.pyc` causes reload to load old bytecode | Reload appears to do nothing | Explicitly delete `__pycache__/<module>.*.pyc` before reload (Phase 1.6) |
| Thread safety during reload | Corruption if another thread is mid-execution in the module | Reload only while all threads are stopped (enforced by lifecycle state check); document that async tasks may still hold old references |
| Bytecode cache leak in `BytecodeModifier.modified_code_objects` | Memory growth over many reloads | Add `evict_file(path)` to `BytecodeModifier` that removes entries originating from `path` (Phase 1.10) |

---

## Files to Create or Modify

### New files
| Path | Purpose |
|------|---------|
| `dapper/adapter/hot_reload.py` | `HotReloadService` class — encapsulates module resolution, reload execution, cache invalidation, breakpoint refresh, frame rebinding |
| `tests/unit/test_hot_reload.py` | Unit tests for `HotReloadService` |
| `tests/integration/test_hot_reload.py` | End-to-end reload integration test *(planned; not yet implemented)* |
| `doc/reference/hot-reload.md` | User-facing documentation *(planned; not yet implemented)* |

### Modified files
| Path | Change |
|------|--------|
| `dapper/protocol/requests.py` | Add `HotReloadArguments`, `HotReloadResponse` TypedDicts |
| `dapper/protocol/capabilities.py` | Add `supportsHotReload` to `Capabilities` |
| `dapper/adapter/payload_extractor.py` | Add `_hot_reload_result` extractor and register `dapper/hotReloadResult` |
| `dapper/adapter/request_handlers.py` | Add `_handle_dapper_hot_reload()` method and advertise `supportsHotReload` |
| `dapper/adapter/debugger/py_debugger.py` | Add `hot_reload(path)` method that delegates to `HotReloadService` |
| `dapper/adapter/source_tracker.py` | Add `resolve_module_for_path(path) → ModuleType \| None` helper |
| `tests/unit/test_request_handlers.py` | Add handler-level tests for `dapper/hotReload` preconditions and success path |
| `dapper/_frame_eval/cache_manager.py` | Use existing `invalidate_breakpoints(path)` API from hot reload service *(no new `invalidate_file` method added in this phase)* |
| `dapper/_frame_eval/modify_bytecode.py` | `evict_file(path)` cleanup helper *(planned; not yet implemented)* |
| `dapper/_frame_eval/runtime.py` | `invalidate_file(path)` convenience API *(planned; not yet implemented)* |
| `dapper/core/debugger_bdb.py` | `reapply_breakpoints_for_file(path)` helper *(planned; not yet implemented; reapply currently done via `PyDebugger.set_breakpoints`)* |

---

## Estimated Effort

| Phase | Scope | Estimate |
|-------|-------|----------|
| Phase 1 | MVP reload + cache invalidation + breakpoint re-sync | 3–4 days |
| Phase 2 | Frame-locals rebinding + `f_code` mutation | 2–3 days |
| Phase 3 | Guards, UX polish, VS Code command, docs | 2–3 days |
| **Total** | | **7–10 days** |

---

## Acceptance Criteria

### Phase 1
- [x] `dapper/hotReload` request accepted while debugger is stopped (in-process)
- [x] Module is reloaded; next function call executes updated code (in-process)
- [x] Breakpoints survive the reload (line numbers that still exist, in-process)
- [x] `loadedSource` event emitted with `reason: "changed"`
- [x] Error response returned for non-Python / non-loaded modules
- [x] Frame-eval caches are invalidated for the reloaded file

Status note: Phase 1 is complete for the in-process backend. External-process
hot reload transport/execution remains outstanding and is tracked in Phase 3 scope.

### Phase 2
- [ ] Function locals referencing reloaded functions are updated in-place
- [ ] On 3.12+, `frame.f_code` is updated when structurally compatible
- [ ] Variables panel reflects new values after reload
- [ ] Incompatible code changes produce a diagnostic warning (not a crash)

### Phase 3
- [ ] Closures are detected and skipped with warning
- [ ] C extensions are rejected with a clear error message
- [ ] VS Code keybinding triggers reload on current file
- [ ] Documentation covers usage, limitations, and supported Python versions

---

*Plan created: 2026-02-21*
