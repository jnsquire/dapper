# DebuggerBDB Test Double Audit

Date: 2026-02-15 (updated)

## Scope

Audit of tests using `DummyDebugger`, `FakeDebugger`, and `MockDebuggerBDB` to determine where a real `dapper.core.debugger_bdb.DebuggerBDB` can be used safely.

## Inventory Summary

Files using test doubles (17 total):

- `DummyDebugger` heavy usage:
  - `tests/integration/test_debug_launcher_comprehensive.py`
  - `tests/integration/test_dap_command_handlers.py`
  - `tests/integration/test_debugger_protocol.py`
  - `tests/integration/test_dap_command_handlers_extra.py`
  - `tests/integration/test_debug_launcher_handlers.py`
  - `tests/unit/test_make_variable_object.py`
  - `tests/unit/test_debug_shared_helpers.py`
  - plus `tests/integration/test_inprocess_debugger.py` (inherits via local `FakeDebugger(DummyDebugger)`)
- `FakeDebugger` usage:
  - `tests/unit/test_data_breakpoint_info_shared.py`
  - `tests/unit/test_launcher_set_data_breakpoints.py`
  - `tests/unit/test_completions.py`
  - `tests/integration/test_inprocess_debugger.py`
- `MockDebuggerBDB` usage (frame-eval focused mocks):
  - `tests/integration/test_frame_eval_integration_mock.py`
  - `tests/integration/test_frame_eval_pytest.py`
  - `tests/integration/test_debugger_integration.py`
  - `tests/functional/test_pytest_comprehensive.py`

## Feasibility Classification

### A) High-confidence migration candidates (can use real `DebuggerBDB` now)

1. `tests/unit/test_make_variable_object.py` ✅ **migrated**
   - Now uses real `DebuggerBDB`.
   - Assertions updated to use `var_manager` storage.

2. `tests/unit/test_debug_shared_helpers.py` (partial) ✅ **partially migrated**
   - Some tests can switch directly (`_allocate_var_ref`, visibility/format helpers).
   - Data-watch related tests need field-shape adjustments (`data_bp_state` semantics).
   - `_allocate_var_ref` path now uses real `DebuggerBDB`; data-watch-shape test remains on `DummyDebugger`.

3. `tests/integration/test_dap_command_handlers_extra.py` (targeted subset) ✅ **migrated subset**
   - `setBreakpoints` clearing behavior now uses real `DebuggerBDB` with file-backed breakpoints.
   - Keep non-breakpoint protocol-shape tests on dummy if needed.

4. `tests/integration/test_dap_command_handlers.py` (targeted subset) ✅ **migrated subset**
   - Added real `DebuggerBDB` `setBreakpoints` handler-path integration test.

5. `tests/integration/test_debugger_protocol.py` (targeted subset) ✅ **migrated subset**
   - Added real `DebuggerBDB` breakpoint-method protocol test.

### B) Keep doubles (or migrate last)

1. `tests/integration/test_frame_eval_integration_mock.py`
2. `tests/integration/test_frame_eval_pytest.py`
3. `tests/functional/test_pytest_comprehensive.py`
4. `tests/integration/test_debugger_integration.py` (mock debugger portions)

Reason: These tests validate frame-eval integration hooks, explicit trace-function substitution, and failure/fallback behavior with intentionally controlled surfaces. Replacing with real `DebuggerBDB` would increase fragility and reduce determinism.

### C) Mixed/large suites (incremental migration only)

1. `tests/integration/test_debug_launcher_comprehensive.py`
2. `tests/integration/test_dap_command_handlers.py`
3. `tests/integration/test_debugger_protocol.py`
4. `tests/integration/test_debug_launcher_handlers.py`
5. `tests/integration/test_inprocess_debugger.py`

Reason: These suites intentionally assert protocol/handler contracts and broad behavior using lightweight doubles. Full replacement with real `DebuggerBDB` is likely high effort and may blur test intent.

## Changes already completed during this pass

- `tests/dummy_debugger.py::DummyDebugger.clear_breaks_for_file` aligned to real-style behavior:
  - per-line clear via `clear_break`
  - metadata clear via `clear_break_meta_for_file`
