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
- ❌ Reverse Continue (reverse debugging)
- ❌ Step granularity (instruction-level stepping)

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
- ❌ Dynamic thread names (improvements possible)
- ✅ Stack traces (frames, locations, ids)
- ❌ Source references for non-filesystem sources (e.g., generated content)

### Variables & scopes
- ✅ Scopes (locals/globals)
- ✅ Variables listing
- ✅ Set variable (support for complex types and conversions)
- 🟡 Variable presentation / presentationHint (supported; expanding coverage)

### Expression evaluation
- 🟡 Evaluate expressions in-frame (existing Frame Evaluation support; see FRAME_EVAL docs)
- ❌ Set expression / expression-backed watchpoints
- ✅ Completions / auto-complete for expression editors

Useful links: frame-eval docs — `doc/getting-started/frame-eval/index.md`, `doc/architecture/frame-eval/implementation.md`, `doc/architecture/frame-eval/performance.md`.

---

## Advanced features / code navigation
- ✅ Loaded sources listing (what's present in runtime)
- ✅ Source request handling (adapter supports `source` and `moduleSource` requests)
- ❌ Goto targets (find jump targets / navigation helpers — planned)
- ✅ Modules listing
- ❌ Module source retrieval (not fully supported in all backends)

---

## Implementation status — short summary

Dapper provides a stable, functional core debugger experience: program control, stepping, breakpoint management, stack/threads, variables and set-variable operations are implemented and well-tested. Expression completions are now implemented. Work remains on higher-level ergonomics: advanced breakpoint workflows (runtime watchpoints), source navigation UX and profiling integration.

---

## Priorities & roadmap (high-level)

Phase 1 — core polish (current)
- ✅ Improve expression evaluation ergonomics (completions implemented, evaluate works). See: `doc/getting-started/frame-eval/index.md` and `doc/architecture/frame-eval/implementation.md`.

Phase 2 — enhanced debugging experience (in-progress)
- Improve source navigation & request-level support (goto targets, richer `source` handling). Tests & partial support already present (see `architecture/breakpoints_controller.md` and existing adapter handlers).
- Expand variable presentation semantics and UI hints (`presentationHint` coverage).

Phase 3 — advanced features (future)
- Runtime watchpoints / data breakpoint triggers (Phase 1 bookkeeping implemented; runtime triggers are now supported when watches are registered — further work remains for read-access detection, per-address watches, and cross-process robustness)
- Reverse debugging / time-travel
- Performance profiling integration and tooling

---

## Tests & coverage snapshot
- Tests exercise core DAP features extensively (adapter + launcher + core components).
- Areas flagged for additional unit/integration coverage: some breakpoint edge cases and runtime watchpoint behaviors.

---

*Last updated: 2025-11-30*

This document outlines the Debug Adapter Protocol (DAP) features implemented in Dapper, organized by category.

## Legend
- ✅ **Implemented**: Feature is fully implemented and tested
- 🟡 **Partial**: Feature is partially implemented or has basic support
- ❌ **Not Implemented**: Feature is not yet implemented
- 🔄 **In Progress**: Feature is currently being worked on

---

## Core Debugging Features

### Program Control
### Execution Control
- ❌ **Reverse Continue**: Continue backwards in execution
- ❌ **Step Granularity**: Control stepping granularity (statement/line/instruction)
  - Supports stop-on-entry
 - ✅ **Hit Conditions**: Break after N hits (implemented via BreakpointResolver)
 - ✅ **Log Points**: Log messages without stopping (implemented; see [Breakpoints Controller](../architecture/breakpoints_controller.md))
- ✅ **Restart**: Restart the debugged program
 - ✅ **Set Function Breakpoints**: Set breakpoints on function names (adapter request handler implemented)
 - 🟡 **Function Breakpoint Conditions**: Conditions for function breakpoints (partial — resolver supports them; adapter/tests coverage varies)
### Execution Control
- ✅ **Continue**: Continue execution until next breakpoint
### Advanced Features
### Source Code
 - ✅ **Loaded Sources**: List all loaded source files
 - ✅ **Source**: Request source code content (implemented — adapter handles `source`/`moduleSource` requests)
- ✅ **Step In**: Step into function calls
### Phase 1: Complete Basic Features (Current Priority)
- Implement attach, restart (completed)
- ✅ Expression evaluation with completions implemented. See [Frame Evaluation user guide](../getting-started/frame-eval/index.md) and [implementation notes](../architecture/frame-eval/implementation.md).
- ❌ **Step Granularity**: Control stepping granularity (statement/line/instruction)
### Phase 2: Enhanced Debugging Experience (in-progress)
- Complete source code requests & navigation (source content requests, goto targets, source references) — basic source requests are implemented; see `source`/`moduleSource` handling and related tests, and the [Breakpoints Controller](../architecture/breakpoints_controller.md) for navigation helpers.
- ✅ Add expression completions / auto-complete (implemented)
- Improve variable presentation (presentation hints already present; expand coverage and UI semantics)
---
### Phase 3: Advanced Features (future)
- Reverse debugging capabilities (not implemented)
 - Data breakpoints and runtime watchpoints (bookkeeping requests implemented; runtime triggers / watchpoints remain) — see [Breakpoints Controller](../architecture/breakpoints_controller.md) and protocol `dataBreakpointInfo`/`setDataBreakpoints` handling.
- Performance profiling integration (future work)
- ✅ **Set Breakpoints**: Set/remove breakpoints in source files
  - Basic line breakpoints
  - Verified/unverified status
- 🟡 **Breakpoint Conditions**: Basic condition support
- ❌ **Hit Conditions**: Break after N hits
- ❌ **Log Points**: Log messages without stopping

### Function Breakpoints
### Function Breakpoints
- 🟡 **Set Function Breakpoints**: Set breakpoints on function names
  - Note: low-level support exists in the debugger and launcher (PyDebugger + debug launcher handlers), but the adapter `RequestHandler` currently does not expose a `_handle_setFunctionBreakpoints` method to DAP clients.
- ❌ **Function Breakpoint Conditions**: Conditions for function breakpoints

### Exception Breakpoints
### Exception Breakpoints
- 🟡 **Set Exception Breakpoints**: Break on raised/uncaught exceptions
  - Supports "uncaught" and "raised" filters
  - Note: the debugger and launcher support exception breakpoints, but the adapter currently lacks a `_handle_setExceptionBreakpoints` method on `RequestHandler` to expose this to clients.
- ❌ **Exception Options**: Advanced exception filtering options

### Data Breakpoints
- 🟡 **Data Breakpoints (Phase 1)**: Requests implemented (dataBreakpointInfo, setDataBreakpoints) and server advertises capability. Currently bookkeeping only – no runtime stop on change yet.
- ❌ **Watchpoints (runtime triggers)**: Break when variable values change (Phase 2 planned: compare stored values per line and emit `stopped` with reason `data breakpoint`).

---

## Runtime Information

### Threads
- ✅ **Threads**: Get list of active threads
  - Thread IDs and names
- ✅ **Thread Names**: Dynamic thread naming (live names read from `threading.enumerate()` at query time)

### Stack Frames
- ✅ **Stack Trace**: Get stack frames for a thread
  - Frame IDs, names, source locations
  - Line and column information
- ❌ **Source References**: Handle source code not in filesystem

### Variables and Scopes
- ✅ **Scopes**: Get variable scopes for a frame
  - Local and Global scopes
- ✅ **Variables**: Get variables in a scope
  - Basic variable listing
- ✅ **Set Variable**: Modify variable values during debugging
  - Supports local and global scopes
  - Enhanced support for complex objects, lists, and dictionaries
  - Type conversion with context awareness
  - Expression evaluation for variable values
  - Object attribute modification
  - List element modification by index
  - Dictionary key-value setting
  - Error handling for invalid operations and immutable types
- 🟡 **Variable Presentation**: Rich variable display hints
  - Supported fields (DAP VariablePresentationHint):
    - `kind` (string): semantic kind; recommended values include `property`, `method`, `class`, `data`, `event`, `baseClass`, `innerClass`, `interface`, `mostDerivedClass`, `virtual`.
    - `attributes` (string[]): badges/flags; recommended values include `static`, `constant`, `readOnly`, `rawString`, `hasObjectId`, `canHaveObjectId`, `hasSideEffects`, `hasDataBreakpoint`.
    - `visibility` (string): `public`, `private`, `protected`, `internal`, `final`.
    - `lazy` (boolean): when true, the client should present a UI affordance to fetch the value (useful for getters or expensive evaluations). When `lazy` is used, `variablesReference` is expected to point at the value provider.
  - Notes: The adapter returns these hints as part of each `Variable`'s `presentationHint`. Clients may map `kind` and `attributes` to icons, styles, or tooltips. Prefer `hasDataBreakpoint` attribute over the deprecated `dataBreakpoint` kind.
  - Examples:
    - Property (read-only):

      ```json
      {
        "presentationHint": { "kind": "property", "attributes": ["readOnly"], "visibility": "public" }
      }
      ```

    - Lazy property (expensive getter):

      ```json
      {
        "presentationHint": { "kind": "property", "lazy": true, "attributes": ["canHaveObjectId"] },
        "variablesReference": 123
      }
      ```

### Expression Evaluation
- ✅ **Evaluate**: Evaluate expressions in debug context
  - Basic expression evaluation
  - Supports different contexts (hover, watch, etc.)
- ❌ **Set Expression**: Set expressions for watchpoints
- ✅ **Completions**: Auto-complete for expressions

---

## Advanced Features

### Source Code
- ✅ **Loaded Sources**: List all loaded source files
- ❌ **Source**: Request source code content
- ❌ **Goto Targets**: Find possible goto locations

### Modules
- ✅ **Modules**: List loaded modules
- ❌ **Module Source**: Get module source code

### Exceptions
- ✅ **Exception Info**: Detailed exception information
- ❌ **Set Exception Breakpoints**: Advanced exception filtering

### Configuration
- ✅ **Initialize**: Basic DAP initialization
- ✅ **Configuration Done**: Signal configuration completion
- ✅ **Capabilities**: Report supported features

---

## Implementation Status Summary

### Current Implementation Level: **Stable basic debugger + advanced work in progress**

Many of the essential DAP features are implemented and covered by tests (program control, execution control, breakpoints, threads/stack/variables, and variable modification). Work continues on higher-level ergonomics such as expression completion, richer breakpoint options and runtime watchpoints.

---

## Priority Implementation Order

### High Priority (Essential for the remaining core gaps)
1. ✅ **Completions** - Expression auto-completion (implemented)
2. **Source References** - Support source locations that are not direct filesystem paths

### Medium Priority (Enhanced debugging experience)
1. **Data Breakpoints** - Variable watchpoints (runtime triggers)
2. **Log Points** - Non-stopping breakpoints / log messages
3. **Goto Targets** - Navigation features

### Low Priority (Advanced features)
1. **Reverse Debugging** - Step back, reverse continue
2. **Step Granularity** - Fine-grained stepping control

---

## Testing Coverage

Current test coverage for debugger features:
- **debugger.py**: 64% coverage
- **server.py**: 82% coverage (DAP request handling)
- **Total**: 56% overall coverage

### Well Tested Features
- ✅ Launch process
- ✅ Set breakpoints
- ✅ Execution control (continue, pause, stepping)
- ✅ Thread management
- ✅ Stack trace retrieval
- ✅ Variable inspection
- ✅ Variable modification

### Under Tested Features
- 🟡 Exception breakpoints
- 🟡 Function breakpoints
- 🟡 Expression evaluation
- ❌ Advanced DAP features (not implemented yet)

---

## Future Development Roadmap

### Phase 1: Complete Basic Features (Current Priority)
- ✅ Expression evaluation with completions implemented

### Phase 2: Enhanced Debugging Experience (in-progress)
- Complete source code requests & navigation (source content requests, goto targets, source references) — note: "Loaded Sources" and basic module listing are implemented, so this work focuses on request-level support and navigation helpers.
- ✅ Add expression completions / auto-complete (implemented)
- Improve variable presentation (presentation hints already present; expand coverage and UI semantics)

### Phase 3: Advanced Features (future)
- Reverse debugging capabilities (not implemented)
- Data breakpoints and runtime watchpoints (bookkeeping requests implemented; runtime triggers / watchpoints remain)
- Log points and hit conditions (not implemented)
- Performance profiling integration (future work)

---

*Last updated: November 30, 2025*
*Coverage data: 56% overall, 64% debugger module*

