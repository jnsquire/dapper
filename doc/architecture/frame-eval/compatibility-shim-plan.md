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

- The extension currently builds only for Python 3.12 in package builds.
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

- CPython 3.12-3.14: primary shim family
- CPython 3.11: secondary family, likely needs custom frame/line access
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
- Replace the current 3.12-only package-build gate with a capability function
  that reflects implemented support
- Run compiled-extension smoke checks on every supported minor in CI

### Phase 5: 3.11 Decision Point

- Either implement a dedicated 3.11 compatibility branch for frame/line access
- Or explicitly keep 3.11 on tracing fallback only

Do not merge 3.11 into the main support claim without an explicit decision and
dedicated validation.

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