# `sys.monitoring` Integration Plan

A phased plan for integrating Python 3.12+'s `sys.monitoring` API into
Dapper as a high-performance alternative to the existing `sys.settrace` /
frame-evaluation tracing backend.

> **Reference:** <https://docs.python.org/3/library/sys.monitoring.html>

---

## Motivation

`sys.monitoring` (PEP 669, Python 3.12+) is purpose-built to replace
`sys.settrace` for debuggers, profilers, and coverage tools.  Key advantages:

- **Near-zero overhead for unmonitored code** — events are disabled per
  code-object; non-breakpoint frames run at full speed.
- **No per-frame trace-function dispatching** — eliminates the
  `SelectiveTraceDispatcher` entirely; the VM itself skips unsolicited
  callbacks.
- **`DISABLE` return value** — a callback can return
  `sys.monitoring.DISABLE` to surgically turn off monitoring at a single
  bytecode offset, making non-breakpoint lines a one-time cost.
- **First-class tool identity** — `sys.monitoring.DEBUGGER_ID` (0) is
  reserved for debuggers; no collision with profilers/coverage.

The existing `_frame_eval` subsystem with `bdb`/`sys.settrace` remains the
fallback for Python 3.9–3.11.

---

## Architecture

```
                     ┌──────────────────────────────┐
                     │       DebuggerBDB (core)      │
                     │  user_line / user_call / ...  │
                     └──────────┬───────────────────┘
                                │
                     ┌──────────▼───────────────────┐
                     │    TracingBackend (ABC)        │   ← NEW
                     │  install() / shutdown()       │
                     │  set_breakpoints()            │
                     │  set_stepping()               │
                     └──┬───────────────────────┬───┘
                        │                       │
           ┌────────────▼──────┐    ┌───────────▼──────────┐
           │ SettraceBackend   │    │ SysMonitoringBackend  │   ← NEW
           │ (Python 3.9-3.11) │    │ (Python ≥ 3.12)       │
           │ existing code     │    │ sys.monitoring API     │
           └───────────────────┘    └──────────────────────┘
```

---

## Event Mapping

| `sys.monitoring` event | Dapper use case | Replaces |
|------------------------|----------------|----------|
| `LINE` | Line breakpoints, stepping | `sys.settrace` dispatch_line → `user_line` |
| `CALL` | Function breakpoints | `sys.settrace` dispatch_call → `user_call` |
| `PY_START` / `PY_RETURN` | Code-object discovery, step-over boundary, call-stack tracking | `sys.settrace` dispatch_call/return |
| `PY_YIELD` / `PY_RESUME` | Async/generator stepping | Not currently handled cleanly |
| `RAISE` / `RERAISE` | Exception breakpoints | `sys.settrace` dispatch_exception → `user_exception` |
| `EXCEPTION_HANDLED` | "User-unhandled" exception filter | Not currently possible cleanly |
| `INSTRUCTION` | Instruction-level stepping, read watchpoints | `frame.f_trace_opcodes = True` |
| `BRANCH_LEFT` / `BRANCH_RIGHT` | Coverage-aware breakpoints (feature idea §8) | Not available today |
| `set_local_events()` | Per-file breakpoint activation | `SelectiveTraceDispatcher` + `FrameTraceAnalyzer` |
| `DISABLE` return | Per-offset event suppression | `BytecodeModifier` (breakpoint bytecode injection) |

---

## Checklist

### Phase 1 — `TracingBackend` abstraction & backend selection

Introduce the backend interface without changing any runtime behaviour.
All existing code continues to work behind `SettraceBackend`.

- [x] **1.1 Define `TracingBackend` protocol**
  - Created `dapper/_frame_eval/tracing_backend.py`.
  - Define abstract methods:
    - `install(debugger) → None`
    - `shutdown() → None`
    - `update_breakpoints(file: str, lines: set[int]) → None`
    - `set_stepping(mode: StepMode) → None`
    - `set_exception_breakpoints(filters: list[str]) → None`
    - `get_statistics() → dict[str, Any]`
  - Document thread-safety expectations in docstrings.

- [x] **1.2 Add `TracingBackendKind` enum to config**
  - Edited `dapper/_frame_eval/config.py`.
  - Add `TracingBackendKind` enum with values `AUTO`, `SETTRACE`,
    `SYS_MONITORING`.
  - Add `tracing_backend: TracingBackendKind = TracingBackendKind.AUTO`
    field to `FrameEvalConfig`.
  - Update `to_dict()` / `from_dict()` to serialise the new field.

