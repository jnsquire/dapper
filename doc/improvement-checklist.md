# Dapper Improvement Checklist

Comprehensive checklist of identified issues, organized by severity and category.
Generated from a full codebase review on 2026-02-14.

## Architecture

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
    - 🔜 Remaining: migrate any external legacy entry-point hooks that still assume implicit singleton construction (`SessionState()`) to explicit session composition or `debug_shared.state`, then consider deprecating `SessionState` compatibility wrappers.
  - **Recommended order (next steps):**
    1. [ ] Migrate remaining low-risk tests from direct `debug_shared.state` reads to explicit `DebugSession` fixtures (`tests/integration/test_data_breakpoint_subprocess.py`, `tests/unit/test_source_references.py`, minor stale comment in `tests/unit/test_request_handlers.py`).
    2. [ ] Migrate medium-risk compatibility-heavy tests to explicit session fixtures while preserving semantics (`tests/integration/test_command_providers.py`, `tests/unit/test_send_debug_message.py`, `tests/unit/test_source_reference_helpers.py`, `tests/unit/test_session_state_start_command_receiver.py`).
    3. [ ] Replace remaining `SessionState` typing mentions in runtime with `DebugSession`/Protocol-oriented typing where practical (`dapper/shared/source_handlers.py`).
    4. [ ] Evaluate replacing remaining monkeypatch seams (e.g., sender alias in `dapper/ipc/ipc_receiver.py`) with explicit injectable hooks for tests.
    5. [ ] Keep only dedicated compatibility-contract tests for `SessionState` behavior (`tests/unit/test_session_state_reset.py`) and migrate all non-contract tests off singleton assumptions.
    6. [ ] Add deprecation notice for legacy `SessionState` constructor/reset entry points and define a removal window after external hook migration is complete.

---

## Code Quality

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
  - **Progress update (current branch):**
    - ✅ Added focused unit coverage for `dapper/ipc/sync_adapter.py` in `tests/unit/test_sync_connection_adapter.py`.
    - ✅ New tests cover synchronous adapter method passthrough, missing-loop error path, and close-path exception propagation behavior.
    - ✅ Added launcher IPC edge-case tests in `tests/integration/test_launcher_ipc.py` for EOF/OSError read handling and socket-connect failure cleanup paths.

- [ ] **Increase frame evaluation coverage**
  - `dapper/_frame_eval/modify_bytecode.py`, `dapper/_frame_eval/selective_tracer.py`, `dapper/_frame_eval/frame_tracing.py` need dedicated tests.

- [ ] **Increase launcher coverage**
  - `dapper/launcher/debug_launcher.py`, `dapper/launcher/launcher_ipc.py` lack unit tests.
  - **Progress update (current branch):**
    - ✅ Added broad launcher + IPC test coverage across orchestration, routing, parse/validation, error branches, and binary/text transport paths.
    - ✅ New/expanded tests are concentrated in `tests/unit/test_debug_launcher.py`, `tests/integration/test_launcher_ipc.py`, and `tests/unit/test_sync_connection_adapter.py`.
    - 🔜 Remaining: incremental edge-path coverage (receive-loop timing and command error-shaping consistency).

- [ ] **Increase branch coverage to ≥50%**
  - Error paths and edge cases are largely untested. Focus on conditional branches in `debugger_bdb.py`, `server.py`, and `command_handlers.py`.

- [ ] **Add integration tests for end-to-end DAP sessions**
  - Test full launch → set breakpoints → continue → hit breakpoint → inspect variables → disconnect flow.

---

## Summary

| Category           | Open Items |
|--------------------|------------|
| Architecture       | 1          |
| Performance        | 0          |
| Code Quality       | 1          |
| Test Coverage      | 5          |
| **Total**          | **7**      |

**Next up:** Code Quality source-provider improvements (1 item) and Test Coverage expansion (5 items).
