# Dapper Improvement Checklist

Comprehensive checklist of identified issues, organized by severity and category.
Generated from a full codebase review on 2026-02-14.

## Architecture

- [x] **Replace global `SessionState` singleton with explicit session composition**
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
    - ✅ Completed low-risk migration off direct singleton assumptions in targeted tests (`tests/integration/test_data_breakpoint_subprocess.py`, stale singleton comments in `tests/unit/test_source_references.py` and `tests/unit/test_request_handlers.py`).
    - ✅ Completed medium-risk test migration to explicit `DebugSession` fixtures while preserving behavior (`tests/integration/test_command_providers.py`, `tests/unit/test_send_debug_message.py`, `tests/unit/test_source_reference_helpers.py`, `tests/unit/test_session_state_start_command_receiver.py`).
    - ✅ Replaced runtime `SessionState` typing mentions in `dapper/shared/source_handlers.py` with `DebugSession` typing.
    - ✅ Replaced `ipc_receiver` sender monkeypatch seam with explicit injectable error sender hooks and migrated integration tests to injected callbacks (`tests/integration/test_ipc_receiver.py`, `tests/integration/test_debug_adapter_comm.py`).
    - ✅ Non-contract singleton assumptions removed from integration and unit coverage.
    - ✅ Removed legacy `SessionState`/`SessionProxy` compatibility layer and deleted obsolete compatibility-contract test (`tests/unit/test_session_state_reset.py`).
  - **Recommended order (next steps):**
    1. [x] Migrate remaining low-risk tests from direct `debug_shared.state` reads to explicit `DebugSession` fixtures (`tests/integration/test_data_breakpoint_subprocess.py`, `tests/unit/test_source_references.py`, minor stale comment in `tests/unit/test_request_handlers.py`).
    2. [x] Migrate medium-risk compatibility-heavy tests to explicit session fixtures while preserving semantics (`tests/integration/test_command_providers.py`, `tests/unit/test_send_debug_message.py`, `tests/unit/test_source_reference_helpers.py`, `tests/unit/test_session_state_start_command_receiver.py`).
    3. [x] Replace remaining `SessionState` typing mentions in runtime with `DebugSession`/Protocol-oriented typing where practical (`dapper/shared/source_handlers.py`).
    4. [x] Evaluate replacing remaining monkeypatch seams (e.g., sender alias in `dapper/ipc/ipc_receiver.py`) with explicit injectable hooks for tests.
    5. [x] Keep only dedicated compatibility-contract tests for `SessionState` behavior (`tests/unit/test_session_state_reset.py`) and migrate all non-contract tests off singleton assumptions.
    6. [x] Remove legacy `SessionState` constructor/reset compatibility entry points.

---

## Code Quality

- [x] **Add pluggable source-content hook with URI-aware path handling**
  - Files: `dapper/shared/debug_shared.py`, `dapper/shared/source_handlers.py`, `dapper/adapter/request_handlers.py` (optional typing-only additions in `dapper/protocol/debugger_protocol.py`)
  - Goal: Allow callers to provide additional source content (remote/editor/generated) based on DAP `source.path` while preserving existing `sourceReference` behavior.
  - Protocol note: DAP `Source.path` may be a filesystem path or URI; non-filesystem content can also be represented via `sourceReference`.
  - **Refactor alignment (PyDebugger decomposition):**
    - `PyDebugger` is now decomposed and does not currently own source-content-by-path resolution helpers.
    - Implement the provider hook at the `DebugSession` / `SourceCatalog` layer so both legacy command handlers and async adapter request handlers benefit via shared fallback logic.
    - Keep debugger-specific hooks optional (capability-based), not required on `PyDebugger` itself.
  - **Implementation plan (detailed):**
   1. **Define provider contract (PEP 544 style)**
     - Add a small `Protocol`/callable type for providers: input `path_or_uri: str`, output `str | None`.
     - Keep this in `debug_shared.py` near `SourceCatalog` (runtime registry) and optionally mirror as a typing-only helper in `debugger_protocol.py`.
   2. **Add SourceCatalog/DebugSession provider registry API**
     - Add `register_source_provider(provider) -> int`, `unregister_source_provider(provider_id) -> bool`.
     - Store providers in insertion order with stable IDs and guard with a lock (`threading.RLock`) for thread-safety.
     - Ensure unregister is idempotent/safe when IDs are missing.
     - Expose pass-through methods on `DebugSession` for compatibility call sites.
   3. **Add URI normalization utility**
     - Implement helper to detect URI vs path (`urllib.parse.urlparse`).
     - Convert `file://` URIs to local paths for disk fallback (`urllib.request.url2pathname`).
     - Preserve non-`file` URIs (e.g., `vscode-remote://`, `git:`) for provider resolution.
   4. **Integrate lookup flow into source resolution**
     - Update `SourceCatalog.get_source_content_by_path` / `DebugSession.get_source_content_by_path` to: providers first → normalized disk fallback for local files.
     - Keep `shared/source_handlers.py` and `adapter/request_handlers.py` using shared session helpers so behavior stays consistent across sync/async command paths.
     - Keep precedence clear: explicit `sourceReference` lookup remains first, then path/URI provider fallback.
   5. **Error handling + observability**
     - Provider exceptions must be isolated (log + continue to next provider), never fail the whole request.
     - Add debug-level logs for provider hits/misses to aid diagnostics.
   6. **Test plan (unit + integration)**
     - Unit tests for register/unregister lifecycle and thread-safe behavior.
     - Unit tests for `file://` normalization and non-`file` URI pass-through.
     - Integration tests for `shared/source_handlers.handle_source` and `adapter/request_handlers._handle_source` returning provider-backed content by URI/path.
     - Regression tests to confirm existing `sourceReference` and local-path behavior remain unchanged.

  - **Status update (implemented in current branch):**
    - ✅ Added provider registry APIs on `SourceCatalog`/`DebugSession` (`register_source_provider`, `unregister_source_provider`) with stable IDs and lock-guarded access.
    - ✅ Added URI-aware source resolution with provider-first lookup and `file://` normalization for disk fallback in `dapper/shared/debug_shared.py`.
    - ✅ Updated legacy source-path flow in `dapper/shared/source_handlers.py` to use shared session lookup so provider behavior is consistent.
    - ✅ Added focused coverage in `tests/unit/test_source_reference_helpers.py`, `tests/unit/test_source_references.py`, and `tests/unit/test_request_handlers.py` for provider lifecycle, URI handling, and sync/async source handler fallback behavior.




