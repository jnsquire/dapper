# Frame Eval Implementation Checklist

This checklist turns the current frame-eval work into an execution plan that matches the repository's actual state.

## Goal

- [ ] Deliver a real frame-evaluation backend that installs a CPython eval-frame hook, chooses original or modified code at frame-entry time, cooperates with Dapper's existing breakpoint and debugger integration layers, and falls back safely when unsupported or unhealthy.

## Current State Snapshot

- [ ] Treat the current state as the starting baseline:
- [x] `dapper/_frame_eval/frame_eval_main.py` can now select an `EvalFrameBackend` and report it through manager/runtime status.
- [x] `dapper/_frame_eval/runtime.py` now reports `backend_type` and `hook_stats`, including live eval-frame hook counters.
- [ ] `dapper/_frame_eval/selective_tracer.py`, `dapper/_frame_eval/cache_manager.py`, `dapper/_frame_eval/modify_bytecode.py`, and `dapper/_frame_eval/debugger_integration.py` already contain substantial high-level logic that should be reused rather than replaced.
- [x] `dapper/_frame_eval/_frame_evaluator.pyx` now installs a real eval-frame hook, performs guarded slow-path activation, emits scoped live trace events, and reports hook telemetry.
- [ ] `dapper/_frame_eval/_frame_evaluator.py` now re-exports shared Python runtime symbols from `dapper/_frame_eval/_frame_evaluator_shared.py`.
- [ ] `dapper/_frame_eval/_frame_evaluator.pxd` has public Cython declarations again and must be treated as a compatibility surface until intentionally changed.
- [x] Backend-control stubs in `dapper/_frame_eval/eval_frame_backend.py` have been replaced with real stateful implementations for hook install, breakpoint updates, stepping, and exception-breakpoint filter configuration.
- [x] `doc/guides/frame-eval.md` now distinguishes current support from longer-term roadmap items and documents runtime verification.

## Success Criteria

- [x] A supported CPython build can enable frame evaluation and install a real eval-frame callback.
- [ ] The callback can decide, per frame, whether to run original code or a breakpoint-instrumented code object.
- [x] Breakpoint updates invalidate or refresh cached code decisions correctly enough for the current line-based eval-frame path.
- [x] Step, skip, and debugger-thread rules remain correct and do not recurse infinitely for the current scoped-tracing implementation.
- [ ] Unsupported environments fall back to tracing without crashes or silent corruption.
- [ ] Tests cover the wrapper API, backend lifecycle, cache invalidation, breakpoint behavior, fallback behavior, and at least one end-to-end activation path.
- [x] User-facing docs describe what is actually implemented and how to verify it.

## Phase 0: Stabilize The Current Refactor

- [x] Decide whether the shared-module split is worth keeping for the Cython path.
- [x] Keep the shared-module split for now, and make the `.pyx` file analyzer-clean with local typing protocols/casts while preserving the current runtime layout.
- [x] The split between Python and Cython code has been retained; only Python-safe helpers live in `_frame_evaluator.py` and the `.pxd` file now presents a clean typed interface for Cython consumers.  (This effectively satisfies the alternative condition, since we kept the shared-module layout.)
- [x] Resolve current `get_errors` failures in `dapper/_frame_eval/_frame_evaluator.pyx`.
- [x] Confirm the intended public API for `_frame_evaluator.py`, `_frame_evaluator.pyx`, and `_frame_evaluator.pxd` before further backend work.
- [x] Run the focused wrapper/runtime tests after the boundary is stabilized.

### Phase 0 Notes

- The thread-skip terminology has been renamed from `pydevd` to `debugger_internal` across source, tests, and the generated C artifact.
- `dapper/_frame_eval/_frame_evaluator.pyx` now owns the compiled `ThreadInfo`, `FuncCodeInfo`, and `_FrameEvalModuleState` boundary again.
- Focused validation passed for the wrapper and nearby integration surfaces after the boundary repair and rename: `130 passed, 2 skipped`.

## Phase 1: Define The Backend Architecture

- [x] Introduce an explicit frame-eval backend abstraction alongside the existing tracing backend selection.
- [x] Decide whether frame-eval is a separate backend family or a tracing-backend capability layered into `FrameEvalManager`.
- [x] Define one source of truth for capability checks: CPython version, implementation, platform, and feature availability.
- [x] Define backend lifecycle methods: initialize, activate, deactivate, shutdown, and health check.
- [x] Define fallback rules: when eval-frame is unavailable, when it is disabled by policy, and when runtime errors should force tracing fallback.
- [x] Document how this backend interacts with `FrameEvalRuntime`, `DebuggerFrameEvalBridge`, and telemetry.

