# Frame Eval Backend Architecture

This note describes the current frame-eval backend architecture, how backend selection works, and when Dapper falls back to tracing.

## Scope

The current implementation provides two backend families:

- `tracing`, which routes debugger events through `sys.settrace` or `sys.monitoring`
- `eval_frame`, which installs a CPython eval-frame callback and uses a scoped trace function only for frames that need debugger intervention

The eval-frame path is real, but it is still an incremental backend. It does not yet swap between original and breakpoint-instrumented code objects at frame entry. Once a frame is selected, debugger events are still delivered through scoped tracing.

## Main Components

### `FrameEvalManager`

`dapper._frame_eval.frame_eval_main.FrameEvalManager` is the top-level coordinator.

- Validates and stores `FrameEvalConfig`
- Consults `FrameEvalCompatibilityPolicy`
- Selects either a tracing backend or `EvalFrameBackend`
- Initializes `FrameEvalRuntime`
- Shuts down the active backend and runtime in the correct order

This keeps backend selection in one place rather than letting each caller make its own compatibility or fallback decision.

### `FrameEvalBackend`

`dapper._frame_eval.backend.FrameEvalBackend` is the common protocol for frame-eval backends.

- `TracingBackend` now subclasses it
- `EvalFrameBackend` implements the same install, shutdown, breakpoint, stepping, and exception-breakpoint control surface

That shared surface lets the manager and debugger integration layer treat backend selection as a runtime choice instead of a separate control path.

### `EvalFrameBackend`

`dapper._frame_eval.eval_frame_backend.EvalFrameBackend` owns the high-level eval-frame control path.

- Installs or uninstalls the low-level hook
- Stores breakpoint state used by the eval-frame decision path
- Mirrors breakpoint updates into the existing selective-tracing store
- Tracks stepping mode in the shared per-thread state
- Normalizes exception-breakpoint filters
- Registers the debugger trace callback used when the slow path activates

The backend deliberately reuses existing tracing-side structures where possible. The current implementation is meant to prove backend wiring and event delivery before code-object replacement and cache-extra machinery land.

### Low-Level Hook

`dapper._frame_eval._frame_evaluator` and `dapper._frame_eval._frame_evaluator.pyx` own the interpreter-facing hook logic.

- The Cython layer installs the CPython eval-frame callback
- Per-thread state prevents recursive re-entry
- The hook inspects the current code object and line
- If the frame does not need debugger attention, evaluation falls through to the interpreter's normal evaluator
- If the frame does need debugger attention, the hook enables a scoped trace function for that code object and lets default evaluation continue

This keeps CPython-specific logic in the Cython boundary while leaving policy and debugger behavior in the Python backend and manager layers.

## Backend Selection

Backend selection is driven by `FrameEvalConfig.backend`.

- `auto` prefers eval-frame when `FrameEvalCompatibilityPolicy.can_use_eval_frame(...)` reports the full environment as eligible
- `eval_frame` requests the eval-frame backend explicitly
- `tracing` forces the legacy tracing family

When tracing is selected, `FrameEvalConfig.tracing_backend` still chooses between `sys.monitoring`, `settrace`, or `auto` within that family.

### Why `eval_frame` Exists Alongside `sys.monitoring`

`sys.monitoring` and `eval_frame` both reduce the cost of always-on `sys.settrace`, but they operate at different control points.

- `sys.monitoring` is a tracing backend. It improves how events are delivered once monitoring is active.
- `eval_frame` is a frame-entry router. It decides whether a frame should enter debugger work at all before the normal tracing path is engaged for that frame.

That distinction matters because Dapper's long-term design needs a place to choose among three outcomes at frame entry:

- keep running the original frame untouched,
- activate scoped debugger tracing for the frame,
- or run a breakpoint-aware modified code object.

`sys.monitoring` is useful for the second outcome. `eval_frame` is the only backend family here that naturally owns the first decision point and can later absorb the third.

So the current recommendation is pragmatic:

- prefer `sys.monitoring` when you want a simpler tracing backend on Python 3.12+;
- prefer `eval_frame` when you want the architecture that best matches Dapper's future frame-selection and code-selection model, and your runtime is compatible with the CPython hook.

## Fallback Model

Fallback is intentionally conservative.

### Selection-Time Fallback

If eval-frame is requested but not supported, the manager falls back to a tracing backend when configuration allows it.

Common reasons include:

- the compiled extension is unavailable
- the compatibility policy reports eval-frame support as unavailable for the current interpreter or environment
- eval-frame backend creation raises during initialization
- another debugger, coverage tool, or known conflicting environment marker is already active

When fallback is allowed, manager logging is intentionally deduplicated for consecutive identical reasons so repeated setup attempts do not flood normal debugging sessions with the same warning.

### Runtime Fallback Inside The Hook

The low-level hook also falls back defensively.

- Recursive eval-frame entry returns control to the previous evaluator immediately
- Frames that are not fully initialized, are debugger-internal, or are marked to skip never enter the slow path
- If the hook itself raises unexpectedly, control returns to the interpreter's default evaluator instead of leaving the process half-hooked
- If no trace callback is registered for the current thread, the hook can still fall back to normal evaluation

This means the current eval-frame backend is additive: it opts into scoped debugger work for selected frames, but it does not replace the interpreter's normal evaluator on error.

### Shutdown And Recovery

Shutdown removes the eval-frame hook before clearing thread-local trace state and backend bookkeeping.

That order matters because it avoids leaving a hook installed after the manager believes frame evaluation is disabled.

Runtime shutdown also resets condition-evaluator settings and runtime config back to defaults so repeated enable-disable cycles start from a clean state.

## Current Decision Path

Today the hook makes a line-oriented decision based on shared breakpoint state.

- If the current executable line is breakpointed, the frame takes the slow path
- If the function contains a breakpoint and the thread is in step mode, the frame also takes the slow path
- Otherwise the frame stays on the interpreter fast path

This is sufficient for the current backend integration and end-to-end tests, but it is not yet the final decision engine described in the implementation checklist. Reusing the richer selective-tracer analysis and code-object caching remains follow-on work.

## Observability

Runtime status and hook stats are the primary diagnostics surfaces.

- `FrameEvalRuntime.get_status()` reports the active backend type and whether the hook is installed
- `FrameEvalRuntime.get_stats()` reports hook counters such as `slow_path_attempts`, `slow_path_activations`, `scoped_trace_installs`, `return_events`, and `exception_events`

These counters are the easiest way to confirm that eval-frame is active without guessing from debugger behavior alone.

## Relationship To Selective Tracing

The current eval-frame backend does not replace selective tracing. It narrows when selective tracing is activated.

- Tracing backends still provide the baseline debugger behavior
- Eval-frame decides whether a frame should enter the debugger path at frame entry
- Once a frame is selected, debugger callbacks still flow through the tracing machinery

That is why the current architecture should be read as a backend-routing and scoped-activation improvement, not as a complete bytecode-replacement design yet.

## Follow-On Work

The main unfinished architecture items are:

- reuse shared frame-decision logic instead of the current line-based hook check
- integrate code-extra storage and cache invalidation
- choose original versus modified code objects at frame entry
- harden automatic fallback behavior across more incompatible environments
- validate the compiled wrapper path in CI