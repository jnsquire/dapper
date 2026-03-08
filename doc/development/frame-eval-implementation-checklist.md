# Frame Eval Implementation Checklist

This checklist turns the current frame-eval work into an execution plan that matches the repository's actual state.

## Goal

- [ ] Deliver a real frame-evaluation backend that installs a CPython eval-frame hook, chooses original or modified code at frame-entry time, cooperates with Dapper's existing breakpoint and debugger integration layers, and falls back safely when unsupported or unhealthy.

## Current State Snapshot

- [ ] Treat the current state as the starting baseline:
- [ ] `dapper/_frame_eval/frame_eval_main.py` only creates tracing backends today.
- [ ] `dapper/_frame_eval/runtime.py` initializes selective tracing, caches, telemetry, and integration plumbing, but does not install an eval-frame backend.
- [ ] `dapper/_frame_eval/selective_tracer.py`, `dapper/_frame_eval/cache_manager.py`, `dapper/_frame_eval/modify_bytecode.py`, and `dapper/_frame_eval/debugger_integration.py` already contain substantial high-level logic that should be reused rather than replaced.
- [ ] `dapper/_frame_eval/_frame_evaluator.pyx` still has stub behavior in `get_bytecode_while_frame_eval()` and currently has editor errors after the shared-module refactor.
- [ ] `dapper/_frame_eval/_frame_evaluator.py` now re-exports shared Python runtime symbols from `dapper/_frame_eval/_frame_evaluator_shared.py`.
- [ ] `dapper/_frame_eval/_frame_evaluator.pxd` has public Cython declarations again and must be treated as a compatibility surface until intentionally changed.
- [ ] `doc/guides/frame-eval.md` currently overstates implementation maturity and should not be treated as the source of truth until backend work is complete.

## Success Criteria

- [ ] A supported CPython build can enable frame evaluation and install a real eval-frame callback.
- [ ] The callback can decide, per frame, whether to run original code or a breakpoint-instrumented code object.
- [ ] Breakpoint updates invalidate or refresh cached code decisions correctly.
- [ ] Step, skip, and debugger-thread rules remain correct and do not recurse infinitely.
- [ ] Unsupported environments fall back to tracing without crashes or silent corruption.
- [ ] Tests cover the wrapper API, backend lifecycle, cache invalidation, breakpoint behavior, fallback behavior, and at least one end-to-end activation path.
- [ ] User-facing docs describe what is actually implemented and how to verify it.

## Phase 0: Stabilize The Current Refactor

- [x] Decide whether the shared-module split is worth keeping for the Cython path.
- [x] Keep the shared-module split for now, and make the `.pyx` file analyzer-clean with local typing protocols/casts while preserving the current runtime layout.
- [ ] If not keeping it, move only Python-safe shared logic out of the Cython layer and restore a clean, typed boundary for Cython-visible symbols.
- [x] Resolve current `get_errors` failures in `dapper/_frame_eval/_frame_evaluator.pyx`.
- [x] Confirm the intended public API for `_frame_evaluator.py`, `_frame_evaluator.pyx`, and `_frame_evaluator.pxd` before further backend work.
- [x] Run the focused wrapper/runtime tests after the boundary is stabilized.

### Phase 0 Notes

- The thread-skip terminology has been renamed from `pydevd` to `debugger_internal` across source, tests, and the generated C artifact.
- `dapper/_frame_eval/_frame_evaluator.pyx` now owns the compiled `ThreadInfo`, `FuncCodeInfo`, and `_FrameEvalModuleState` boundary again.
- Focused validation passed for the wrapper and nearby integration surfaces after the boundary repair and rename: `130 passed, 2 skipped`.

## Phase 1: Define The Backend Architecture

- [ ] Introduce an explicit frame-eval backend abstraction alongside the existing tracing backend selection.
- [ ] Decide whether frame-eval is a separate backend family or a tracing-backend capability layered into `FrameEvalManager`.
- [ ] Define one source of truth for capability checks: CPython version, implementation, platform, and feature availability.
- [ ] Define backend lifecycle methods: initialize, activate, deactivate, shutdown, and health check.
- [ ] Define fallback rules: when eval-frame is unavailable, when it is disabled by policy, and when runtime errors should force tracing fallback.
- [ ] Document how this backend interacts with `FrameEvalRuntime`, `DebuggerFrameEvalBridge`, and telemetry.

## Phase 2: Build The Low-Level Eval-Frame Hook

- [ ] Implement the real CPython eval-frame hook entry point in `dapper/_frame_eval/_frame_evaluator.pyx`.
- [x] Add explicit install and uninstall functions for the hook.
- [ ] Add a minimal, well-defined Python-visible wrapper API for activation and deactivation.
- [ ] Ensure recursive entry protection uses per-thread state and cannot leak on exceptions.
- [ ] Preserve safe fallback behavior so exceptions inside the hook return control to default evaluation.
- [ ] Verify compatibility across the supported CPython versions in the repo policy.
- [ ] Keep this layer thin: only CPython-specific hook mechanics and truly low-level fast-path decisions belong here.

