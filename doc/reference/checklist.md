# Dapper Debugger — Features Checklist

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
- ✅ Attach by PID for live Python 3.14 processes (`processId`) — the extension allocates the IPC listener, spawns `dapper.launcher.attach_by_pid`, reuses the normal socket-backed session flow after a `sys.remote_exec()` bootstrap inside the target interpreter, and surfaces targeted diagnostics for version, remote-debugging, privilege, and bootstrap-timeout failures.
- ✅ Restart
- ✅ Disconnect
- ✅ Terminate

### Execution control
- ✅ Continue
- ✅ Pause
- ✅ Next (step over)
- ✅ Step In
- ✅ Step Out
- ✅ Async-aware stepping — `next`/`stepIn` over `await` skips event-loop internals and lands in user code (asyncio / concurrent.futures frames filtered via `_is_event_loop_frame`); see [Async Debugging reference](../guides/async-debugging.md)
- ✅ Automatic sys.monitoring tracing backend on Python 3.12+ (configurable via `FrameEvalConfig.tracing_backend`) for lower-overhead breakpoints and stepping
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
- 🟡 Runtime watchpoints (trigger on write/value change/read) — variable and expression watchpoints are supported when watches are registered (including `frame:<id>:expr:<expression>`), and read watchpoints are available on Python 3.12+ via `sys.monitoring` (name-read scope). On older versions, read access types gracefully fall back to write semantics. Broader cross-process/read-precision integration work remains. See [Watchpoints reference](../guides/watchpoints.md).

Reference: see Architecture — [Breakpoints Controller](../architecture/breakpoints.md) for design notes and Phase 1 status.

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
- ✅ Variable presentation / presentationHint — see [Variable Presentation reference](../guides/variable-presentation.md)

### Expression evaluation
- 🟡 Evaluate expressions in-frame — [Frame Evaluation](../guides/frame-eval.md) backend; partial support
- 🟡 Expression-backed watchpoints via `setDataBreakpoints` (`frame:<id>:expr:<expression>`)
- ✅ Set expression (`setExpression` DAP request)
- ✅ Completions / auto-complete for expression editors

See also: [Frame Eval User Guide](../guides/frame-eval.md).

---

## Advanced features / code navigation
- ✅ Loaded sources listing (what's present in runtime)
- ✅ Source request handling (adapter supports `source` and `moduleSource` requests)
- 🟡 Hot code reload / reload-and-continue (`supportsHotReload`, `dapper/hotReload`, `dapper/hotReloadResult`) — protocol/types, request handler, runtime reload service, frame-local rebinding, adapter-mediated external-process path, and VS Code command/auto-on-save are implemented. Remaining work is mainly option/runtime parity (`rebindFrameLocals`, `patchClassInstances`) and broader end-to-end hardening. See [Hot Reload reference](../guides/hot-reload.md).
- 🟡 Multi-process child auto-attach (`subprocessAutoAttach`, `dapper/childProcess`, `dapper/childProcessExited`, `dapper/childProcessCandidate`) — Python-side `subprocess.Popen` rewrite, child lifecycle event emission, VS Code child-session attach plumbing, and extension tree grouping are implemented for Python script/module/code invocations, with session IDs and recursion guardrails propagated in launcher args and events. Remaining work is broader runtime hardening plus promoting direct `multiprocessing` / `ProcessPoolExecutor` launch paths beyond scaffold-level candidate detection when they do not already flow through rewritten Python subprocess launches.
- ❌ Goto targets (find jump targets / navigation helpers — planned)
- ✅ Modules listing
- ❌ Module source retrieval (not fully supported in all backends)

---

## Implementation status — short summary

Dapper provides a stable, functional core debugger experience: program control, stepping, breakpoint management, stack/threads, variables and set-variable operations are implemented and well-tested. Expression completions are implemented. Async/concurrency debugging is fully supported — asyncio tasks appear as pseudo-threads, stepping is async-aware, and thread names are live. Structured variable rendering (dataclasses, namedtuples, Pydantic v1 & v2) is implemented with field-level expansion and presentation hints. Work remains on higher-level ergonomics: advanced breakpoint workflows (runtime watchpoints), source navigation UX, and profiling integration.

---

## Roadmap (near-term)

- Source navigation & goto targets — tests and partial `source` handling exist; goto targets planned
- Runtime watchpoints — bookkeeping and runtime triggers implemented; read-access detection, per-address watches, and cross-process robustness remain
- Hot reload option/runtime parity — core reload flow is implemented; remaining work is optional behavior parity and broader integration coverage
- Process-tree UX for multi-process attach — tree grouping is implemented via the extension process TreeView; broader runtime matrix hardening and polish remain
- Documentation screenshot automation — add a Playwright + code-server capture flow for reproducible VS Code docs screenshots, with manual capture remaining the short-term fallback
- Reverse debugging / time-travel (future)
- Performance profiling integration (future)

For a fuller list of ideas and proposed work, see the [Roadmap](../roadmap/feature-ideas.md).

*Last updated: 2026-03-06*
