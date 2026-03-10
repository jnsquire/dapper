# Frame-Eval CPython Compatibility Shim Plan

This note records the compatibility-shim direction for the compiled
`dapper._frame_eval._frame_evaluator` extension.

## Goal

Keep one Cython implementation for the frame-eval extension while isolating
CPython minor-version differences behind a narrow compatibility layer.

This does not aim for a stable `abi3` extension. The eval-frame backend depends
on CPython internal and unstable APIs, so we should expect per-minor compiled
artifacts even when the source stays unified.

## Current State

- The extension currently builds for Python 3.11 and 3.12 in package builds.
- The main Cython module still depends on CPython internal frame APIs, but the
  declarations and symbol selection are now concentrated in
  `dapper/_frame_eval/cpython_compat.pxd`.
- Phase 1 extracted the code-extra symbol mapping into
  `dapper/_frame_eval/cpython_compat.pxd`.
- Phase 2 extracted eval-frame hook control and frame-access declarations into
  `dapper/_frame_eval/cpython_compat.pxd`.

## Compatibility Families

Treat CPython support as version families rather than one undifferentiated
"all supported versions" target.

- CPython 3.11-3.12: currently implemented compiled-backend families
- CPython 3.13-3.14: follow-on shim family for Phase 4
- CPython 3.9-3.10: legacy family, may remain tracing-only unless a separate
  implementation is justified

## Shim Surface

The compatibility layer should eventually own all version-dependent access to:

- eval-frame hook get/set operations
- current frame code extraction
- current frame line extraction
- frame object extraction
- code-extra request/get/set operations
- capability detection for the active Python minor

The long-term intent is for `_frame_evaluator.pyx` to consume only that shim
surface and stop including CPython-version logic inline.

## Phase Breakdown

### Phase 1: Code-Extra Extraction

Status: completed

- Move code-extra symbol aliasing to `cpython_compat.pxd`
- Keep exported Python helpers unchanged:
  - `_PyEval_RequestCodeExtraIndex`
  - `_PyCode_SetExtra`
  - `_PyCode_GetExtra`
  - `_get_code_extra_metadata`
  - `_store_code_extra_metadata`
  - `_clear_code_extra_metadata`
- Validate with compiled-extension smoke and code-extra focused tests

### Phase 2: Eval-Frame Hook Shims

Status: completed

- Extract interpreter hook get/set calls behind the compatibility layer
- Refactor install/uninstall helpers to stop using raw CPython symbols directly
- Preserve diagnostics such as `_get_current_eval_frame_address`

### Phase 3: Frame Access Shims

Status: completed for the current 3.12 path

- Extract frame code lookup
- Extract line-number lookup
- Extract frame-object lookup
- Keep `_should_trace_code_for_eval_frame_impl` and
  `get_bytecode_while_frame_eval` focused on Dapper logic rather than CPython
  minor-version details

### Phase 4: 3.12-3.14 Support Matrix

- Make the compiled extension work across 3.12, 3.13, and 3.14
- Replace the current 3.11-3.12 package-build gate with a capability function
  that reflects implemented support
- Run compiled-extension smoke checks on every supported minor in CI

### Phase 5: 3.11 Decision Point

Status: planned

Implement a dedicated 3.11 compatibility branch rather than folding 3.11 into
the main 3.12-3.14 path.

Rationale:

- 3.11 sits on the first CPython release with inline bytecode caches and the
  modern `co_exceptiontable` layout, so bytecode instrumentation already needs
  version-specific handling.
- The eval-frame path also depends on unstable/internal frame APIs whose symbol
  availability and struct-access patterns differ from the 3.12+ family.
- Previous CI failures showed that at least one assumed 3.12+ symbol,
  `PyUnstable_InterpreterFrame_GetLine`, is not safe to treat as universally
  available on 3.11 builds.

Do not merge 3.11 into the main support claim without completing the dedicated
3.11 branch and validating it independently in CI.

#### Phase 5A: Capability Baseline

- [x] Introduce a single compatibility capability function for the compiled
  module.
- [x] Report support for eval-frame hook install/uninstall.
- [x] Report support for interpreter-frame code access.
- [x] Report support for interpreter-frame line access.
- [x] Report support for frame-object extraction suitable for synthetic event
  dispatch.
- [x] Keep `setup.py` gated to 3.12-only until this capability function is
  wired into both build-time and runtime checks.
- [x] Add an explicit runtime reason string for unsupported 3.11 capability
  gaps so fallback-to-tracing behavior is observable in tests and logs.

#### Phase 5B: 3.11 Frame/Line Access Shim

- [x] Move all 3.11-specific frame access into `cpython_compat.pxd`.
- [x] Add a 3.11 branch for code extraction from `_PyInterpreterFrame`.
- [x] Add a 3.11 branch for line-number lookup.
- [x] Add a 3.11 branch for frame-object lookup.
- [x] Keep `_frame_evaluator.pyx` free of direct Python-minor branching.
- [x] Preserve `_get_current_eval_frame_address`.
- [x] Preserve `get_eval_frame_hook_status`.
- [x] Preserve `_should_trace_code_for_eval_frame`.

#### Phase 5C: 3.11 Hook Installation Validation

