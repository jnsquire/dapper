# Dapper Improvement Checklist

Comprehensive checklist of identified issues, organized by severity and category.
Generated from a full codebase review on 2026-02-14.

## Architecture

- [ ] **Decompose `PyDebugger` god-class**
  - File: `dapper/adapter/server.py` — 1533 lines
  - ~30+ public methods handling launching, IPC, breakpoints, stack traces, variables, events, and shutdown.
  - Fix: Extract into focused managers (e.g., `LaunchManager`, `EventRouter`, `StateManager`, `BreakpointRouter`).
  - **Progress update (current branch):**
    - ✅ Extracted debug message/event handling into dedicated `_PyDebuggerEventRouter` in `dapper/adapter/server.py`.
    - ✅ Added explicit delegation methods on `PyDebugger` (`emit_event`, `resolve_pending_response`, `schedule_program_exit`, pending-command helpers) to reduce direct state coupling.
    - ✅ Extracted launch/attach/in-process startup orchestration into dedicated `_PyDebuggerLifecycleManager` in `dapper/adapter/server.py`.
    - ✅ Added lifecycle bridge methods on `PyDebugger` (`start_ipc_reader`, backend/bridge creators, stop-event await, IPC mode toggle, launch helpers) so extracted components avoid direct private-state mutation.
    - ✅ Extracted breakpoint/state-inspection operations into dedicated `_PyDebuggerStateManager` in `dapper/adapter/server.py` (`set_breakpoints`, `get_stack_trace`, `get_scopes`, `get_variables`, `set_variable`, `evaluate`).
    - ✅ Added bridge wrappers (`get_active_backend`, `get_inprocess_backend`, breakpoint processing/event helpers) to keep extracted components decoupled from private internals.
    - 🔜 Next chunk: move process/output/thread primitives (debuggee process startup, stream readers, termination orchestration) into a focused runtime manager.