- `tests/mocks.py::FakeDebugger.clear_breaks_for_file` aligned similarly.
- `tests/unit/test_make_variable_object.py` migrated to real `DebuggerBDB`.
- `tests/unit/test_debug_shared_helpers.py` partially migrated (`_allocate_var_ref` test).
- `tests/integration/test_dap_command_handlers_extra.py::test_set_breakpoints_and_state` migrated to real `DebuggerBDB`.
- `tests/integration/test_dap_command_handlers.py` now includes real `DebuggerBDB` setBreakpoints-path test.
- `tests/integration/test_debugger_protocol.py` now includes real `DebuggerBDB` breakpoint-method protocol test.
- `tests/integration/test_debug_launcher_handlers.py::test_handle_threads_empty` migrated to real `DebuggerBDB`.
- `tests/integration/test_debug_launcher_handlers.py::test_set_data_breakpoints_and_info` migrated to real `DebuggerBDB`.
- `tests/integration/test_debug_launcher_comprehensive.py::test_handle_set_breakpoints_failure` migrated to real `DebuggerBDB`.
- `tests/integration/test_debug_launcher_comprehensive.py::test_handle_set_breakpoints_success` migrated to real `DebuggerBDB` with file-backed line assertions.
- `tests/integration/test_debug_launcher_comprehensive.py::test_handle_set_breakpoints_exception_handling` migrated to real `DebuggerBDB`.
- `tests/integration/test_debug_launcher_comprehensive.py::test_handle_set_function_breakpoints` migrated to real `DebuggerBDB`.
- `tests/integration/test_debug_launcher_comprehensive.py::test_handle_set_function_breakpoints_empty` migrated to real `DebuggerBDB`.
- `tests/integration/test_debug_launcher_comprehensive.py::test_handle_set_exception_breakpoints` migrated to real `DebuggerBDB`.
- `tests/integration/test_debug_launcher_comprehensive.py::test_handle_set_exception_breakpoints_invalid_filters` migrated to real `DebuggerBDB`.
- `tests/integration/test_debug_launcher_comprehensive.py::test_handle_set_exception_breakpoints_exception_handling` migrated to real `DebuggerBDB`.
- `tests/integration/test_debug_launcher_comprehensive.py::test_handle_pause` migrated to real `DebuggerBDB`.
- `tests/integration/test_debug_launcher_comprehensive.py::test_handle_stack_trace` migrated to real `DebuggerBDB`.
- `tests/integration/test_debug_launcher_comprehensive.py::test_handle_stack_trace_pagination` migrated to real `DebuggerBDB`.
- `tests/integration/test_debug_launcher_comprehensive.py::test_handle_threads_with_data` migrated to real `DebuggerBDB`.
- `tests/integration/test_debug_launcher_comprehensive.py::test_handle_debug_command_unsupported` migrated to real `DebuggerBDB`.
- `tests/integration/test_debug_launcher_comprehensive.py::test_handle_debug_command_with_response` migrated to real `DebuggerBDB`.
- Setup hygiene refactor: added `_session_with_debugger(...)` helper and replaced repeated session+debugger population in `tests/integration/test_debug_launcher_comprehensive.py`.
- Setup hygiene refactor: added `_session_with_debugger(...)` helper in `tests/integration/test_debug_launcher_handlers.py` and `_active_session_with_debugger(...)` helper in `tests/integration/test_dap_command_handlers.py` to reduce repeated debugger attachment boilerplate.
- Naming convention: prefer `_session_with_debugger(...)` for session-fixture-based tests and `_active_session_with_debugger(...)` for active-session tests.

These changes reduce divergence while preserving existing test expectations.

## Recommended migration plan

1. **Phase 1 (quick wins)** ✅ complete
2. **Phase 2 (targeted integration gains)** ✅ complete for selected files
3. **Phase 3 (next candidates)**
   - selected `setBreakpoints`/breakpoint-clear paths in `tests/integration/test_debug_launcher_comprehensive.py`
   - additional low-risk handler tests in `tests/integration/test_debug_launcher_handlers.py`
   - optional partial migration in `tests/integration/test_inprocess_debugger.py` where protocol-shape assumptions allow
   - defer frame-eval mock suites unless coverage ROI justifies fragility risk

## Expected outcome

- Better confidence in real `DebuggerBDB` behavior on critical breakpoint paths.
- Lower mock drift risk.
- Minimal increase in test flakiness by avoiding frame-eval/mock-heavy suites for early migration.