- [x] Verify that the eval-frame get/set path used on 3.12+ is valid on 3.11.
- [x] If 3.11 requires different symbol resolution or header visibility,
  isolate that difference in the compatibility layer instead of changing the
  backend logic.
- [x] Restore the low-level install/uninstall tests for 3.11 only after the
  hook pointer-change test passes against a real compiled 3.11 build.

Local validation note:

- Verified locally with a compiled `.venv311` editable install plus the core
  hook lifecycle tests: idempotent install/uninstall and pointer-change
  restoration both passed under CPython 3.11.

#### Phase 5D: 3.11 Event-Dispatch Stabilization

- [x] Revalidate how synthetic `call`, `line`, `return`, and `exception`
  events are dispatched when the eval-frame path activates on 3.11.
- [x] Confirm that `frame.frame_obj` or the 3.11 equivalent is safe for
  dispatch.
- [x] Do not rely on `PyThreadState_GetFrame()` if it points at the caller
  frame in this hook context.
- [x] Keep the `inside_frame_eval` reentry guard semantics identical to 3.12+
  so the shared selective-tracer logic does not fork unnecessarily.

Validation note:

- Local compiled 3.11 validation covered direct dispatch helpers, live
  call/line/return and exception routing, debugger breakpoint routing, and the
  thread skip / `inside_frame_eval` guard behavior.
- The only 3.11-specific regression encountered in this phase was a duplicate
  synthetic `return` event; the backend now suppresses the extra synthetic
  return when the scoped trace already observed a natural return event.

#### Phase 5E: 3.11 Bytecode/Metadata Validation

- [x] Reuse the existing 3.11-aware bytecode helpers for inline `CACHE`
  instructions and code-object reconstruction.
- [x] Add compiled-backend tests proving that metadata storage,
  modified-code lookup, and lazy instrumentation all behave correctly under a
  real 3.11 extension build.
- [x] Treat any 3.11-only bytecode mismatch as a blocker even if the hook
  itself installs successfully.

Validation note:

- Local compiled 3.11 validation passed for code-extra metadata round-trip,
  metadata version mismatch handling, modified-code cache invalidation,
  lazy instrumentation, breakpoint bytecode injection/removal, and generator /
  module-level reconstruction paths.

#### Phase 5F: Build and CI Rollout

- [x] Expand `_supports_frame_eval_extension()` only after Phases 5A-5E pass.
- [x] Add a dedicated compiled-extension smoke check on Python 3.11 in both CI
  workflows before enabling broader 3.11 eval-frame assertions.
- [x] Re-enable the 3.11 extension import smoke test in CI.
- [x] Re-enable the 3.11 hook lifecycle tests in CI.
- [x] Re-enable the 3.11 metadata version mismatch test in CI.
- [x] Re-enable the 3.11 eval-frame end-to-end breakpoint dispatch test in CI.

Rollout note:

- CI now builds the compiled frame-eval extension on Python 3.11 and runs the
  validated smoke, hook lifecycle, metadata mismatch, and end-to-end
  breakpoint dispatch tests as part of the standard compiled-backend rollout.

#### Phase 5G: User-Facing Policy Update

- [x] Update the frame-eval guide to state that 3.11 supports `eval_frame`
  only after the compiled backend is validated, rather than inferring support
  from the generic compatibility-policy Python range.
- [x] Keep `backend: "auto"` as the recommended first rollout mode on 3.11.
- [x] Preserve tracing fallback for explicit incompatibilities such as coverage
  tools or unsupported environments.

#### Phase 5 Exit Criteria

- [x] The compiled extension builds and imports on CPython 3.11 in CI.
- [x] `install_eval_frame_hook()` and `uninstall_eval_frame_hook()` change and
  restore the interpreter eval-frame pointer on 3.11.
- [x] Eval-frame end-to-end breakpoint dispatch passes on 3.11 without
  synthetic event misrouting.
- [x] Metadata and lazy bytecode instrumentation tests pass on 3.11.
- [x] `setup.py`, runtime capability checks, and docs all agree that 3.11 is
  now a supported compiled eval-frame target.

#### Fallback Rule

If any of the following remain unresolved, keep 3.11 tracing-only and document
that as the intended behavior rather than shipping partial support:

- [x] no stable 3.11 line-access path
- [x] hook installation works but event dispatch misroutes frames
- [x] compiled import succeeds but modified-code / metadata handling is
  unreliable
- [x] CI requires per-test skips that indicate the backend is not
  operationally equivalent to the 3.12 path

### Phase 6: 3.9-3.10 Decision Point

- Evaluate whether a legacy eval-frame implementation is worth maintaining
- If not, document tracing fallback as the intended behavior

Do not let 3.9-3.10 block the primary 3.12-3.14 shim work.

## Acceptance Criteria

- `_frame_evaluator.pyx` no longer embeds CPython symbol aliasing directly
- Future hook/frame access differences are implemented in the compatibility
  layer, not scattered through the main Cython module
- Exported compiled-module helpers remain stable for current tests and callers
- Unsupported interpreter minors fail gracefully into tracing rather than build
  or import errors

## Notes

- Editor diagnostics may not resolve Cython `cimport` from local `.pxd` files
  even when the real Cython build succeeds. Treat the package build as the
  authoritative check until tooling support improves.