---

## Test Coverage

Overall: **36.8% line coverage / 14.5% branch coverage** (1120 tests, 120 files).

- [ ] **Increase IPC layer coverage**
  - `dapper/ipc/transport_factory.py`, `dapper/ipc/connections/`, `dapper/ipc/sync_adapter.py` are undertested.
  - **Progress update (current branch):**
    - ✅ Added focused unit coverage for `dapper/ipc/sync_adapter.py` in `tests/unit/test_sync_connection_adapter.py`.
    - ✅ New tests cover synchronous adapter method passthrough, missing-loop error path, and close-path exception propagation behavior.
    - ✅ Added launcher IPC edge-case tests in `tests/integration/test_launcher_ipc.py` for EOF/OSError read handling and socket-connect failure cleanup paths.
    - ✅ Expanded `dapper/ipc/transport_factory.py` unit coverage in `tests/unit/test_transport_factory.py` for transport resolution, unsupported transport guards, unix→tcp fallback paths, and wrapped socket-connect error paths.
    - ✅ Added dedicated `dapper/ipc/connections/tcp.py` branch tests in `tests/unit/test_tcp_connection_unit.py` for wait timeout/precondition errors, DAP/binary read error branches, and write-path validations.
    - ✅ Added platform-independent mocked Windows named-pipe coverage in `tests/unit/test_transport_factory.py` for `create_pipe_listener_sync`, `create_pipe_client_sync`, routed `create_listener/create_connection` pipe paths, and wrapped listener/client failure handling.
    - ✅ Added direct non-Windows guard-path tests for sync named-pipe helpers in `tests/unit/test_transport_factory.py` (`create_pipe_listener_sync`, `create_pipe_client_sync`) to lock expected platform error behavior.
    - ✅ Enabled mocked-Windows named-pipe connection tests to run cross-platform in `tests/unit/test_pipe_windows_unit.py` (accept/listener path, recv fallback, DBGP binary/text read, binary/text write, and close-resource cleanup).
    - ✅ Focused `pipe` coverage run (`tests/unit/test_pipe_windows_unit.py` + `tests/integration/test_connections_pipe.py`) now reports `dapper/ipc/connections/pipe.py` at **70/94 branch edges**.
    - 🔜 Remaining: deeper coverage of platform-specific named-pipe branches and additional factory/listener lifecycle edge cases.

- [x] **Increase frame evaluation coverage**
  - `dapper/_frame_eval/modify_bytecode.py`, `dapper/_frame_eval/selective_tracer.py`, `dapper/_frame_eval/frame_tracing.py` need dedicated tests.
  - **Progress update (current branch):**
    - ✅ Added dedicated analyzer/manager branch coverage for `dapper/_frame_eval/selective_tracer.py` in `tests/unit/test_selective_tracer_analyzer_manager.py`.
    - ✅ New tests cover skip-frame decisions, breakpoint/no-breakpoint routing, function-range breakpoint tracing in step mode, cache invalidation hooks, dispatcher stats/dispatch paths, manager breakpoint lifecycle, and global wrapper delegation.
    - ✅ Added `modify_bytecode` fallback/error-path tests in `tests/unit/test_bytecode_modification.py` for `insert_code` failure guards, `get_bytecode_info` error handling, and `_rebuild_code_object` legacy fallback construction.
    - ✅ Targeted frame-eval run now reports: `selective_tracer.py` **76%** (up from **37%** in this focused suite), `frame_tracing.py` **92%**, `modify_bytecode.py` **72%** (up from **63%**).