- [ ] **Split `command_handlers.py` into domain modules**
  - File: `dapper/shared/command_handlers.py` — 1544 lines
  - All DAP command handler logic in a single file.
  - Fix: Split by domain: `breakpoint_handlers.py`, `variable_handlers.py`, `stepping_handlers.py`, `source_handlers.py`, etc.
  - **Progress update (current branch):**
    - ✅ Extracted source-domain logic into `dapper/shared/source_handlers.py` (`loadedSources`, `source`, `modules`, and source collection helpers).
    - ✅ Extracted breakpoint-domain logic into `dapper/shared/breakpoint_handlers.py` (`setBreakpoints`, `setFunctionBreakpoints`, `setExceptionBreakpoints` implementations).
    - ✅ Extracted stepping-domain logic into `dapper/shared/stepping_handlers.py` (`continue`, `next`, `stepIn`, `stepOut`, `pause` implementations).
    - ✅ Extracted variable/evaluation domain logic into `dapper/shared/variable_handlers.py` (`variables`, `setVariable`, `evaluate`, `setDataBreakpoints`, `dataBreakpointInfo` implementations).
    - ✅ Extracted stack/thread/scope domain logic into `dapper/shared/stack_handlers.py` (`stackTrace`, `threads`, `scopes` implementations).
    - ✅ Extracted lifecycle/exception command logic into `dapper/shared/lifecycle_handlers.py` (`exceptionInfo`, `configurationDone`, `terminate`, `initialize`, `restart` implementations).
    - ✅ Extracted remaining variable/conversion helper utilities into `dapper/shared/command_handler_helpers.py` and converted `dapper/shared/command_handlers.py` helper bodies to delegating wrappers.
    - ✅ Migrated selected downstream tests to direct domain-module imports (`source_handlers` / `variable_handlers`) instead of `command_handlers` internals.
    - ✅ Migrated source/exception integration test call sites to `source_handlers` / `lifecycle_handlers` and removed now-unused transitional source-collection wrappers from `command_handlers.py`.
    - ✅ Migrated additional integration command-path tests (`setBreakpoints`, `setFunctionBreakpoints`, `setExceptionBreakpoints`, stepping/pause, variables/evaluate, loaded-sources) to direct domain handlers.
    - ✅ Migrated remaining `_cmd_set_variable` integration assertions to direct `variable_handlers` calls with explicit response emission checks.
    - ✅ Removed internal-only `_handle_*` transitional wrappers from `command_handlers.py`; public `handle_*` and registry `_cmd_*` now delegate directly to domain modules.
    - ✅ Migrated all test imports off `command_handlers` conversion wrappers (`_convert_string_to_value`, `_convert_value_with_context`) to `value_conversion.convert_value_with_context`.
    - ✅ Migrated `_set_object_member` / `_set_scope_variable` test and integration consumers to `command_handler_helpers` with explicit dependency injection and removed these wrappers from `command_handlers.py`.
    - ✅ Removed remaining compatibility hooks (`_CONVERSION_FAILED`, `_try_custom_convert`, `extract_variables`) from `command_handlers.py` and migrated final tests to helper/value-conversion APIs.
    - ✅ Removed dead compatibility aliases/wrappers (`make_variable_object`, `_convert_string_to_value`, `_extract_variables_from_mapping`) from `command_handlers.py`; variable extraction now delegates directly to `command_handler_helpers`.
    - ✅ Kept compatibility surface in `dapper/shared/command_handlers.py` via delegating wrappers (`_cmd_loaded_sources`, `_cmd_source`, `_cmd_modules`, and legacy `handle_source`).
    - ✅ Kept existing public/back-compat `handle_*` call signatures in `dapper/shared/command_handlers.py` while simplifying internals to direct domain delegation.
    - ✅ Preserved command registry behavior and existing test imports while reducing monolith scope.
    - ✅ Removed temporary conversion-override plumbing (`_convert_value_with_context_override`) after confirming no remaining test/runtime dependency.
    - ✅ Removed legacy `handle_source` compatibility wrapper from `dapper/shared/command_handlers.py` and migrated remaining tests to `source_handlers.handle_legacy_source`.
    - ✅ Removed legacy lifecycle `handle_*` wrapper exports from `dapper/shared/command_handlers.py` (`handle_initialize`, `handle_terminate`, `handle_configuration_done`, `handle_restart`, `handle_exception_info`) and switched registry handlers/tests to domain implementations.
    - ✅ Removed stack-domain `handle_*` wrapper exports from `dapper/shared/command_handlers.py` (`handle_stack_trace`, `handle_threads`, `handle_scopes`) and migrated tests to `stack_handlers`.
    - ✅ Removed stepping and breakpoint `handle_*` wrapper exports from `dapper/shared/command_handlers.py` (`handle_continue`, `handle_next`, `handle_step_in`, `handle_step_out`, `handle_pause`, `handle_set_breakpoints`, `handle_set_function_breakpoints`, `handle_set_exception_breakpoints`) and migrated tests to `stepping_handlers` / `breakpoint_handlers`.
    - ✅ Removed remaining variable/evaluate/data-breakpoint `handle_*` wrapper exports from `dapper/shared/command_handlers.py` (`handle_variables`, `handle_set_variable`, `handle_evaluate`, `handle_set_data_breakpoints`, `handle_data_breakpoint_info`) and migrated tests to `variable_handlers` with explicit dependency injection where needed.
    - ✅ Moved setVariable orchestration composition out of `dapper/shared/command_handlers.py` into `variable_handlers.handle_set_variable_command_impl`, leaving `command_handlers` as dispatch-only for this command.
    - ✅ Extracted variable-command runtime glue into `dapper/shared/variable_command_runtime.py` and switched `command_handlers` to use this adapter for variable-resolution and setVariable dependency wiring.
    - ✅ Removed remaining `command_handlers` shim helpers (`_make_variable`, `_resolve_variables_for_reference`) and migrated tests to runtime-adapter-backed helpers in domain-level test setup.
    - ✅ Removed `_convert_value_with_context` helper from `dapper/shared/command_handlers.py`, switched setVariable dependency wiring to `value_conversion.convert_value_with_context`, and migrated remaining tests off the removed helper.
    - ✅ Moved evaluation error formatting out of `dapper/shared/command_handlers.py` into `variable_handlers.format_evaluation_error` and migrated runtime/test call sites.
    - ✅ Extracted `_safe_send_debug_message` transport-guard implementation out of `dapper/shared/command_handlers.py` into `command_handler_helpers.build_safe_send_debug_message` while preserving monkeypatch/test behavior via dynamic sender resolution.
    - ✅ Moved `_error_response` implementation out of `dapper/shared/command_handlers.py` into `command_handler_helpers.error_response` while keeping `_error_response` alias compatibility for existing tests and call sites.
    - ✅ Moved thread-id/stepping glue logic into `command_handler_helpers` (`get_thread_ident`, `set_dbg_stepping_flag`) while preserving compatibility aliases in `command_handlers.py` for existing tests and call sites.
    - ✅ Final internal polish: removed redundant `_get_threading_module` indirection and switched setVariable dependency wiring to shared `command_handler_helpers.error_response` while preserving compatibility aliases used by tests.
    - 🔜 Next chunk: optional cleanup is now mostly cosmetic (further alias collapse in `command_handlers.py`) since behavior lives in domain/helper modules.

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

- [x] **`BreakpointCache._access_order` uses list with O(n) removal** ✅
  - File: `dapper/_frame_eval/cache_manager.py`
  - Fix: Replaced list-based LRU tracking with `OrderedDict`-backed access ordering and updated all read/write/eviction/clear/remove paths to O(1)-style key operations.
  - Validation: previously failing frame-eval cache/tracer test cases now pass after the refactor cleanup.

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


- [ ] **`DebuggerLike` Protocol has ~30+ required attributes**
  - File: `dapper/protocol/debugger_protocol.py`
  - Includes private attributes like `_data_watches`, `_frame_eval_enabled`, `_mock_user_line`. Nearly impossible to create test doubles.
  - Fix: Split into smaller sub-protocols. Remove private attributes from the public Protocol.



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
| Performance        | 4          |
| Code Quality       | 2          |
| Test Coverage      | 5          |
| **Total**          | **15**     |

**Next up:** Performance improvements (4 items).
