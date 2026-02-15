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

- [ ] **Missing type hints on public methods**
  - Files:
    - `dapper/core/debugger_bdb.py` — `record_breakpoint`, `clear_break_meta_for_file`, `set_custom_breakpoint`, `clear_custom_breakpoint` (all params untyped)
    - `dapper/core/debug_helpers.py` — `get_int`, `get_str` (missing return type)
    - `dapper/ipc/ipc_context.py` — heavy use of `Any` for socket/pipe/file fields
  - Fix: Add proper type annotations.

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

- [ ] **Singleton `SessionState` has no `reset()` method**
  - File: `dapper/shared/debug_shared.py` (~L76)
  - `__new__` returns the same instance forever. Tests can't clean up state between runs.
  - Fix: Add a `reset()` classmethod that reinitializes all mutable state.


- [ ] **Frame eval `types.py` stubs are runtime-callable but raise**
  - File: `dapper/_frame_eval/types.py`
  - Function bodies use `...` (Ellipsis). They'll raise `TypeError` if called at runtime.
  - Fix: Guard with `TYPE_CHECKING` or provide runtime implementations.

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
| Architecture       | 3          |
| Performance        | 5          |
| Code Quality       | 5          |
| Test Coverage      | 5          |
| **Total**          | **18**     |

**Next up:** Code quality improvements (5 items).
