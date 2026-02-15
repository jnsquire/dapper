# Dapper Improvement Checklist

Comprehensive checklist of identified issues, organized by severity and category.
Generated from a full codebase review on 2026-02-14.

## Architecture

- [x] **Decompose `PyDebugger` god-class** ✅
  - File: `dapper/adapter/server.py` — 1533 lines
  - ~30+ public methods handling launching, IPC, breakpoints, stack traces, variables, events, and shutdown.
  - Fix: Extract into focused managers (e.g., `LaunchManager`, `EventRouter`, `StateManager`, `BreakpointRouter`).
  - **Natural split boundaries (current code layout):**
    - Event loop + event routing: `_acquire_event_loop` and `_PyDebuggerEventRouter` (`dapper/adapter/server.py` ~L82–212)
    - Launch/attach orchestration: `_PyDebuggerLifecycleManager` (`dapper/adapter/server.py` ~L214–372)
    - Breakpoint/state inspection: `_PyDebuggerStateManager` (`dapper/adapter/server.py` ~L374–568)
    - Runtime process/IPC/backend wiring inside `PyDebugger` (`dapper/adapter/server.py` ~L881–1109)
    - Breakpoint/data-breakpoint domain logic inside `PyDebugger` (`dapper/adapter/server.py` ~L752–848, ~L1111–1222)
    - Execution control + termination/shutdown inside `PyDebugger` (`dapper/adapter/server.py` ~L1224–1541)
    - DAP transport server boundary: `DebugAdapterServer` (`dapper/adapter/server.py` ~L1543–1710)
  - **Proposed extraction map:**
    - `dapper/adapter/debugger/event_router.py`: `_PyDebuggerEventRouter` + debug-message parsing/dispatch
    - `dapper/adapter/debugger/lifecycle.py`: `_PyDebuggerLifecycleManager` + launch/attach helpers
    - `dapper/adapter/debugger/state.py`: `_PyDebuggerStateManager` + breakpoint normalization/event forwarding helpers
    - `dapper/adapter/debugger/runtime.py`: process startup/output readers, IPC reader bootstrap, backend/bridge creation
    - `dapper/adapter/debugger/session.py`: `PyDebugger` session state, pending-command futures, shutdown/cleanup
    - `dapper/adapter/server_core.py`: `DebugAdapterServer` request loop + protocol send/response/event methods
  - **Suggested extraction order (lowest risk first):**
    1. Move `DebugAdapterServer` to `server_core.py` (clear API boundary, minimal debugger coupling)
    2. Move event router + lifecycle/state managers to `adapter/debugger/` modules (already logically extracted)
    3. Extract runtime process/IPC/backend plumbing from `PyDebugger`
    4. Extract execution-control + shutdown helpers; leave `PyDebugger` as thin composition/orchestration facade
  - **Progress update (current branch):**
    - ✅ Extracted debug message/event handling into dedicated `_PyDebuggerEventRouter` in `dapper/adapter/server.py`.
    - ✅ Added explicit delegation methods on `PyDebugger` (`emit_event`, `resolve_pending_response`, `schedule_program_exit`, pending-command helpers) to reduce direct state coupling.
    - ✅ Extracted launch/attach/in-process startup orchestration into dedicated `_PyDebuggerLifecycleManager` in `dapper/adapter/server.py`.
    - ✅ Added lifecycle bridge methods on `PyDebugger` (`start_ipc_reader`, backend/bridge creators, stop-event await, IPC mode toggle, launch helpers) so extracted components avoid direct private-state mutation.
    - ✅ Extracted breakpoint/state-inspection operations into dedicated `_PyDebuggerStateManager` in `dapper/adapter/server.py` (`set_breakpoints`, `get_stack_trace`, `get_scopes`, `get_variables`, `set_variable`, `evaluate`).
    - ✅ Added bridge wrappers (`get_active_backend`, `get_inprocess_backend`, breakpoint processing/event helpers) to keep extracted components decoupled from private internals.
    - ✅ Extracted process/IPC/backend primitives into dedicated `_PyDebuggerRuntimeManager` in `dapper/adapter/server.py` (`start_ipc_reader`, backend/bridge creation, debuggee process startup, output stream forwarding).
    - ✅ Extracted execution-control and termination lifecycle helpers into dedicated `_PyDebuggerExecutionManager` in `dapper/adapter/server.py` (`continue/step/pause`, thread listing, exception info, configuration-done, disconnect/terminate/restart, raw command send).
    - ✅ Reduced `PyDebugger` wrapper/alias surface by inlining direct manager/event-router delegation for event handling and pending-response resolution; retained minimal private compatibility alias for launch monkey-patching/tests.
    - ✅ Moved `DebugAdapterServer` to `dapper/adapter/server_core.py` and preserved import compatibility via re-export in `dapper/adapter/server.py`.
    - ✅ Moved manager classes into dedicated modules under `dapper/adapter/debugger/`:
      - `event_router.py`: `_PyDebuggerEventRouter`
      - `lifecycle.py`: `_PyDebuggerLifecycleManager`
      - `state.py`: `_PyDebuggerStateManager`
      - `runtime.py`: `_PyDebuggerRuntimeManager`
      - `execution.py`: `_PyDebuggerExecutionManager`
    - ✅ Introduced focused session façade in `dapper/adapter/debugger/session.py` (`_PyDebuggerSessionFacade`) and wired `PyDebugger` pending-command lifecycle through it (`_get_next_command_id`, pending-command map compatibility accessors, response resolution, shutdown failure propagation).
    - ✅ Moved additional mutable session containers (`threads`, `var_refs`, `breakpoints`, `current_stack_frames`) behind `session.py` with compatibility properties on `PyDebugger` to preserve test-facing attribute access.
    - ✅ Migrated remaining session-owned mutable containers (`function_breakpoints`, data-watch containers, thread-exit bookkeeping) behind `session.py` with compatibility properties to preserve current direct access patterns.
    - ✅ Reduced direct container mutation in hot paths by routing key mutation sites through focused session-facade helper methods (`event_router`, `state`, `execution`, data-breakpoint registration, and shutdown state clearing).
    - ✅ Consolidated remaining high-value direct container reads behind session-facade query helpers where it improved clarity (notably thread iteration for execution/thread-list reporting), while intentionally keeping straightforward direct compatibility reads in low-risk paths.
    - ✅ Closeout: decomposition now lands on a thin `PyDebugger` orchestration facade backed by dedicated manager modules + a focused session facade, with compatibility accessors retained for test/runtime stability.

- [x] **Reduce compatibility property sprawl in `DebuggerBDB`** ✅
  - File: `dapper/core/debugger_bdb.py` (~L100–310)
  - Status: Completed. Production runtime paths now use delegate components directly (`stepping_controller`, `thread_tracker`, `exception_handler`, `var_manager`, `bp_manager`).
  - Note: Compatibility-style properties intentionally remain only in test doubles (`tests/mocks.py`, `tests/dummy_debugger.py`).

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


- [x] **`DebuggerLike` Protocol has ~30+ required attributes** ✅
  - File: `dapper/protocol/debugger_protocol.py`
  - Status: Completed. `DebuggerLike` is now composed from focused capability protocols and no longer requires private/internal attributes.



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
| Performance        | 4          |
| Code Quality       | 1          |
| Test Coverage      | 5          |
| **Total**          | **11**     |

**Next up:** Performance improvements (4 items).
