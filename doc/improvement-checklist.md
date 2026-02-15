# Dapper Improvement Checklist

Comprehensive checklist of identified issues, organized by severity and category.
Generated from a full codebase review on 2026-02-14.

## Architecture

- [ ] **Decompose `PyDebugger` god-class**
  - File: `dapper/adapter/server.py` — 1533 lines
  - ~30+ public methods handling launching, IPC, breakpoints, stack traces, variables, events, and shutdown.
  - Fix: Extract into focused managers (e.g., `LaunchManager`, `EventRouter`, `StateManager`, `BreakpointRouter`).

- [ ] **Split `command_handlers.py` into domain modules**
  - File: `dapper/shared/command_handlers.py` — 1544 lines
  - All DAP command handler logic in a single file.
  - Fix: Split by domain: `breakpoint_handlers.py`, `variable_handlers.py`, `stepping_handlers.py`, `source_handlers.py`, etc.

- [ ] **Reduce compatibility property sprawl in `DebuggerBDB`**
  - File: `dapper/core/debugger_bdb.py` (~L100–310)
  - 50+ lines of compatibility properties proxying attributes to delegates. Defeats the purpose of component extraction.
  - Fix: Update callers to access delegate objects directly.

- [ ] **Replace global `SessionState` singleton with explicit session composition**
  - Files: `dapper/shared/debug_shared.py`, `dapper/shared/command_handlers.py`, `dapper/ipc/ipc_receiver.py`, `dapper/launcher/debug_launcher.py`
  - Problem: `SessionState` currently mixes transport lifecycle, debugger lifecycle, command dispatch/provider registry, and source-reference catalog in one mutable global object (`state`).
  - Impact: API leakage across modules, heavy test coupling (`reset()` + subclassing), implicit runtime dependencies, and brittle global mutation during lifecycle transitions.
  - **Target architecture:**
    - Introduce a composed `DebugSession` object created at launcher startup and passed to modules that need session context.
    - Split responsibilities into focused services:
      - `SessionTransport` (IPC channels + send/receive + channel guards)
      - `SourceCatalog` (sourceReference mapping + content lookup)
      - `CommandDispatcher` (provider registration + dispatch + command-level response shaping)
      - `ProcessControl` (exit/exec hooks for terminate/restart)
  - **Migration plan (detailed):**
   1. **Define service interfaces and composed session model**
     - Add lightweight Protocols/ABCs for transport, source catalog, dispatcher, and process control.
     - Add `DebugSession` dataclass/object that composes those services and stores debugger/session flags.
     - Keep constructors dependency-injection friendly (accept concrete implementations + test doubles).
   2. **Introduce compatibility facade (no behavioral changes)**
     - Keep existing module-level `state` and `send_debug_message` as thin delegating wrappers over a default `DebugSession` instance.
     - Mark direct `state.<field>` usage as transitional in docs and internal comments.
     - Preserve `SessionState.reset()` semantics temporarily by reinitializing the default composed session.
   3. **Move source-reference responsibilities first**
     - Migrate `get_ref_for_path`, `get_or_create_source_ref`, `get_source_meta`, and content lookup into `SourceCatalog`.
     - Update source-related handlers to depend on `session.sources` rather than the global mutable dicts.
     - Add parity tests to lock current behavior for `sourceReference` and path fallback.
   4. **Move command-provider registry and dispatch**
     - Relocate provider registration/unregistration and dispatch/error-response logic to `CommandDispatcher`.
     - Update IPC receiver/launcher command paths to dispatch through injected session dispatcher.
     - Add tests for provider ordering, failure isolation, and response-shaping parity.
   5. **Move transport send/validate logic**
     - Replace global `send_debug_message` internals with `SessionTransport.send(event_type, payload)`.
     - Encapsulate `require_ipc` and write-channel checks in transport service; remove direct channel field checks from handlers.
     - Preserve event-emitter hooks via transport-level publish/subscribe API.
   6. **Move process lifecycle hooks**
     - Extract restart/terminate cleanup (`exit_func`, `exec_func`, IPC closure, thread handling) into `ProcessControl`.
     - Keep command handlers as orchestration-only call sites (`session.process_control.restart(...)`).
     - Add focused tests for cleanup order and idempotency.
   7. **Flip call sites to explicit session dependency**
     - Update launcher setup to build a concrete `DebugSession` and pass it to receivers/handlers/dispatcher.
     - Remove direct imports of global `state` where constructor or function injection is feasible.
     - Keep wrappers only for legacy entry points and tests during transition.
   8. **Deprecate and remove compatibility layer**
     - Once call-site migration completes, remove mutable singleton internals and keep a minimal default-session accessor.
     - Convert remaining tests from singleton reset/subclassing to explicit session fixtures.
     - Remove dead `SessionState` fields that became service internals.
  - **Validation checklist:**
   - Existing command behavior remains wire-compatible (responses/events unchanged).
   - Restart/terminate resource cleanup remains correct under IPC pipe/socket modes.
   - Source lookup behavior (`sourceReference`, `path`, provider hooks) remains parity-stable.
   - Tests no longer require test-only `SessionState` subclasses for common setup.
  - **Status update (implemented in current branch):**
    - ✅ Added composed session internals in `dapper/shared/debug_shared.py`: `DebugSession`, `SessionTransport`, `SourceCatalog`, `CommandDispatcher`, `ProcessControl`.
    - ✅ Kept compatibility surface (`SessionState`, module-level `state`, `send_debug_message`) as delegating facade over composed services.
    - ✅ Moved source-reference storage/lookup and provider dispatch internals behind dedicated service objects while preserving existing call signatures.
    - ✅ Preserved `SessionState.reset()` singleton semantics for tests and legacy call paths.
    - ✅ Added context-local session injection primitives (`use_session`, `get_active_session`, `active_state`) and wired explicit session parameters through launcher/receiver/handler entrypoints.
    - 🔜 Remaining: migrate remaining modules that still import global `state` directly so full non-singleton session instances can be used end-to-end without compatibility shims.

