# Frame Evaluation Refactor Plan

## Goal

Refactor the frame evaluation subsystem to improve correctness, maintainability, and feature velocity while preserving backward compatibility and minimizing runtime risk.

## Non-Goals

- No wholesale rewrite of the Cython evaluator in a single PR.
- No debugger protocol behavior changes unless explicitly scoped in a phase.
- No performance claims without benchmark evidence.

## Success Criteria

- Single authoritative compatibility policy used across frame-eval entrypoints.
- Reduced global mutable state and duplicated runtime abstractions.
- Observable fallback/error reasons instead of silent failure paths.
- Stable or improved performance on integration benchmarks.
- Existing frame-eval public API remains compatible.

## Current Pain Points (Observed)

1. Compatibility policy drift
   - Supported versions list includes 3.11–3.13, but runtime check rejects >3.10.
2. Lifecycle is not a true composition root
   - Manager init/cleanup do not own subsystem wiring end-to-end.
3. Duplicated runtime abstractions
   - Thread info and fallback behavior are implemented in multiple modules.
4. Broad exception swallowing
   - Many catch-all paths hide behavior regressions and make diagnosis hard.
5. Mixed responsibilities in integration layer
   - Debugger bridge currently combines policy, monkeypatching, and optimization orchestration.

## High-Level Architecture Target

### Runtime Composition

Introduce one internal runtime composition service:

- FrameEvalRuntime
  - Owns configuration, compatibility, tracer, cache, bytecode optimizer, and debugger integration bridge.
  - Exposes start, stop, status, and update_breakpoints operations.

### Stable Public Surface

Keep existing module-level functions as compatibility wrappers that delegate to runtime.

### Policy and Telemetry

- Centralized compatibility policy object.
- Structured reason codes for fallback, disablement, and optimization failures.
- Unified stats schema consumed by tests and diagnostics.

#### Telemetry & selective tracing (implementation notes)

- A thread-safe telemetry collector records events and a short recent-event history; API is exposed via `dapper._frame_eval.telemetry`.
- Selective tracing performs lightweight frame analysis (fast-path checks, condition evaluation, per-file caching) and exposes stats useful for tuning (`trace_rate`, `cache_hits`, `fast_path_hits`).
- Telemetry is surfaced in runtime stats (`FrameEvalRuntime.get_stats()`) so tooling and CI can assert on reason-codes and trace metrics.

Files of interest: `dapper/_frame_eval/telemetry.py`, `dapper/_frame_eval/selective_tracer.py`, `dapper/_frame_eval/runtime.py`.

---

## Phased Plan (PR-Sized)

## Phase 0: Baseline and Safety Net

### Scope

- Document existing behavior contracts and invariants.
- Add focused tests for known drift/fragility points before refactoring.

### File Targets

- tests/unit/test_frame_eval_manager.py
- tests/unit/test_frame_eval_main.py
- tests/integration/test_frame_eval_components.py
- tests/integration/test_frame_eval_integration.py

### Deliverables

- New tests that lock in:
  - Compatibility decision matrix behavior.
  - Integration fallback semantics under controlled failures.
  - Stats schema shape guarantees.

### Exit Criteria

- New tests fail on current drift but pass once drift is fixed.
- CI green with no unrelated test changes.

### Rollback Strategy

- Revert only added tests if they block refactor merge unexpectedly.

---

## Phase 1: Compatibility Policy Unification

### Scope

- Introduce a single compatibility policy module.
- Remove duplicated version/platform compatibility sources.
- Ensure all status/check paths read from one policy implementation.

### File Targets

- dapper/_frame_eval/frame_eval_main.py
- dapper/_frame_eval/config.py
- dapper/_frame_eval/__init__.py
- New: dapper/_frame_eval/compatibility_policy.py

### Deliverables

- CompatibilityPolicy class with:
  - supported_python_min
  - supported_python_max or capability probing model
  - supported_platforms/architectures
  - incompatible_environment detectors
- check_environment_compatibility delegates to policy.

### Exit Criteria

- No contradictory compatibility logic remains.
- Unit tests validate policy for 3.8–3.13 matrix.

### Rollback Strategy

- Keep compatibility wrappers untouched; revert policy wiring if needed.

---

## Phase 2: Runtime Composition Root

### Scope

- Create FrameEvalRuntime and migrate lifecycle ownership from fragmented globals.
- Keep existing top-level API signatures intact.

### File Targets

- dapper/_frame_eval/frame_eval_main.py
- dapper/_frame_eval/__init__.py
- dapper/_frame_eval/selective_tracer.py
- dapper/_frame_eval/cache_manager.py
- dapper/_frame_eval/debugger_integration.py
- New: dapper/_frame_eval/runtime.py

