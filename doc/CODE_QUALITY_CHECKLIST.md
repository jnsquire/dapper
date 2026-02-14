# Code Quality Checklist

This checklist turns the current review findings into incremental, low-risk work items.

## How to use

- Work top-to-bottom; each phase is intended to be a small PR.
- Fill in **Owner**, **Estimate**, and **Target PR** before starting each item.
- Mark each checkbox as complete as you merge.

---

## Phase 1 — Config and tooling hygiene (low risk)

| Task | Owner | Estimate | Target PR |
|---|---|---:|---|
| [x] Normalize Ruff config sections to one schema in `pyproject.toml` |  |  |  |
| [x] Remove conflicting/dead Ruff keys and validate with a clean lint run |  |  |  |
| [x] Move `pyright` from runtime dependencies to dev dependencies |  |  |  |
| [x] Document lint/typecheck commands in contributor docs |  |  |  |

### Exit criteria

- [x] `ruff check` runs with expected config and no config warnings
- [x] package install for end users no longer pulls type-check tooling

---

## Phase 2 — Exception handling hardening

| Task | Owner | Estimate | Target PR |
|---|---|---:|---|
| [x] Replace broad `except Exception` in hot command paths with specific exceptions |  |  |  |
| [x] Add debug-level logging for fallback/error-swallow paths |  |  |  |
| [ ] Standardize DAP error response shape across handlers |  |  |  |
| [ ] Add tests for expected failure modes (bad args, missing frame, conversion failures) |  |  |  |

### Exit criteria

- [ ] No silent failure in critical command dispatch paths
- [ ] Failure paths are observable in logs and validated by tests

### Progress notes

- Phase 1 completed except final Ruff validation run.
- Phase 2 substantially in progress in `dapper/shared/command_handlers.py`; focused hardening shipped without behavior regressions.
- Current regression status after each Phase 2 slice: `uv run pytest` passes (`1101 passed, 10 skipped`).
- `uv run ruff check .` passes after applying safe and unsafe Ruff auto-fixes, plus one manual `TRY300` cleanup.
- Current validation status: `uv run ruff check .` passes and `uv run pytest` passes (`1101 passed, 10 skipped`).

---

## Phase 3 — Handler deduplication

| Task | Owner | Estimate | Target PR |
|---|---|---:|---|
| [ ] Select a single canonical handler implementation module |  |  |  |
| [ ] Convert duplicate module to thin wrappers/delegation only |  |  |  |
| [ ] Add tests asserting pipe-IPC and socket-IPC use same behavior |  |  |  |
| [ ] Remove dead helper code that became redundant after deduplication |  |  |  |

### Exit criteria

- [ ] One source of truth for command logic
- [ ] Both IPC pathways pass the same behavioral test suite

---

## Phase 4 — Eval and conversion safety

| Task | Owner | Estimate | Target PR |
|---|---|---:|---|
| [ ] Centralize value/expression conversion in one utility |  |  |  |
| [ ] Guard runtime `eval` use with explicit policy checks and strict context |  |  |  |
| [ ] Add tests for malformed and hostile-like input cases |  |  |  |
| [ ] Ensure conversion errors map to consistent user-facing messages |  |  |  |

### Exit criteria

- [ ] Dynamic evaluation behavior is explicitly controlled and test-covered
- [ ] Conversion behavior is consistent across handlers

---

## Phase 5 — Adapter server modularization (largest change)

| Task | Owner | Estimate | Target PR |
|---|---|---:|---|
| [ ] Extract server lifecycle and transport orchestration into dedicated module(s) |  |  |  |
| [ ] Extract debugger runtime/state management into dedicated module(s) |  |  |  |
| [ ] Keep public API compatibility with thin compatibility layer |  |  |  |
| [ ] Add/adjust integration tests to protect launch/attach/regression paths |  |  |  |
| [ ] Update architecture docs with new module boundaries |  |  |  |

### Exit criteria

- [ ] Reduced file size and clearer ownership boundaries
- [ ] Existing launch/attach scenarios continue to pass integration tests

---

## Cross-cutting quality gates (apply to every phase)

- [ ] Add or update tests for every behavior change
- [ ] Keep PRs narrow and independently releasable
- [ ] Avoid unrelated refactors in the same PR
- [ ] Include rollback notes for risky behavior changes
- [ ] Update docs/changelog notes for externally visible behavior changes

---

## Suggested PR order

1. Config/tooling hygiene
2. Exception hardening
3. Handler deduplication
4. Eval/conversion safety
5. Adapter server modularization