---

## Performance

- [x] **Dispatch tables rebuilt on every `_execute_command` call** ✅
  - Files: `dapper/adapter/external_backend.py`, `dapper/adapter/inprocess_backend.py`
  - Fix: Introduced an instance-level `self._dispatch_map` (built in `__init__`) and updated `BaseBackend._execute_command` to prefer it. Legacy `_build_dispatch_table` retained for back-compat.
  - Tests: `tests/unit/test_critical_bug_regressions.py::test_dispatch_map_reused_and_build_not_called`, `tests/integration/test_inprocess_mode.py::test_inprocess_dispatch_map_reused_and_build_not_called`.

- [ ] **`BreakpointCache._access_order` uses list with O(n) removal**
  - File: `dapper/_frame_eval/cache_manager.py` (~L659)
  - On every access, `.remove(filepath_str)` scans the full list.
  - Fix: Use `OrderedDict` (already imported) instead of a list.

- [ ] **Busy-wait spin loop for event loop readiness**
  - File: `dapper/ipc/sync_adapter.py` (~L47)
  - `while self._loop is None: pass` spins the CPU.
  - Fix: Use `threading.Event` for synchronization.

- [ ] **Cache key uses `id()` which can be reused after GC**
  - File: `dapper/_frame_eval/modify_bytecode.py` (~L221)
  - `_get_cache_key` uses `id(code_obj)`. After GC, a new object may reuse the same ID, returning stale cached bytecode.
  - Fix: Use a stable key (e.g., `(code_obj.co_filename, code_obj.co_name, code_obj.co_firstlineno)`).

- [ ] **`clear_line_meta_for_file` uses O(n) scan**
  - File: `dapper/core/breakpoint_manager.py` (~L86)
  - `[k for k in self.line_meta if k[0] == path]` iterates all breakpoint metadata.
  - Fix: Use a nested `dict[str, dict[int, ...]]` keyed by path for O(1) lookup.

- [ ] **Non-thread-safe protocol sequence counter**
  - File: `dapper/protocol/protocol.py` (~L57)
  - `ProtocolFactory.seq_counter` is a plain integer with no locking. Concurrent message creation produces duplicate sequence numbers.
  - Fix: Use `itertools.count()` or `threading.Lock`.

---

## Code Quality

- [x] **Missing type hints on public methods** ✅
  - Files:
    - `dapper/core/debugger_bdb.py` — annotated `record_breakpoint`, `clear_break_meta_for_file`, `set_custom_breakpoint`, `clear_custom_breakpoint`.
    - `dapper/core/debug_helpers.py` — added return types for `get_int`, `get_str`.
    - `dapper/ipc/ipc_context.py` — replaced broad `Any` IPC field typing with concrete socket/pipe/file aliases and typed method parameters.
  - Validation: test suite passes after changes.

- [ ] **`DebuggerLike` Protocol has ~30+ required attributes**
  - File: `dapper/protocol/debugger_protocol.py`
  - Includes private attributes like `_data_watches`, `_frame_eval_enabled`, `_mock_user_line`. Nearly impossible to create test doubles.
  - Fix: Split into smaller sub-protocols. Remove private attributes from the public Protocol.


