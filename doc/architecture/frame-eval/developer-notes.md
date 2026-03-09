# Frame Eval Developer Notes

This note captures the implementation decisions, completed milestones, and maintenance invariants for Dapper's frame-eval work.

It is intentionally different from the user-facing guide and from the higher-level backend architecture note:

- use [guides/frame-eval.md](../../guides/frame-eval.md) for operator-facing behavior and runtime verification
- use [architecture/frame-eval/backend-architecture.md](backend-architecture.md) for the main component model and backend-selection story
- use this note for implementation status, design constraints, and the pieces future contributors should preserve

## Current Status

The current repository state has a real eval-frame backend, not a placeholder.

- `FrameEvalManager` can select an `EvalFrameBackend` and report it through runtime status
- `EvalFrameBackend` installs a real hook lifecycle and participates in breakpoint, stepping, and debugger integration flows
- `dapper._frame_eval._frame_evaluator.pyx` installs the CPython eval-frame callback and tracks hook-level counters
- shared Python logic from `selective_tracer`, `cache_manager`, `modify_bytecode`, and `debugger_integration` is reused rather than forked into an eval-frame-only policy layer
- the pure-Python fallback module re-exports the shared runtime symbols and mirrors the metadata helpers used by the compiled extension

The implementation is still deliberately incremental in one important sense: eval-frame remains a routing and activation layer that can choose fast-path execution or scoped debugger work at frame entry, while debugger events still flow through tracing once a frame is selected.

## Main Decisions

### Backend Selection Lives In One Place

`dapper._frame_eval.frame_eval_main.FrameEvalManager` remains the source of truth for backend choice.

- `FrameEvalConfig.backend` chooses between `auto`, `tracing`, and `eval_frame`
- `FrameEvalCompatibilityPolicy` decides whether eval-frame is available in the current runtime
- manager-level fallback decides whether explicit eval-frame requests fail fast or degrade to tracing

This prevents backend selection logic from being spread across debugger integration, runtime state, and low-level hook code.

### Eval-Frame Reuses Existing Debugger Policy

The eval-frame path does not maintain its own independent decision engine.

- breakpoint routing reuses selective-tracer analysis
- thread skip, debugger-internal state, and step-mode handling remain shared concepts
- debugger event delivery continues to go through the existing bridge and trace-callback machinery

The architectural rule is simple: eval-frame should decide whether a frame needs debugger work, not reinvent how debugger work is performed.

### The Cython Boundary Stays Narrow

`dapper._frame_eval._frame_evaluator.pyx` owns the interpreter-facing hook and code-extra helpers.

- install and uninstall of the CPython callback stay in Cython
- recursion guards and low-level hook bookkeeping stay in Cython
- higher-level routing, telemetry, invalidation, and debugger policy stay in Python

This split matters because it keeps the CPython-specific surface as small as possible while leaving most behavior testable from Python.

## Implemented Milestones

### Module Boundary Stabilization

The `_frame_evaluator` boundary is now stable enough to treat as an interface.

- `_frame_evaluator.py` re-exports shared runtime symbols from `_frame_evaluator_shared.py`
- `_frame_evaluator.pxd` exposes the public Cython declarations needed by consumers
- the compiled module still owns the concrete `ThreadInfo`, `FuncCodeInfo`, and `_FrameEvalModuleState` boundary
- thread-skip naming was normalized from `pydevd` terminology to `debugger_internal`

### Real Hook Lifecycle

The low-level hook is no longer a stub.

- a real eval-frame callback is installed on supported CPython builds
- install and uninstall are explicit operations
- exceptions inside the hook fall back to the previous evaluator rather than leaving the process in a half-hooked state
- hook stats expose slow-path attempts, activations, scoped trace installs, return events, and exception events

### Shared Decision Path

The routing contract is now shared between tracing and eval-frame.

- `selective_tracer.TraceDecision` defines the outcome vocabulary
- current routing outcomes are `skip`, `original`, and `breakpointed`
- conditional breakpoints, debugger-internal frames, and step-mode rules are reused rather than reimplemented

### Code-Extra And Cache Integration

Code-object metadata and fallback caches are integrated into one cache story.

- modified code is stored against the original `CodeType`
- code-extra metadata is the primary association mechanism when the compiled wrapper is available
- `CacheManager` remains the Python-side cache index and fallback lookup path
- breakpoint invalidation and global cache clearing clear both modified-code cache entries and associated code-extra metadata
- the pure-Python metadata fallback now uses weak-key storage so it does not keep code objects alive after garbage collection

The weak-key fallback is an important maintenance invariant. If the pure-Python path ever regresses to strong references again, it reintroduces the stale-reference and leak risk that this work closed.

### Bytecode Modification Contract

Breakpoint instrumentation is intentionally conservative.

- instrumentation is lazy by default, on the first `breakpointed` eval-frame decision
- modified-code caches are keyed by original code identity plus breakpoint fingerprint
- rollback paths clear partial state and record telemetry when injection or rebuild fails
- nested functions, generators, async functions, and module-level code now have focused coverage

### Debugger Integration And Fallback

Debugger integration flows through the shared bridge rather than a second control path.

- breakpoint updates reach both tracing state and eval-frame caches
- step-over, step-in, step-out, pause, and continue normalization are covered through shared thread-local state
- conditional-breakpoint fallback stays conservative and keeps behavior aligned with tracing
- backend-selection fallback logs are deduplicated to avoid repeated warnings during normal debugging

## Test And CI Coverage

The current repository includes the following coverage layers for frame-eval work.

- focused wrapper tests for code-extra helpers and compiled wrapper behavior
- unit coverage for manager selection, runtime state, hook lifecycle, invalidation, bytecode metadata, and fallback behavior
- integration coverage for breakpointed and non-breakpointed eval-frame paths
- CI smoke coverage that validates the compiled frame-eval extension is present

One practical nuance is worth preserving in tests: on interpreters where eval-frame is unavailable or not selected by policy, eval-frame-specific end-to-end tests should skip cleanly instead of failing by assuming `EvalFrameBackend` was chosen.

## Operational Invariants

Contributors touching this area should preserve these invariants.

### Hook Safety

- shutdown must uninstall the hook before runtime state and caches are torn down
- unexpected hook failures must return control to default evaluation
- repeated enable and disable cycles must start from a clean runtime state

### Cache Safety

- invalidation must clear both code-extra metadata and Python-side modified-code cache entries
- fallback metadata stores must not hold strong references to code objects longer than necessary
- stale modified-code metadata must not survive breakpoint changes, file reloads, or global cache clears

### Policy Sharing

- eval-frame should reuse selective-tracing and debugger policy where possible
- debugger-owned internal frames must remain skippable through shared thread-local state
- backend selection and fallback decisions should remain centralized in manager and compatibility-policy code

## Practical Verification

When debugging frame-eval changes, the most useful checks are:

- confirm which backend was actually selected through runtime status
- inspect hook stats to see whether slow-path activation occurred
- verify that breakpoint invalidation clears modified-code lookup state
- verify that unsupported runtimes fall back cleanly instead of forcing eval-frame assumptions into tests

## Historical Context

The original implementation checklist served as an execution plan while the backend was landing. That checklist is now effectively complete and has been superseded by this note plus the backend architecture document.

If new frame-eval work begins again, prefer adding narrow developer notes or targeted follow-up design docs here instead of reviving a long-running checkbox plan unless the work genuinely needs milestone tracking.