- [x] **Increase launcher coverage**
  - `dapper/launcher/debug_launcher.py`, `dapper/launcher/launcher_ipc.py` lack unit tests.
  - **Progress update (current branch):**
    - ✅ Added broad launcher + IPC test coverage across orchestration, routing, parse/validation, error branches, and binary/text transport paths.
    - ✅ New/expanded tests are concentrated in `tests/unit/test_debug_launcher.py`, `tests/integration/test_launcher_ipc.py`, and `tests/unit/test_sync_connection_adapter.py`.
    - ✅ Added incremental edge-path coverage for receive-loop timing and command error-shaping consistency in `tests/unit/test_debug_launcher.py` and `tests/integration/test_launcher_ipc.py`.
    - ✅ Targeted launcher run now reports: `dapper/launcher/debug_launcher.py` **99%** and `dapper/launcher/launcher_ipc.py` **100%** coverage.

- [ ] **Increase branch coverage to ≥50%**
  - Error paths and edge cases are largely untested. Focus on conditional branches in `debugger_bdb.py`, `server.py`, and `command_handlers.py`.
  - **Progress update (current branch):**
    - ✅ Added `tests/unit/test_server_wrapper_delegation.py` to exercise `PyDebugger` delegation/alias and data-breakpoint wrapper paths in `dapper/adapter/server.py`.
    - ✅ Focused module run for that test reports `dapper/adapter/server.py` at **62%** coverage.
    - ✅ Added `tests/unit/test_command_handlers_guards.py` to cover no-debugger guard branches for debugger-dependent command handlers and invalid/unknown command response paths in `dapper/shared/command_handlers.py`.
    - ✅ Focused coverage run for `tests/unit/test_command_handlers_guards.py` now reports `dapper/shared/command_handlers.py` at **19/40 branch edges** in that target run (up from a previously observed **3/40** in an integration-only focused run).
    - ✅ Added `tests/unit/test_debugger_bdb_branches.py` for `DebuggerBDB` function-breakpoint call flow branches (`CONTINUE` vs `STOP`), breakpoint-clear edge handling (`None`/non-int lines + metadata clear failure), and `user_exception` `set_continue()` failure fallback path.
    - ✅ Expanded `tests/unit/test_debugger_bdb_branches.py` with additional edge-path coverage for data-breakpoint stop decisions (default/no-meta + all-continue), single-emission thread registration, optional stopped-event descriptions, `user_line` early-return/default-stop flows, `user_exception` no-break fast path, and function-name non-match handling.
    - ✅ Added further focused `DebuggerBDB` branch tests for multi-candidate function-name matching, non-mapping data-watch helper guards, custom-breakpoint existing/no-op paths, and explicit regular-breakpoint `CONTINUE` handling.
    - ✅ Added deeper `DebuggerBDB` path tests for regular-breakpoint `STOP` flow, data-breakpoint stop+return path in `user_line`, regular-breakpoint handled-return path in `user_line`, full `user_exception` stop path, and `clear_breaks_for_file` breaks-lookup exception handling.
    - ✅ Added less-mocked real-frame/real-break-table `DebuggerBDB` tests in `tests/unit/test_debugger_bdb_branches.py` (entry-path `user_line`, regular-breakpoint handling via real `breaks`, full exception-stop flow, and success-path breakpoint cleanup); full-suite targeted report remains **47%** in this environment.
    - 🔜 Remaining: raise full-suite branch baselines to the ≥50% target for remaining modules (`debugger_bdb.py` currently **47%** in full-suite targeted run).

- [x] **Add integration tests for end-to-end DAP sessions**
  - Test full launch → set breakpoints → continue → hit breakpoint → inspect variables → disconnect flow.
  - **Progress update (current branch):**
    - ✅ Added `tests/integration/test_server.py::test_end_to_end_dap_flow_launch_break_continue_variables_disconnect`.
    - ✅ New integration test drives request sequence: `initialize` → `launch` → `setBreakpoints` → `configurationDone` → `continue` (emits `stopped` event) → `stackTrace` → `scopes` → `variables` → `disconnect`.
    - ✅ Asserts response success for each request, verifies breakpoint `stopped` event payload, and validates variable inspection payload (`x=42`) in the same session flow.

---

## Summary

| Category           | Open Items |
|--------------------|------------|
| Architecture       | 0          |
| Performance        | 0          |
| Code Quality       | 0          |
| Test Coverage      | 2          |
| **Total**          | **2**      |

**Next up:** IPC + branch coverage expansion (2 items).
