# Dapper — Feature Improvement Ideas

Ideas generated from a full codebase review, organised by theme.
Each item is unchecked and intended to be promoted into the main
[checklist](checklist.md) or a phase roadmap as work begins.

Legend
- [ ] Not started
- [x] Done / promoted to main checklist

---

## 2. Rich Variable Presentation

- [ ] **numpy / pandas / torch tensor summaries** — show shape, dtype, and a
      compact data preview instead of the full `repr` (which can hang the UI
      for large arrays).
- [ ] **Object reference graph** — a custom evaluate response or DAP event
      that serialises a shallow object graph; useful for spotting aliasing bugs
      and unintended shared-state.
- [ ] **`__repr__` vs `__str__` toggle** — let the user choose which
      representation the variable panel displays when both differ meaningfully
      (e.g. SQLAlchemy models, custom domain objects).

---

## 4. Hot Code Reloading During a Debug Session

- [x] **Reload-and-continue** — when stopped at a breakpoint, allow the user
      to edit source and apply the change without restarting.  Use
      `importlib.reload` + targeted frame-locals rebinding for functions
      already on the call stack.
- [x] **`loadedSource` changed event** — emit the DAP event after a reload so
      the editor refreshes its gutter decorations and breakpoint markers.

---

## 5. Expression Watchpoints / Set Expression

- [x] **Persistent expression watchpoints** — re-evaluate a Python expression
      after every step and break when the value changes.  The frame-eval
      `ConditionEvaluator` already compiles and caches expressions; this
      feature needs a persistent watch list wired to the step dispatch loop.
- [ ] **Set expression (`setExpression` DAP request)** — currently `❌` in the
      checklist; complements data breakpoints with expression-backed writes.

---

## 6. Multi-Process Debugging

- [ ] **Auto-attach to child processes** — when the debuggee calls
      `subprocess.Popen`, `multiprocessing.Process`, or
      `concurrent.futures.ProcessPoolExecutor`, inject the Dapper launcher
      before `exec` so child processes are debuggable automatically.
- [ ] **Process tree view** — expose multiple debuggees in the adapter's event
      stream so a DAP client can show a process tree and switch contexts.

---

## 7. Execution Event Log (Lightweight Reverse Debugging)

- [ ] **Structured execution history** — record every `stopped` event with a
      frame snapshot (locals, call stack) to an in-memory ring buffer.  Lets
      the user browse recent execution as a timeline without full rr-style
      time travel.  The telemetry infrastructure in
      `_frame_eval/telemetry.py` provides a pattern to follow.
- [ ] **Promote to full reverse execution** — once the event log is stable,
      consider wiring it to the DAP `reverseContinue` / `stepBack` requests
      (Phase 3 roadmap item).

---

## 8. Coverage-Aware Breakpoints

- [ ] **Per-line execution counts** — emit counts via a custom DAP event
      (e.g. `dapper/lineCoverage`) as lines are executed; the frame-eval
      tracing layer already visits every line.
- [ ] **Editor decoration support in VS Code extension** — use the counts to
      shade hit / unhit lines, making unexercised branches immediately visible
      without a separate coverage tool.

---

## 9. Test-Framework Integration

- [ ] **Parametrised-test context** — when stopped inside a `pytest`
      parametrised test, surface the current parameter set as a virtual scope
      in the variables panel.
- [ ] **Fixture inspection** — expose active pytest fixtures as a virtual
      scope in the stack frame view.
- [ ] **Re-run on save** — after a hot-reload edit (see §4), re-run the
      currently-paused test body automatically.

---

## 11. Richer Exception Filtering

- [ ] **Exception type filter** — break only on specific exception classes
      (e.g. `ValueError`, `KeyError`) rather than all raised exceptions.
- [ ] **Module-origin filter** — break on exceptions originating in user code
      but ignore those raised inside site-packages (analogous to debugpy
      "user-unhandled").
- [ ] **"Just my code" mode** — skip all frames inside site-packages /
      standard library entirely during stepping and stack display.

---

## 12. Read-Access Data Watchpoints

- [ ] **Read watchpoints via `sys.monitoring` (Python 3.12+)** — use
      `sys.monitoring.EVENTS` to detect reads of watched variables on 3.12+
      with a graceful fallback to the existing write-only watchpoint
      implementation on older versions.  (Write watchpoints are `🟡`;
      read-access detection is flagged in the checklist as remaining work.)

---

## 13. `goto` / Jump to Line

- [ ] **`gotoTargets` + `goto` DAP requests** — let the user drag the yellow
      execution arrow to an arbitrary line.  Python supports this via
      `frame.f_lineno` assignment for many (not all) cases; the adapter should
      validate feasibility and report it to the client.  (Currently `❌` in
      checklist.)

---

## Priority Summary

| # | Area | User Impact | Estimated Effort |
|---|------|-------------|-----------------|
| 1 | Async task inspector | Very High | Medium |
| 2 | numpy / pandas / torch tensor summaries | High | Low–Medium |
| 3 | Object reference graph | High | Low–Medium |
| 4 | `__repr__` vs `__str__` toggle | High | Low–Medium |
| 5 | Expression watchpoints | High | Low (frame-eval infra exists) |
| 6 | Exception type filtering / "just my code" | High | Medium |
| 7 | Hot code reloading | High | High |
| 8 | Coverage-aware breakpoints | Medium | Low–Medium |
| 9 | Multi-process attach | Medium | High |
| 10 | Test framework integration | Medium | Medium |
| 11 | goto / jump-to-line | Medium | Low |
| 12 | Execution event log | Medium | Low–Medium |
| 13 | Read-access watchpoints | Medium | Medium |

---

*Generated: 2026-02-20*