### Phase 2 Notes

- The current lifecycle slice adds an explicit low-level hook controller API and exposes hook status through runtime/debug surfaces.
- Actual CPython interpreter eval-frame registration is still pending; the hook callback remains a stub that falls back to default evaluation.

## Phase 3: Reuse Existing Python-Side Decision Logic

- [ ] Reuse `selective_tracer` analysis for frame eligibility instead of duplicating breakpoint heuristics in the hook.
- [ ] Define a single frame-decision contract that can be consumed by both tracing and eval-frame paths.
- [ ] Reuse thread-skip, debugger-thread, and step-mode decisions from shared state rather than creating a second rule engine.
- [ ] Decide which parts of `ThreadInfo` and `FuncCodeInfo` must stay Python-visible and which, if any, need Cython-level optimization.
- [ ] Ensure the hook can cheaply answer: skip, use original code, or use modified code.

## Phase 4: Integrate Code Object Caching And Code Extras

- [ ] Make `_PyEval_RequestCodeExtraIndex`, `_PyCode_SetExtra`, and `_PyCode_GetExtra` part of a concrete caching strategy rather than dead-end wrappers.
- [ ] Store per-code-object metadata that links original code objects to breakpoint-aware evaluation data.
- [ ] Reconcile code-extra storage with `cache_manager.py` so there is one coherent cache story.
- [ ] Define invalidation triggers for breakpoint changes, file reloads, and configuration changes.
- [ ] Ensure cached objects do not create leaks or stale references when code objects disappear.
- [ ] Add telemetry for cache hits, misses, invalidations, and forced fallbacks.

## Phase 5: Integrate Bytecode Modification Safely

- [ ] Use `modify_bytecode.py` to produce breakpoint-instrumented code only when needed.
- [ ] Cache modified code objects by original code object and breakpoint set.
- [ ] Ensure modified code preserves line mapping, exception behavior, and debuggability.
- [ ] Define whether instrumentation happens eagerly on breakpoint updates or lazily on first frame hit.
- [ ] Add a rollback path when bytecode injection fails so execution continues under tracing.
- [ ] Verify that nested functions, generators, async functions, and module-level code behave correctly.

## Phase 6: Wire The Backend Into Manager And Runtime

- [ ] Update `FrameEvalManager._initialize_components()` so it can create and activate a frame-eval backend, not only a tracing backend.
- [ ] Decide how `FrameEvalConfig` selects between eval-frame, sys.monitoring, and settrace strategies.
- [ ] Add runtime status fields that report whether eval-frame is installed, active, and healthy.
- [ ] Ensure shutdown removes the eval-frame hook before clearing caches and disabling tracing helpers.
- [ ] Keep tracing available as an immediate fallback, not a separate manual recovery step.
- [ ] Expose enough debug info to confirm which backend is actually active at runtime.

## Phase 7: Integrate With Debugger Operations

- [ ] Ensure breakpoint updates from the debugger reach both the tracing path and the eval-frame cache path.
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

- [ ] Keep the existing unit and integration test suites passing while backend work lands.
- [ ] Add focused unit tests for hook installation and teardown.
- [ ] Add tests for per-thread recursion guards and exception fallback inside the hook.
- [ ] Add tests for code-extra storage and cleanup semantics.
- [ ] Add tests for cache invalidation after breakpoint changes.
- [ ] Add tests for modified-code selection versus original-code selection.
- [ ] Add integration tests that prove a breakpointed function takes the eval-frame path.
- [ ] Add integration tests that prove a non-breakpointed function stays on the fast path.
- [ ] Add tests for step-mode behavior when eval-frame is enabled.
- [ ] Add tests for fallback to tracing when eval-frame is unavailable or fails.
- [ ] Add at least one smoke test that validates the compiled Cython wrapper path in CI.

## Phase 10: Documentation And Rollout

- [ ] Update `doc/guides/frame-eval.md` to distinguish current support from roadmap promises.
- [ ] Add an implementation note describing the backend architecture and fallback model.
- [ ] Document how to verify that eval-frame is active in logs, stats, or debug info.
- [ ] Document known limitations by Python version and debugger scenario.
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

- [ ] Stabilize the `_frame_evaluator` module boundary and clear current analyzer errors.
- [ ] Add the real low-level hook lifecycle without yet selecting modified code.
- [ ] Wire manager and runtime so the backend can be enabled and reported.
- [ ] Integrate shared frame-decision logic.
- [ ] Integrate code-extra caching.
- [ ] Integrate bytecode selection and invalidation.
- [ ] Add debugger semantics and fallback hardening.
- [ ] Finish with documentation and end-to-end validation.

## Definition Of Done

- [ ] A real eval-frame backend is selectable and observable in runtime status.
- [ ] Breakpointed code can run through the eval-frame path with correct debugger behavior.
- [ ] Non-breakpointed code stays on the optimized fast path.
- [ ] Fallback to tracing works automatically and safely.
- [ ] The Cython wrapper API is tested in CI.
- [ ] Documentation no longer claims features that are still stubbed.