- [x] **1.3 Wrap existing code in `SettraceBackend`**
  - Created `dapper/_frame_eval/settrace_backend.py`.
  - Implement `TracingBackend` by delegating to
    `SelectiveTraceDispatcher`, `DebuggerFrameEvalBridge`, and
    `BytecodeModifier`.
  - Existing functionality must be byte-for-byte identical; this is a
    pure refactoring wrapper.

- [x] **1.4 Wire backend selection into `FrameEvalManager`**
  - Edited `dapper/_frame_eval/frame_eval_main.py`.
  - `setup()` reads `config.tracing_backend`:
    - `AUTO` → pick `SYS_MONITORING` on 3.12+, else `SETTRACE`.
    - `SETTRACE` / `SYS_MONITORING` → use explicitly.
  - `shutdown()` delegates to the active backend's `shutdown()`.

- [x] **1.5 Update compatibility policy**
  - Edited `dapper/_frame_eval/compatibility_policy.py`.
  - Raise `max_python` ceiling to `(3, 14)` (or remove it).
  - Add `supports_sys_monitoring` property: `True` when
    `sys.version_info >= (3, 12)`.

- [x] **1.6 Unit tests for Phase 1**
  - Created `tests/unit/test_tracing_backend_selection.py` (29 tests, all passing).

---

### Phase 2 — `SysMonitoringBackend` core (line & call events)

A working debugger backend powered entirely by `sys.monitoring` that
handles breakpoints and stepping.

- [x] **2.1 Create `SysMonitoringBackend` class**
  - Created `dapper/_frame_eval/monitoring_backend.py`.
  - On `install()`:
    - `sys.monitoring.use_tool_id(DEBUGGER_ID, "dapper")`.
    - Register callbacks for `LINE`, `CALL`, `PY_START`, `PY_RETURN`.
    - Store reference to the debugger instance.
    - Raises `RuntimeError` if `DEBUGGER_ID` slot is already held.
  - On `shutdown()`:
    - `sys.monitoring.set_events(DEBUGGER_ID, NO_EVENTS)`.
    - Unregister all callbacks.
    - `sys.monitoring.free_tool_id(DEBUGGER_ID)`.

- [x] **2.2 `LINE` callback — breakpoint hits**
  - Callback signature: `(code: CodeType, line_number: int) → object`.
  - Look up `code.co_filename` in breakpoint registry.
  - If `line_number` not in breakpoint set and not stepping → return `DISABLE`.
  - If conditional breakpoint → evaluate via `ConditionEvaluator`; if
    falsy → return `None` (not `DISABLE`, so condition can be re-evaluated).
  - Otherwise, obtain frame via `sys._getframe(1)` and call
    `debugger.user_line(frame)`.
  - Stepping path: any `LINE` event fires `user_line` when `_step_mode ≠ CONTINUE`.

- [x] **2.3 Breakpoint management via `set_local_events()`**
  - Maintains `_code_registry: dict[str, set[CodeType]]` and
    `_breakpoints: dict[str, frozenset[int]]`.
  - `update_breakpoints(file, lines)`:
    - For each code object in `code_registry[file]`:
      - If `lines` is non-empty → `sys.monitoring.set_local_events(DEBUGGER_ID, code, events.LINE)`.
      - If `lines` is empty → `sys.monitoring.set_local_events(DEBUGGER_ID, code, events.NO_EVENTS)`.
    - Calls `sys.monitoring.restart_events()` to re-enable any
      previously `DISABLE`d offsets.
  - `set_conditions(filepath, line, expression)` wires per-line conditions.

- [x] **2.4 Code-object registry via `PY_START`**
  - `PY_START` callback: `(code, instruction_offset) → object`.
  - Register `code` in `code_registry[code.co_filename]`.
  - If that file has active breakpoints, immediately call
    `set_local_events(DEBUGGER_ID, code, events.LINE)` so new
    functions are monitored as they are first entered.
  - Always returns `DISABLE` (code object now known; no need for future
    `PY_START` calls on this `(code, offset)` pair).