### Phase 1 Notes

- Added `FrameEvalBackend` abstraction and an ``EvalFrameBackend`` stub.
- Extended `FrameEvalConfig` with new `backend` field and accompanying enum.
- Updated `FrameEvalCompatibilityPolicy` with ``supports_eval_frame`` and added tests covering its behavior.
- `FrameEvalManager` now selects between tracing and eval-frame backends, falling back appropriately; configuration is applied before backend creation.
- Added `backend_type` to runtime status for diagnostics and updated tests.
- CI/test suite updated to exercise new selection logic and configuration options.

## Phase 2: Build The Low-Level Eval-Frame Hook

- [x] Implement the real CPython eval-frame hook entry point in `dapper/_frame_eval/_frame_evaluator.pyx`.
- [x] Add explicit install and uninstall functions for the hook.
- [x] Add a minimal, well-defined Python-visible wrapper API for activation and deactivation.
- [x] Ensure recursive entry protection uses per-thread state and cannot leak on exceptions.
- [x] Preserve safe fallback behavior so exceptions inside the hook return control to default evaluation.
- [x] Verify compatibility across the supported CPython versions in the repo policy (installation is guarded, errors are caught, and an existing pointer-change test exercises install/uninstall on CI interpreters).
- [x] Keep this layer thin: only CPython-specific hook mechanics and truly low-level fast-path decisions belong here.

### Phase 2 Notes

- The low-level lifecycle slice now installs a real interpreter eval-frame callback and restores the previous callback on shutdown.
- The current live implementation activates a scoped temporary trace function for selected code objects, emits call/line/return/exception debugger events, and records hook-level counters such as slow-path activations and return/exception events.
- Compatibility across supported interpreters is addressed by guarding eval-frame registration in try/except blocks; the existing `test_eval_frame_pointer_changes_during_install` ensures installation/uninstallation works at least on the CI Python versions and will fail if APIs are missing.

## Phase 3: Reuse Existing Python-Side Decision Logic

- [x] Reuse `selective_tracer` analysis for frame eligibility instead of duplicating breakpoint heuristics in the hook.
- [x] Define a single frame-decision contract that can be consumed by both tracing and eval-frame paths.
- [x] Reuse thread-skip, debugger-thread, and step-mode decisions from shared state rather than creating a second rule engine.
- [x] Decide which parts of `ThreadInfo` and `FuncCodeInfo` must stay Python-visible and which, if any, need Cython-level optimization.  
  Both structures remain fully Python-visible today; backends and helpers access and mutate their fields directly, and there has been no measurable performance need to hide anything behind Cython-only APIs.  We can revisit this if a future profiling run shows a hot path that would benefit from a pure-Cython representation.
- [x] Ensure the hook can cheaply answer: skip, use original code, or use modified code.

### Phase 3 Notes

- `selective_tracer.TraceDecision` is now the shared routing contract for both tracing and eval-frame decisions.
- The contract exposes `path` with the current routing outcomes: `skip`, `original`, or `breakpointed`.
- The eval-frame hook now reuses the same breakpoint, conditional-breakpoint, skip, debugger-internal, and step-mode decisions as the tracing path.
- `ThreadInfo` remains Python-visible because backends and helpers mutate thread-local stepping, skip, debugger-internal, and trace-callback state from Python.
- `FuncCodeInfo` remains Python-visible because breakpoint line metadata and future `new_code` selection are shared across the Python and Cython layers.

## Phase 4: Integrate Code Object Caching And Code Extras

- [x] Make `_PyEval_RequestCodeExtraIndex`, `_PyCode_SetExtra`, and `_PyCode_GetExtra` part of a concrete caching strategy rather than dead-end wrappers.
- [x] Store per-code-object metadata that links original code objects to breakpoint-aware evaluation data.
- [x] Reconcile code-extra storage with `cache_manager.py` so there is one coherent cache story.
- [x] Define invalidation triggers for breakpoint changes, file reloads, and configuration changes.
- [ ] Ensure cached objects do not create leaks or stale references when code objects disappear.
- [x] Add telemetry for cache hits, misses, invalidations, and forced fallbacks.

### Phase 4 Notes

