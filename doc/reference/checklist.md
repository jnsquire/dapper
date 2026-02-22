# Dapper AI Debugger Features Checklist

A compact status matrix for Dapper's Debug Adapter Protocol (DAP) features and the near-term roadmap.

Legend
- ✅ Implemented
- 🟡 Partial / in-progress
- ❌ Not implemented

---

## Core Debugging Features

### Program control
- ✅ Launch (start a new Python program under debugger)
- ✅ Attach (attach to running program)
- ✅ Restart
- ✅ Disconnect
- ✅ Terminate

### Execution control
- ✅ Continue
- ✅ Pause
- ✅ Next (step over)
- ✅ Step In
- ✅ Step Out
- ✅ Async-aware stepping — `next`/`stepIn` over `await` skips event-loop internals and lands in user code (asyncio / concurrent.futures frames filtered via `_is_event_loop_frame`); see [Async Debugging reference](async-debugging.md)
- ❌ Reverse Continue (reverse debugging)
- ✅ Step granularity (instruction-level stepping) — `StepGranularity` enum; `line`/`statement`/`instruction` forwarded end-to-end; `user_opcode` + `f_trace_opcodes` for instruction stepping

---

## Breakpoints

### Source breakpoints
- ✅ Set / remove source breakpoints (line-level, verified/unverified)
- 🟡 Breakpoint conditions (basic condition evaluation supported; more advanced expressions & testing ongoing)
- ✅ Hit conditions (N-th hit / modulo / comparisons; implemented by BreakpointResolver)
- ✅ Log points (formatting & output without stopping; see Breakpoints Controller page)

### Function breakpoints
- ✅ Set function breakpoints (adapter + debug launcher support)
- 🟡 Function breakpoint conditions (resolver supports them; more test coverage is desirable)

### Exception breakpoints
- ✅ Set exception breakpoints (raised/uncaught filters supported)
- 🟡 Exception options / advanced filtering (work in progress)

### Data breakpoints
- 🟡 Data breakpoint requests & bookkeeping (dataBreakpointInfo, setDataBreakpoints implemented; adapter advertises capability)
- 🟡 Runtime watchpoints (trigger on write) — supported when the debugger registers watches (in-process already works; launcher/adapter now register watches so subprocess mode can use this). Read-access detection and broader integration work remain.

Reference: see Architecture — [Breakpoints Controller](../architecture/breakpoints_controller.md) for design notes and Phase 1 status.

---

## Runtime introspection

### Threads & frames
- ✅ Threads listing and basic metadata
- ✅ Dynamic thread names (live names read from `threading.enumerate()` at query time)
- ✅ Asyncio task inspector — live `asyncio.Task` objects exposed as pseudo-threads with full coroutine call stacks
- ✅ Stack traces (frames, locations, ids)
- ✅ Source references for non-filesystem sources (runtime source registry: `eval`, `exec`, `compile`, Cython intermediates)

### Variables & scopes
- ✅ Scopes (locals/globals)
- ✅ Variables listing
- ✅ Set variable (support for complex types and conversions)
- ✅ Variable presentation / presentationHint — see [Variable Presentation reference](variable-presentation.md)

### Expression evaluation
- 🟡 Evaluate expressions in-frame (existing Frame Evaluation support; see FRAME_EVAL docs)
- ❌ Set expression / expression-backed watchpoints
- ✅ Completions / auto-complete for expression editors

Useful links: frame-eval docs — `doc/getting-started/frame-eval/index.md`, `doc/architecture/frame-eval/implementation.md`, `doc/architecture/frame-eval/performance.md`.

---

## Advanced features / code navigation
- ✅ Loaded sources listing (what's present in runtime)
- ✅ Source request handling (adapter supports `source` and `moduleSource` requests)
- 🟡 Hot code reload / reload-and-continue (`supportsHotReload`, `dapper/hotReload`, `dapper/hotReloadResult`) — protocol/types, request handler, and in-process runtime reload service implemented (module reload, breakpoint reapply, events); external-process support and frame-local rebinding remain
- ❌ Goto targets (find jump targets / navigation helpers — planned)
- ✅ Modules listing
- ❌ Module source retrieval (not fully supported in all backends)

---

## Implementation status — short summary

Dapper provides a stable, functional core debugger experience: program control, stepping, breakpoint management, stack/threads, variables and set-variable operations are implemented and well-tested. Expression completions are implemented. Async/concurrency debugging is fully supported — asyncio tasks appear as pseudo-threads, stepping is async-aware, and thread names are live. Structured variable rendering (dataclasses, namedtuples, Pydantic v1 & v2) is implemented with field-level expansion and presentation hints. Work remains on higher-level ergonomics: advanced breakpoint workflows (runtime watchpoints), source navigation UX, and profiling integration.

---

## Priorities & roadmap (high-level)

Phase 1 — core polish (current)
- ✅ Improve expression evaluation ergonomics (completions implemented, evaluate works). See: `doc/getting-started/frame-eval/index.md` and `doc/architecture/frame-eval/implementation.md`.

Phase 2 — enhanced debugging experience (in-progress)
- ✅ Asyncio task inspector and async-aware stepping (complete). See: [Async Debugging reference](async-debugging.md).
- ✅ Structured variable rendering — dataclasses, namedtuples, Pydantic (complete). See: [Variable Presentation reference](variable-presentation.md).
- Improve source navigation & request-level support (goto targets, richer `source` handling). Tests & partial support already present (see `architecture/breakpoints_controller.md` and existing adapter handlers).

Phase 3 — advanced features (future)
- Runtime watchpoints / data breakpoint triggers (Phase 1 bookkeeping implemented; runtime triggers are now supported when watches are registered — further work remains for read-access detection, per-address watches, and cross-process robustness)
- Reverse debugging / time-travel
- Performance profiling integration and tooling

---

## Tests & coverage snapshot
- Tests exercise core DAP features extensively (adapter + launcher + core components).
- Areas flagged for additional unit/integration coverage: some breakpoint edge cases and runtime watchpoint behaviors.

---

*Last updated: 2026-02-21*


This document outlines the Debug Adapter Protocol (DAP) features implemented in Dapper, organized by category.
