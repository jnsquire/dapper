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

- [ ] **Dispatch tables rebuilt on every `_execute_command` call**
  - Files: `dapper/adapter/external_backend.py` (~L116), `dapper/adapter/inprocess_backend.py` (~L78)
  - A fresh dict and multiple closures are created on every invocation.
  - Fix: Move dispatch tables to class-level or `__init__`.

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

- [ ] **`iter_python_module_files` snapshots all of `sys.modules`**
  - File: `dapper/adapter/source_tracker.py` (~L125)
  - Creates a full copy of `sys.modules` (potentially thousands of entries) on every call.
  - Fix: Cache or debounce.

- [ ] **Non-thread-safe protocol sequence counter**
  - File: `dapper/protocol/protocol.py` (~L57)
  - `ProtocolFactory.seq_counter` is a plain integer with no locking. Concurrent message creation produces duplicate sequence numbers.
  - Fix: Use `itertools.count()` or `threading.Lock`.

- [ ] **RLock held during entire trace dispatch**
  - File: `dapper/_frame_eval/selective_tracer.py` (~L360)
  - The lock is held while calling `self.debugger_trace_func(frame, event, arg)`, which can be arbitrarily slow.
  - Fix: Narrow the critical section to only protect shared state, not the trace callback itself.

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

- [ ] **`CodeType` constructor fragile across Python versions**
  - File: `dapper/_frame_eval/modify_bytecode.py` (~L440)
  - Manual `CodeType(...)` construction handles 3.8/3.10/3.11 but will break on 3.12+ which changed the constructor signature.
  - Fix: Use `code.replace()` (available since 3.8) where possible.

- [ ] **Shadowed `FrameEvalConfig` name**
  - File: `dapper/_frame_eval/debugger_integration.py` (~L44)
  - A local `class FrameEvalConfig(TypedDict)` shadows the imported `FrameEvalConfig` dataclass from `dapper._frame_eval.config`. Different shapes and types.
  - Fix: Rename the local TypedDict (e.g., `FrameEvalConfigDict`).

- [ ] **Duplicate import of `ExceptionDetails`**
  - File: `dapper/protocol/requests.py` (~L15, ~L22)
  - Imported both at runtime and inside `TYPE_CHECKING`, shadowing itself.
  - Fix: Remove the runtime import if only used for type annotations, or remove the `TYPE_CHECKING` import.

- [ ] **`_handle_pause_impl` is a no-op**
  - File: `dapper/shared/command_handlers.py` (~L682)
  - Reads `threadId` but does nothing. Pause is never actually implemented.
  - Fix: Implement pause or raise `NotImplementedError`.

- [ ] **`handle_source` ignores `sourceReference`**
  - File: `dapper/shared/command_handlers.py` (~L1203)
  - When `sourceReference` is provided, `content` is set to `""` — no source is actually fetched.
  - Fix: Implement source lookup by reference.

- [ ] **Singleton `SessionState` has no `reset()` method**
  - File: `dapper/shared/debug_shared.py` (~L76)
  - `__new__` returns the same instance forever. Tests can't clean up state between runs.
  - Fix: Add a `reset()` classmethod that reinitializes all mutable state.

- [ ] **Typo: `DAPPER_SKIP_JS_TESTS_IN_CONFT` → `CONFTEST`**
  - File: `dapper/utils/dev_tools.py` (~L87)

- [ ] **`handle_restart` calls `os.execv` without cleanup**
  - File: `dapper/shared/command_handlers.py` (~L1296)
  - IPC handles, threads, and file descriptors all leak.
  - Fix: Perform cleanup before `exec`, or document the limitation.

- [ ] **Race condition in `start_reader`**
  - File: `dapper/ipc/ipc_context.py` (~L290)
  - Checks `_reader_thread.is_alive()` then creates a new thread without locking. Two concurrent callers could both create threads.
  - Fix: Add a lock around the check-and-create.

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

## Windows Support

- [ ] **Named pipe support incomplete on Windows**
  - File: `dapper/ipc/connections/pipe.py` (~L46)
  - FIXME: `On Windows, named pipes work differently - we need to use the proactor event loop`. Code creates a mock connected state on Windows.
  - Fix: Implement Windows named pipe support using the proactor event loop, or document the limitation.

---

## Summary

| Category           | Total | Done | Remaining |
|--------------------|-------|------|-----------|
| Architecture       | 3     | 0    | 3         |
| Performance        | 8     | 0    | 8         |
| Code Quality       | 19    | 6    | 13        |
| Test Coverage      | 5     | 0    | 5         |
| Windows Support    | 1     | 0    | 1         |
| **Total**          | **36**| **6**| **30**   |

**Next up:** Code quality improvements (13 items).