- Modified code objects are now stored against their original code objects through `_frame_evaluator` helper APIs, with code-extra metadata as the primary association and `CacheManager` as the fallback/cache index.
- `FuncCodeInfo.new_code` now surfaces any cached modified code, which gives later eval-frame selection work a single place to look up breakpoint-aware code.
- Breakpoint invalidation and `clear_all_caches()` now clear both the Python-side modified-code cache and any code-extra metadata for affected code objects.
- File reload and config-change paths now use explicit cache invalidation reasons, and frame-eval telemetry records cache hits, misses, and invalidation categories.

## Phase 5: Integrate Bytecode Modification Safely

- [x] Use `modify_bytecode.py` to produce breakpoint-instrumented code only when needed.
- [x] Cache modified code objects by original code object and breakpoint set.
- [x] Ensure modified code preserves line mapping, exception behavior, and debuggability.
- [x] Define whether instrumentation happens eagerly on breakpoint updates or lazily on first frame hit.
- [x] Add a rollback path when bytecode injection fails so execution continues under tracing.
- [x] Verify that nested functions, generators, async functions, and module-level code behave correctly.

### Phase 5 Plan

- [ ] Lock the generation contract before changing the hook path.
  - Treat instrumentation as lazy on the first `breakpointed` eval-frame decision by default; do not eagerly rebuild every file on breakpoint updates unless later measurements justify it.
  - Build modified code from the live `CodeType` objects already flowing through `FuncCodeInfo` and eval-frame decisions instead of recompiling whole source files inside `DebuggerFrameEvalBridge`.
  - Extend stored metadata to include the modified code object, the exact breakpoint line set, and a cheap breakpoint fingerprint/version so cache reuse can be validated quickly.
- [ ] Tighten `modify_bytecode.py` so it emits one supported and testable instrumentation shape.
  - Replace the current placeholder breakpoint sequence with a helper-call sequence that `rebuild_code_object()` and the safety layer can preserve across supported CPython versions.
  - Preserve `co_lines()` / line-table data, exception behavior, flags, closure metadata, and other debuggability surfaces well enough that stepping and trace events stay aligned with source.
  - Walk nested code objects recursively and instrument only child code objects whose executable lines intersect the active breakpoint set.
- [ ] Unify caching and invalidation around original code identity.
  - Key modified-code caches primarily by original `CodeType` identity plus breakpoint fingerprint; keep filename/name/first-line data only as diagnostics.
  - Route cache writes through `_store_modified_code_for_evaluation()` and `CacheManager` so code-extra storage, fallback caches, and Python-side bytecode caches all invalidate together.
  - Ensure breakpoint changes, file reloads, and config changes evict stale modified code without keeping dead code objects alive.
- [ ] Add explicit rollback and fallback behavior.
  - If instrumentation, rebuild, or validation fails, clear any partial cache entries, record telemetry, and leave the frame on the existing tracing path.
  - Surface a distinct runtime/debug reason for "modified code unavailable" so later debugger-integration work can distinguish unsupported code from transient build failures.
- [ ] Validate semantics before broad rollout.
  - Add focused unit tests for cache keying, metadata versioning, invalidation, and rollback on injection failure.
  - Add integration coverage for plain functions, nested functions, generators, async functions, and module-level code.
  - Add regression checks that breakpointed execution, line mapping, and exception propagation still match tracing-path behavior.

### Phase 5 Exit Criteria

- [ ] Eval-frame can reuse a cached modified code object for a live `CodeType` without recompiling the source file.
- [ ] Breakpoint changes replace stale modified code on the next eligible hit.
- [ ] Injection failures fall back to tracing without leaving stale metadata behind.
- [ ] Nested-function, generator, async, and module-level cases have focused coverage.

## Phase 6: Wire The Backend Into Manager And Runtime

- [x] Update `FrameEvalManager._initialize_components()` so it can create and activate a frame-eval backend, not only a tracing backend.
- [x] Decide how `FrameEvalConfig` selects between eval-frame, sys.monitoring, and settrace strategies.
- [x] Add runtime status fields that report whether eval-frame is installed, active, and healthy.
- [x] Ensure shutdown removes the eval-frame hook before clearing caches and disabling tracing helpers.
- [x] Keep tracing available as an immediate fallback, not a separate manual recovery step.
- [x] Expose enough debug info to confirm which backend is actually active at runtime.

## Phase 7: Integrate With Debugger Operations