### Deliverables

- FrameEvalRuntime:
  - initialize(config)
  - shutdown()
  - status()
  - get_stats()
  - update_breakpoints(file, lines)
- Existing singleton manager becomes a thin delegator.

### Exit Criteria

- No behavior change in public API tests.
- Runtime start/stop deterministically initializes and tears down subsystems.

### Rollback Strategy

- Preserve old manager path behind feature flag during transition.

---

## Phase 3: Error Handling and Telemetry Hardening

### Scope

- Replace broad silent exceptions with structured error handling.
- Add reason codes and counters for fallback and optimization failures.

### File Targets

- dapper/_frame_eval/debugger_integration.py
- dapper/_frame_eval/modify_bytecode.py
- dapper/_frame_eval/selective_tracer.py
- dapper/_frame_eval/frame_tracing.py
- New: dapper/_frame_eval/telemetry.py

### Deliverables

- Typed reason codes (examples):
  - BYTECODE_INJECTION_FAILED
  - SELECTIVE_TRACING_DISABLED_BY_POLICY
  - INTEGRATION_PATCH_FAILED
  - FALLBACK_TO_TRACE_DISPATCH
- Structured telemetry API and emitted counters.

### Exit Criteria

- Silent pass branches reduced to narrowly-scoped best-effort paths only.
- Integration stats include fallback/error reasons.

### Rollback Strategy

- Telemetry can be disabled via config switch if noisy or unstable.

---

## Phase 4: Bytecode Safety Layer

### Scope

- Isolate bytecode construction by Python version and instruction model.
- Enforce pre/post validation before activation.

### File Targets

- dapper/_frame_eval/modify_bytecode.py
- tests/integration/test_frame_eval_components.py
- New: dapper/_frame_eval/bytecode_safety.py

### Deliverables

- Version-aware bytecode builder facade.
- Validate-on-write rules:
  - instruction stream decodable
  - stacksize invariants
  - safe fallback path on validation failure

### Exit Criteria

- Bytecode injection failures always report reason codes and clean fallback.
- No regression in existing bytecode-related integration tests.

### Rollback Strategy

- Runtime config flag to disable bytecode optimization globally.

---

## Phase 5: Capability Expansion (Optional)

### Scope

- Add one focused capability at a time, with metrics.

### Candidate A: Conditional breakpoints fast-path

- Evaluate lightweight predicates before full trace dispatch.
- Guarded by feature flag and timeout budget.

### Candidate B: Async task-aware step context

- Distinguish thread-local vs task-local stepping state for asyncio workloads.

### File Targets

- dapper/_frame_eval/selective_tracer.py
- dapper/_frame_eval/debugger_integration.py
- dapper/adapter/debugger/py_debugger.py

### Exit Criteria

- Capability is opt-in and benchmarked.
- No protocol regressions in adapter integration tests.

### Rollback Strategy

- Feature-flag off by default until confidence threshold is met.

---

## Cross-Cutting Testing Strategy

## Unit Tests

- Policy matrix tests across mocked Python/platform combinations.
- Runtime lifecycle tests for idempotent initialize/shutdown.
- Error classification tests for known failure branches.

## Integration Tests

- Debugger integration monkeypatch safety and restoration semantics.
- Breakpoint update propagation through tracer and cache.
- Bytecode injection fallback correctness on forced failures.

## Performance Validation

- Add repeatable benchmark script (small, medium, large module workloads).
- Capture before/after:
  - trace call counts
  - skipped frame ratio
  - average per-frame overhead

---

## Migration and Release Plan

1. Ship Phase 1 and 2 behind internal runtime flag default-on in tests.
2. Run full CI plus benchmark job.
3. Ship Phase 3 with telemetry toggles and monitor diagnostics.
4. Ship Phase 4 bytecode safety hardening.
5. Evaluate Phase 5 capabilities as separate feature PRs.

## Suggested PR Breakdown

- PR 1: Tests baseline + compatibility policy module.
- PR 2: Runtime composition root and delegation wiring.
- PR 3: Error handling reason codes + telemetry.
- PR 4: Bytecode safety layer and validation.
- PR 5+: Capability expansion (one feature per PR).

## Risk Register

- Risk: subtle debugger behavior changes from integration rewiring.
  - Mitigation: preserve wrapper APIs and restore semantics tests.
- Risk: performance regressions from additional checks.
  - Mitigation: benchmark gate and fast-path short-circuiting.
- Risk: Python version bytecode edge cases.
  - Mitigation: validation layer + guarded fallback.

## Immediate Next Step

Start with PR 1 (Phase 0 + Phase 1): add baseline tests that expose compatibility drift, then unify compatibility policy and remove contradictory logic.