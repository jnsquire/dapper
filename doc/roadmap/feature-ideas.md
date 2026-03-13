# Dapper — Feature Improvement Ideas

Ideas generated from a full codebase review, organised by theme.
Each item is unchecked and intended to be promoted into the main
[checklist](../reference/checklist.md) or a phase roadmap as work begins.

Legend
- [ ] Not started
- [x] Done / promoted to main checklist

---

## 1. Async Causality and Scheduling Insight

- [ ] **Async causality view** — when execution resumes in an `asyncio.Task`,
      show why that task became runnable: completion of a specific
      `Future`/`Task`, a loop callback, a timer, selector I/O readiness, or an
      explicit cross-thread wakeup. The goal is to answer "what resumed this
      task?" rather than only "where is it paused now?".
      **Potential shape:** emit a custom DAP event or expose a virtual scope /
      tool payload containing the most recent wakeup cause, scheduler edge, and
      related object reprs.
      **Likely implementation hooks:** `asyncio` task/future callbacks,
      event-loop scheduling helpers (`call_soon`, `call_later`, selector
      callbacks), and the existing pseudo-thread task-inspector plumbing.
      **Acceptance signal:** when stopped in async code, the user can see the
      last scheduling cause without manually reconstructing it from stack frames
      and event-loop internals.

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

- [ ] **Auto-attach to child processes (Phase 1 scaffold promoted)** — when the debuggee calls
      `subprocess.Popen`, `multiprocessing.Process`, or
      `concurrent.futures.ProcessPoolExecutor`, inject the Dapper launcher
      before `exec` so child processes are debuggable automatically.  
      **Current status:** Python `subprocess.Popen` child rewrite, lifecycle events, VS Code extension child-session attach plumbing, and process-tree / tracked-PID UX are implemented for rewritten Python subprocess launches. `multiprocessing.Process` / `ProcessPoolExecutor` still remain scaffold-level candidate detection outside the cases that already pass through rewritten Python subprocess launches. Attach-by-PID for already-running Python 3.14 interpreters is now implemented as a separate complementary flow rather than a future phase.
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
  - [ ] **Phase 2: `multiprocessing` + `ProcessPoolExecutor` coverage**
    - [x] Add scaffold-level detection hooks/events for
          `multiprocessing.Process` / `ProcessPoolExecutor` to support
          iterative rollout before full launcher injection.
    - [x] Handle `spawn` / `forkserver` launch paths where command lines are
          visible and safe to rewrite.
    - [x] Validate behavior across Linux/macOS/Windows transport defaults.
    - [x] Add limits/guardrails (max children, recursion prevention).
    - [ ] Promote scaffold detection to full child-session attach for direct
          `multiprocessing` / `ProcessPoolExecutor` launch paths that do not
          already flow through rewritten Python `subprocess.Popen` invocations.
    - Validation note: behavior is covered by unit-level launch rewrite tests
          and platform transport defaults; expand with full OS matrix runtime
          tests in CI as follow-up hardening.
  - [x] **Phase 2.5: extension child-session attach plumbing**
    - [x] Handle `dapper/childProcess`, `dapper/childProcessExited`, and
          `dapper/childProcessCandidate` in the VS Code extension.
    - [x] Replace the single-session IPC wiring with child-aware socket/session
          correlation.
    - [x] Start child debug sessions from correlated events instead of only
          emitting launch-side events.
  - [x] **Phase 3: process tree + tracked-PID UX polish**
    - [x] Add process lifecycle events (`started` / `exited`) sufficient for
          extension-side process tree rendering.
    - [x] Consume parent/child session IDs in the extension for actual tree
          grouping.
    - [x] Surface tracked PIDs in the extension TreeView with process/session
          commands so the process tree can be used as an active control surface.
    - [x] Document known limitations (non-Python children, shell wrappers,
          custom launchers).
    - [x] Wire tracked Python processes to true attach-by-PID instead of tree-only
          visibility and control affordances.
    - [ ] **Acceptance criteria (for promoting from idea to checklist)**
      - [x] With auto-attach enabled, Python `subprocess.Popen(...)` children
            emit attachable child-process events.
      - [x] With auto-attach disabled, launch behavior is unchanged.
      - [x] Patching is always cleaned up on session end (no global leakage).
      - [x] Existing launch/attach flows remain regression-free.
      - [x] Child-process events cause real child debug sessions to be created
            in VS Code.
      - [x] Parent/child sessions are grouped coherently in extension UX.
  - [x] **Phase 4: attach by PID for live Python 3.14 interpreters**
    - [x] Add a Python-side live-attach bootstrap that can be injected with
          `sys.remote_exec(pid, script)` and then connect back over Dapper's
          existing IPC transport.
    - [x] Extend DAP attach config parsing so `processId` is a first-class
          attach mode alongside direct IPC endpoint attach.
    - [x] Teach the VS Code debug adapter factory to allocate the IPC listener
          first, then invoke a local CPython 3.14 helper that performs the
          remote execution into the target process.
    - [x] Surface actionable diagnostics for version mismatch, disabled remote
          debugging, missing privileges, and bootstrap timeout cases.
    - [x] Add focused tests for the processId attach handshake.
    - [x] Document the Python 3.14 / permission constraints.

---

## 7. Execution Event Log (Lightweight Reverse Debugging)