- [x] **`handle_source` ignores `sourceReference`** ✅
  - File: `dapper/shared/command_handlers.py`
  - Fix: Legacy `handle_source` now resolves `sourceReference` via `state.get_source_content_by_ref` and falls back to `path` lookup. Added integration test `test_handle_source_resolves_sourceReference_from_state`.

- [ ] **Add pluggable source-content hook with URI-aware path handling**
  - Files: `dapper/shared/debug_shared.py`, `dapper/shared/command_handlers.py`, `dapper/protocol/debugger_protocol.py` (optional typing-only additions)
  - Goal: Allow callers to provide additional source content (remote/editor/generated) based on DAP `source.path` while preserving existing `sourceReference` behavior.
  - Protocol note: DAP `Source.path` may be a filesystem path or URI; non-filesystem content can also be represented via `sourceReference`.
  - **Implementation plan (detailed):**
   1. **Define provider contract (PEP 544 style)**
     - Add a small `Protocol`/callable type for providers: input `path_or_uri: str`, output `str | None`.
     - Keep this in `debug_shared.py` (runtime registry) and optionally mirror as a typing-only helper in `debugger_protocol.py`.
   2. **Add SessionState provider registry API**
     - Add `register_source_provider(provider) -> int`, `unregister_source_provider(provider_id) -> bool`.
     - Store providers in insertion order with stable IDs and guard with a lock (`threading.RLock`) for thread-safety.
     - Ensure unregister is idempotent/safe when IDs are missing.
   3. **Add URI normalization utility**
     - Implement helper to detect URI vs path (`urllib.parse.urlparse`).
     - Convert `file://` URIs to local paths for disk fallback (`urllib.request.url2pathname`).
     - Preserve non-`file` URIs (e.g., `vscode-remote://`, `git:`) for provider resolution.
   4. **Integrate lookup flow into source resolution**
     - Update `SessionState.get_source_content_by_path` to: providers first → normalized disk fallback for local files.
     - Update legacy `handle_source` to reuse state helpers and avoid duplicate path/URI logic.
     - Keep precedence clear: explicit `sourceReference` lookup remains first, then path/URI provider fallback.
   5. **Error handling + observability**
     - Provider exceptions must be isolated (log + continue to next provider), never fail the whole request.
     - Add debug-level logs for provider hits/misses to aid diagnostics.
   6. **Test plan (unit + integration)**
     - Unit tests for register/unregister lifecycle and thread-safe behavior.
     - Unit tests for `file://` normalization and non-`file` URI pass-through.
     - Integration tests for `handle_source` returning provider-backed content by URI/path.
     - Regression tests to confirm existing `sourceReference` and local-path behavior remain unchanged.

- [x] **Singleton `SessionState` has no `reset()` method** ✅
  - File: `dapper/shared/debug_shared.py`
  - Fix: Added `SessionState.reset()` classmethod that reinitializes all mutable singleton fields in-place while preserving singleton identity.
  - Tests: `tests/unit/test_session_state_reset.py`.


- [x] **Frame eval `types.py` stubs are runtime-callable but raise** ✅
  - Files: `dapper/_frame_eval/types.py`, `dapper/_frame_eval/types.pyi`
  - Fix: Moved typing declarations to a new `.pyi` stub and replaced runtime ellipsis stubs with concrete implementations/wrappers (Cython-backed when available, safe Python fallback otherwise).
  - Tests: `tests/unit/test_frame_eval_types_runtime.py`.

---

## Test Coverage

Overall: **36.8% line coverage / 14.5% branch coverage** (1120 tests, 120 files).

- [ ] **Increase IPC layer coverage**
  - `dapper/ipc/transport_factory.py`, `dapper/ipc/connections/`, `dapper/ipc/sync_adapter.py` are undertested.

- [ ] **Increase frame evaluation coverage**
  - `dapper/_frame_eval/modify_bytecode.py`, `dapper/_frame_eval/selective_tracer.py`, `dapper/_frame_eval/frame_tracing.py` need dedicated tests.

- [ ] **Increase launcher coverage**
  - `dapper/launcher/debug_launcher.py`, `dapper/launcher/launcher_ipc.py` lack unit tests.

- [ ] **Increase branch coverage to ≥50%**
  - Error paths and edge cases are largely untested. Focus on conditional branches in `debugger_bdb.py`, `server.py`, and `command_handlers.py`.

- [ ] **Add integration tests for end-to-end DAP sessions**
  - Test full launch → set breakpoints → continue → hit breakpoint → inspect variables → disconnect flow.

---

## Summary

| Category           | Open Items |
|--------------------|------------|
| Architecture       | 4          |
| Performance        | 5          |
| Code Quality       | 2          |
| Test Coverage      | 5          |
| **Total**          | **16**     |

**Next up:** Code quality improvements (2 items).