- [x] **2.5 Stepping support**
  - `set_stepping(STEP_IN)`:
    - `sys.monitoring.set_events(DEBUGGER_ID, events.LINE | events.PY_START | events.PY_RETURN)` globally.
  - `set_stepping(STEP_OVER)`:
    - Enable `LINE` only on the current code object via
      `set_local_events` (set by `capture_step_context`).
    - Enable `PY_RETURN` globally so we detect exiting the current frame.
  - `set_stepping(STEP_OUT)`:
    - Enable `PY_RETURN` globally; disable `LINE` on current code object.
  - `set_stepping(CONTINUE)`:
    - `sys.monitoring.set_events(DEBUGGER_ID, events.PY_START)`.
    - Re-enable per-code-object `LINE` events only for files with active breakpoints.
  - `capture_step_context(code)` records the code object used for
    `STEP_OVER` / `STEP_OUT` local event control.
  - `_on_py_return` transitions `STEP_OVER` / `STEP_OUT` → `STEP_IN`
    when the monitored frame exits.

- [x] **2.6 `CALL` callback for function breakpoints**
  - On `CALL` event, match the callable's `__qualname__` / `__name__`
    against the function-breakpoint set.
  - If match → call `debugger.user_call(frame, arg)`.
  - If no match → return `DISABLE`.
  - `update_function_breakpoints(names)` manages the set and adds /
    removes the `CALL` global event flag accordingly.

- [x] **2.7 Bridge to `DebuggerBDB`**
  - Added `integrate_with_backend(backend, debugger_instance)` to
    `dapper/_frame_eval/debugger_integration.py`.
  - If `SysMonitoringBackend`: calls `backend.install(debugger_instance)`
    directly — no `user_line` wrapping, no `sys.settrace`.
  - If `SettraceBackend` (or any other backend): delegates to the
    existing `integrate_debugger_bdb()` path unchanged.

- [x] **2.8 Integration tests for Phase 2**
  - Created `tests/unit/test_sys_monitoring_backend.py` (55 tests, all passing).
  - Covers: instantiation, install/shutdown lifecycle, DEBUGGER_ID conflict,
    code-object registry, breakpoint management, `LINE` callback (DISABLE /
    hit / conditional), stepping (all four modes, `PY_RETURN` transitions),
    `CALL` callback, `integrate_with_backend` routing, statistics shape,
    and concurrent thread safety.

---

### Phase 3 — Exception breakpoints & advanced events

- [ ] **3.1 Exception breakpoints**
  - Register `RAISE` callback.
  - On `RAISE`: inspect exception type against filter list from
    `ExceptionHandler`.
  - If match → call `debugger.user_exception(frame, exc_info)`.
  - If no match → return `DISABLE`.

- [ ] **3.2 "User-unhandled" exceptions via `EXCEPTION_HANDLED`**
  - Register `EXCEPTION_HANDLED` callback.
  - Track whether a `RAISE` was followed by `EXCEPTION_HANDLED`
    within user code (using `just_my_code.is_user_frame()`).
  - If the exception propagates out of user code without being
    handled → break.

- [ ] **3.3 `RERAISE` support**
  - Register `RERAISE` callback for `finally` / `except` re-raise
    detection.
  - Ensure exception info is correctly updated when re-raised.

- [ ] **3.4 Instruction-level stepping**
  - Register `INSTRUCTION` event only when
    `StepGranularity.INSTRUCTION` is active.
  - Replaces `frame.f_trace_opcodes = True`.
  - On `INSTRUCTION` callback → call `debugger.user_opcode(frame)`.
  - Unregister when stepping mode changes back to `LINE`.

- [ ] **3.5 Generator/coroutine support**
  - Handle `PY_YIELD` / `PY_RESUME` events to maintain correct
    stepping state across `yield` / `await` boundaries.
  - Ensure step-over does not "leak" into a resumed generator.

- [ ] **3.6 `BRANCH_LEFT` / `BRANCH_RIGHT` for coverage**
  - Use for coverage-aware breakpoints (feature idea §8).
  - Count branch executions with zero overhead when not actively
    debugging.
  - Use feature detection: `hasattr(sys.monitoring.events, 'BRANCH_LEFT')` (3.14+).
  - Fall back to deprecated `BRANCH` event on 3.12–3.13.

- [ ] **3.7 Tests for Phase 3**
  - Exception breakpoint fires on matching type.
  - "User-unhandled" exception correctly ignored when caught in user
    code.
  - Instruction stepping produces correct offsets.
  - Generator step-over stays in caller.
  - Async `await` stepping works correctly.

---

### Phase 4 — Performance optimisation & legacy deprecation

- [ ] **4.1 Remove Cython dependency on 3.12+**
  - The `_frame_evaluator.pyx` / `.c` extension exists to provide a
    C-level frame-eval hook. With `sys.monitoring`, this is
    unnecessary — the VM handles event dispatch natively.
  - Make Cython optional/legacy; skip compilation on 3.12+.
  - Update `build/frame-eval/` and `scripts/build_frame_eval.py`.