- [x] **Structured execution history** — record every `stopped` event with a
      frame snapshot (locals, call stack) to an in-memory ring buffer.  Lets
      the user browse recent execution as a timeline without full rr-style
      time travel.  The telemetry infrastructure in
      `_frame_eval/telemetry.py` provides a pattern to follow.
- [ ] **Stop-reason diagnostics** — attach an explanation payload to stops that
      are technically correct but hard to interpret, such as async-aware step
      filtering, conditional breakpoint truthiness, exception-filter matches, or
      user-code re-entry after skipping event-loop frames.
      **Example explanations:** "stepped into event-loop machinery, then skipped
      to next user frame", "stopped because breakpoint condition `total > 100`
      evaluated truthy", or "paused because this exception matched the active
      uncaught filter".
      **Potential shape:** add a small structured explanation object to stopped
      snapshots / journal entries and optionally mirror it into a custom DAP
      event for extension UX.
      **Likely implementation hooks:** execution controller stop classification,
      breakpoint condition evaluation paths, async-aware stepping filters, and
      exception-breakpoint resolution.
      **Acceptance signal:** after a surprising stop, the user can see why the
      debugger chose that stop without inferring behavior from raw frames and
      internal filters.
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

## 12. Documentation Screenshot Infrastructure

Ideas for building automated, reproducible screenshot capture for the docs.

### Tier 1 — Manual Capture (immediate)

- [ ] **Install Flameshot for Linux** — `sudo apt install flameshot`.  Run
      `flameshot gui -p doc/img/vscode/` to capture annotated screenshots
      (arrows, highlights, blur) directly into the docs image directory.
- [ ] **ImageMagick post-processing script** — `scripts/process-screenshot.sh`
      that applies a consistent drop shadow and white border to all PNGs so
      every image looks uniform in the rendered site.
- [ ] **`doc/img/vscode/` directory** — centralised home for all VS Code UI
      screenshots.  Use the naming convention
      `vscode-{context}-{element}-{state}.png`
      (e.g. `vscode-debug-breakpoint-hit.png`).
- [ ] **Initial screenshot batch for [using-vscode.md](../getting-started/using-vscode.md)** — eight
      key captures: launch.json config, adapter terminal, breakpoint hit,
      Variables panel, Threads/async view, Call Stack, extension install, Debug
      Console.

### Tier 2 — Automated / CI-Driven Capture

- [ ] **`scripts/capture-screenshots.py` via Playwright + code-server** —
      launch `code-server` pointing at the dapper workspace, use Playwright to
      navigate to each debug state (open file → set breakpoint → start
      debugging → step), capture `page.screenshot()` for each panel.  Saves
      deterministic PNGs that can be regenerated after any UI change.
      ```bash
      pip install playwright && playwright install chromium
      npm install -g code-server
      python scripts/capture-screenshots.py
      ```
- [ ] **`@vscode/test-electron` + Electron capture (alternative)** — for
      pixel-perfect desktop VS Code screenshots (not web), use the existing
      `@vscode/test-electron` integration test harness together with
      Electron's `webContents.capturePage()`.  Run headlessly with
      `xvfb-run` in CI.
- [ ] **`xvfb-run` GitHub Actions job** — add a CI workflow step that runs
      `scripts/capture-screenshots.py` and commits updated images when the
      dapper version bumps, ensuring docs screenshots track releases
      automatically.
- [ ] **Stale-screenshot detection** — a `scripts/check-doc-images.sh` script
      that verifies every `![]()` image reference in the Markdown files points
      to an existing file, and optionally checks image mtimes against the
      last-modified date of the doc page that references them.
- [ ] **Baseline comparison with `pixelmatch`** — after an automated capture
      run, compare new PNGs against the committed baseline; fail CI only if
      the diff exceeds a configurable pixel-change threshold (to tolerate minor
      font rendering differences across OS versions).

### MkDocs image support

- [ ] **Add `glightbox` plugin** — `pip install mkdocs-glightbox`; add to
      `mkdocs.yml` so readers can click any screenshot to see it full-size.
- [ ] **Add `attr_list` extension** — enables `{ width="600" }` syntax on
      image references for responsive sizing without raw HTML.
- [ ] **Upgrade theme to `material`** (optional but unlocks image captions,
      dark mode, admonitions, and better overall DX).

---

## Priority Summary

| # | Area | User Impact | Estimated Effort |
|---|------|-------------|-----------------|
| 1 | Async task inspector | Very High | Medium |
| 2 | Async causality view | Very High | Medium–High |
| 3 | Stop-reason diagnostics | High | Medium |
| 4 | numpy / pandas / torch tensor summaries | High | Low–Medium |
| 5 | Object reference graph | High | Low–Medium |
| 6 | `__repr__` vs `__str__` toggle | High | Low–Medium |
| 7 | Expression watchpoints | High | Low (frame-eval infra exists) |
| 8 | Exception type filtering / "just my code" | High | Medium |
| 9 | Hot code reloading | High | High |
| 10 | Coverage-aware breakpoints | Medium | Low–Medium |
| 11 | Multi-process attach | Medium | High |
| 12 | Test framework integration | Medium | Medium |
| 13 | goto / jump-to-line | Medium | Low |
| 14 | Execution event log | Medium | Low–Medium |
| 15 | Read-access watchpoints | Medium | Medium |
| 16 | Doc screenshot capture (Tier 1 manual) | High | Low |
| 17 | Doc screenshot automation / CI (Tier 2) | Medium | Medium |

---

*Generated: 2026-02-20; updated: 2026-03-12*
