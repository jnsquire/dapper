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

## 5. Expression Watchpoints / Set Expression

- [x] **Set expression (`setExpression` DAP request)** — complements data
      breakpoints with expression-backed writes.

---

## 6. Multi-Process Debugging

- [x] **Auto-attach to child processes (Phase 1 scaffold promoted)** — when the debuggee calls
      `subprocess.Popen`, `multiprocessing.Process`, or
      `concurrent.futures.ProcessPoolExecutor`, inject the Dapper launcher
      before `exec` so child processes are debuggable automatically.  
      **Current status:** Phase 1 (`subprocess.Popen` Python children) is implemented;
      Phase 2/3 work remains.
- [ ] **Auto-attach implementation roadmap (Phase 1–3)**
  - [x] **Phase 1 (MVP): `subprocess.Popen` for Python children**
    - [x] Add launch config flag to enable/disable child auto-attach
          (default off for safety).
    - [x] Wire `SubprocessManager` into external launch lifecycle
          (enable on launch, disable on terminate/disconnect).
    - [x] Intercept Python child commands and rewrite to launcher form,
          preserving script/module args.
    - [x] Emit `dapper/childProcess` event with PID, parent PID, command,
          and IPC endpoint for extension-side attach.
    - [x] Add tests: detection, arg rewrite, patch/unpatch behavior,
          event payload, non-Python passthrough.
      - [x] **Phase 2: `multiprocessing` + `ProcessPoolExecutor` coverage**
    - [x] Add scaffold-level detection hooks/events for
          `multiprocessing.Process` / `ProcessPoolExecutor` to support
          iterative rollout before full launcher injection.
            - [x] Handle `spawn` / `forkserver` launch paths where command lines are
          visible and safe to rewrite.
            - [x] Validate behavior across Linux/macOS/Windows transport defaults.
            - [x] Add limits/guardrails (max children, recursion prevention).
                - Validation note: behavior is covered by unit-level launch rewrite tests
                      and platform transport defaults; expand with full OS matrix runtime
                      tests in CI as follow-up hardening.
  - [ ] **Phase 3: process tree + UX polish**
    - [x] Add process lifecycle events (`started` / `exited`) sufficient for
          extension-side process tree rendering.
    - [x] Associate child sessions to parent session IDs for tree grouping.
      - [x] Document known limitations (non-Python children, shell wrappers,
          custom launchers).
      - [x] **Acceptance criteria (for promoting from idea to checklist)**
            - [x] With auto-attach enabled, Python `subprocess.Popen(...)` children
          emit attachable child-process events.
            - [x] With auto-attach disabled, launch behavior is unchanged.
            - [x] Patching is always cleaned up on session end (no global leakage).
            - [x] Existing launch/attach flows remain regression-free.
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