- [ ] **4.2 Deprecate `BytecodeModifier` on 3.12+**
  - `sys.monitoring.set_local_events()` + `DISABLE` replaces bytecode
    injection for breakpoint checks.
  - Keep `BytecodeModifier` for the settrace path only.
  - Add deprecation notice in docstrings.

- [ ] **4.3 Optimise `DISABLE` usage in `LINE` callback**
  - Profile: return `DISABLE` aggressively for every line that is NOT
    a breakpoint line to minimise callback invocations.
  - Ensure `restart_events()` is called only when breakpoints
    actually change (batch updates).

- [ ] **4.4 Optimise code-object registry memory**
  - Use `weakref.WeakSet` for code-object references to avoid
    preventing garbage collection of unloaded modules.

- [ ] **4.5 Benchmarks**
  - Compare wall-clock overhead:
    - (a) settrace + frame_eval (current).
    - (b) sys.monitoring (naive).
    - (c) sys.monitoring + `DISABLE` optimisation.
    - (d) no debugger attached.
  - Target: < 5% overhead for (c) with a small number of breakpoints
    set.
  - Publish results in `doc/reference/`.

---

### Phase 5 — Read-access watchpoints (feature idea §12)

- [ ] **5.1 Read watchpoints via `INSTRUCTION` events**
  - Use `INSTRUCTION` events on targeted code objects.
  - Inspect opcode at `instruction_offset` for variable-read
    operations: `LOAD_NAME`, `LOAD_FAST`, `LOAD_GLOBAL`,
    `LOAD_ATTR`.
  - Match against watched variable names.
  - Return `DISABLE` for non-matching instructions to minimise
    overhead.

- [ ] **5.2 Graceful fallback on < 3.12**
  - On Python < 3.12, fall back to the existing write-only
    `DataBreakpointState` behaviour.
  - Surface a capabilities flag in DAP `initialize` response:
    `supportsReadWatchpoints: True` only on 3.12+.

- [ ] **5.3 Tests for read watchpoints**
  - Read of a watched local variable triggers a stop.
  - Read of a watched global triggers a stop.
  - Read of a watched attribute triggers a stop.
  - Unwatched reads do not trigger (verify `DISABLE`).
  - Fallback on < 3.12 produces write-only behaviour.

---

## Files Affected

| Action | Path | Phase |
|--------|------|-------|
| **New** | `dapper/_frame_eval/tracing_backend.py` | 1 |
| **New** | `dapper/_frame_eval/settrace_backend.py` | 1 |
| **New** | `dapper/_frame_eval/monitoring_backend.py` | 2 |
| **Modify** | `dapper/_frame_eval/debugger_integration.py` | 2 |
| **New** | `tests/unit/test_sys_monitoring_backend.py` | 2 |
| **Modify** | `dapper/_frame_eval/config.py` | 1 |
| **Modify** | `dapper/_frame_eval/frame_eval_main.py` | 1 |
| **Modify** | `dapper/_frame_eval/compatibility_policy.py` | 1 |
| **Modify** | `dapper/_frame_eval/debugger_integration.py` | 2 |
| **Modify** | `dapper/core/debugger_bdb.py` | 2 |
| **Deprecate** | `dapper/_frame_eval/_frame_evaluator.pyx` | 4 |
| **Deprecate** | `dapper/_frame_eval/modify_bytecode.py` | 4 |
| **Modify** | `scripts/build_frame_eval.py` | 4 |

---

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| `LINE` callback receives `(code, line_number)` — no frame object | Use `sys._getframe(1)` inside callback, or track frames via `PY_START`; benchmark both approaches |
| `restart_events()` is global (all tools) | Only call when breakpoints actually change; document that Dapper may re-enable events for other tools (per CPython semantics) |
| Another tool already holds `DEBUGGER_ID` slot | Call `sys.monitoring.get_tool(DEBUGGER_ID)` at startup; if taken, fall back to `SettraceBackend` with a warning |
| Python 3.12/3.13 vs 3.14 behaviour differences | `BRANCH` deprecated in 3.14 in favour of `BRANCH_LEFT`/`BRANCH_RIGHT`; use `hasattr()` feature detection |
| Thread safety of callback registration | All `register_callback` / `set_events` calls happen on the main thread or under a lock; callbacks themselves are thread-safe (stateless lookups into immutable snapshots) |
| `sys._getframe()` may be slow or restricted | Profile; if problematic, switch to frame tracking via `PY_START` with a thread-local frame stack |