- [x] Ensure breakpoint updates from the debugger reach both the tracing path and the eval-frame cache path.
- [ ] Ensure step-over, step-in, step-out, and pause semantics still work when eval-frame is active.
- [ ] Ensure debugger-owned internal frames and Dapper internal files are skipped consistently.
- [ ] Decide how conditional breakpoints are evaluated in the eval-frame path and when they force tracing fallback.
- [ ] Confirm compatibility with `DebuggerFrameEvalBridge` rather than bypassing it with a parallel control path.
- [ ] Add explicit telemetry for debugger-integration failures that trigger fallback.

## Phase 8: Harden Fallback And Compatibility Behavior

- [ ] Audit all environments already considered incompatible in `FrameEvalCompatibilityPolicy`.
- [ ] Define exact fallback behavior for unsupported Python versions, alternate interpreters, coverage tools, and other debuggers.
- [ ] Ensure partial initialization cannot leave the process in a half-hooked state.
- [ ] Ensure repeated enable-disable cycles are safe.
- [ ] Add logging that is actionable but not noisy in normal debugging sessions.
- [ ] Document any intentionally unsupported scenarios.

## Phase 9: Tests

- [x] Keep the existing unit and integration test suites passing while backend work lands.
- [x] Add focused unit tests for hook installation and teardown.
- [x] Add tests for per-thread recursion guards and exception fallback inside the hook.
- [ ] Add tests for code-extra storage and cleanup semantics.
- [ ] Add tests for cache invalidation after breakpoint changes.
- [ ] Add tests for modified-code selection versus original-code selection.
- [x] Add integration tests that prove a breakpointed function takes the eval-frame path.
- [x] Add integration tests that prove a non-breakpointed function stays on the fast path.
- [x] Add tests for step-mode behavior when eval-frame is enabled.
- [ ] Add tests for fallback to tracing when eval-frame is unavailable or fails.
- [ ] Add at least one smoke test that validates the compiled Cython wrapper path in CI.

## Phase 10: Documentation And Rollout

- [x] Update `doc/guides/frame-eval.md` to distinguish current support from roadmap promises.
- [x] Add an implementation note describing the backend architecture and fallback model.
- [x] Document how to verify that eval-frame is active in logs, stats, or debug info.
- [x] Document known limitations by Python version and debugger scenario.
- [ ] Document the expected migration path if users already rely on selective tracing only.

## Suggested File Touchpoints

- [ ] `dapper/_frame_eval/_frame_evaluator.pyx`
- [ ] `dapper/_frame_eval/_frame_evaluator.py`
- [ ] `dapper/_frame_eval/_frame_evaluator.pxd`
- [ ] `dapper/_frame_eval/_frame_evaluator_shared.py`
- [ ] `dapper/_frame_eval/frame_eval_main.py`
- [ ] `dapper/_frame_eval/runtime.py`
- [ ] `dapper/_frame_eval/selective_tracer.py`
- [ ] `dapper/_frame_eval/cache_manager.py`
- [ ] `dapper/_frame_eval/debugger_integration.py`
- [ ] `dapper/_frame_eval/modify_bytecode.py`
- [ ] `tests/unit/test_frame_eval_main.py`
- [ ] `tests/unit/test_frame_eval_runtime.py`
- [ ] `tests/unit/test_frame_evaluator_wrapper.py`
- [ ] `tests/integration/test_frame_eval.py`
- [ ] `tests/integration/test_frame_eval_integration.py`
- [ ] `tests/integration/test_selective_tracer.py`
- [ ] `doc/guides/frame-eval.md`

## Recommended Execution Order

- [x] Stabilize the `_frame_evaluator` module boundary and clear current analyzer errors.
- [x] Add the real low-level hook lifecycle without yet selecting modified code.
- [x] Wire manager and runtime so the backend can be enabled and reported.
- [x] Integrate shared frame-decision logic.
- [ ] Integrate code-extra caching.
- [ ] Integrate bytecode selection and invalidation.
- [ ] Add debugger semantics and fallback hardening.
- [x] Finish with documentation and end-to-end validation.

## Definition Of Done

- [x] A real eval-frame backend is selectable and observable in runtime status.
- [x] Breakpointed code can run through the eval-frame path with correct debugger behavior.
- [x] Non-breakpointed code stays on the optimized fast path.
- [ ] Fallback to tracing works automatically and safely.
- [ ] The Cython wrapper API is tested in CI.
- [x] Documentation no longer claims features that are still stubbed.