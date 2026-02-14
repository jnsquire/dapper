# Breakpoints Controller (Architecture)

This page documents the design and responsibilities of the *Breakpoints Controller* component inside Dapper's debug adapter. It belongs in the Architecture section because it describes how breakpoints, log points, function and exception breakpoints, and data breakpoint bookkeeping are coordinated at the adapter level.

## Purpose

- Centralize breakpoint state and policies used by the adapter's request handlers.
- Provide utility behaviour for `setBreakpoints`, `setFunctionBreakpoints`, `setExceptionBreakpoints`, `setDataBreakpoints` and related requests.
- Implement non-stopping log points (log messages emitted without stopping the debuggee) and provide safe formatting/evaluation rules.

## Responsibilities

1. Breakpoint bookkeeping — track source breakpoints (verified/unverified), function/exception breakpoint metadata, and data breakpoint bookkeeping.
2. Provide consistent and testable responses to DAP breakpoint requests across different backends (in-process vs external process).
3. Manage lifecycle hooks for breakpoint-related resources (temporary unix socket paths, injected bytecode marks, or runtime data watches).
4. Support runtime log point formatting in a secure and performant manner when executed inside the debugged program.

## Design notes (high level)

- Keep the controller as a focused translator between the adapter request handlers and lower-level debugger/launcher APIs. Do not mix transport or protocol handling here — this focuses on the breakpoint domain only.
- Make components testable and observable (clear invariants: verified vs unverified breakpoints, stable id generation for data watches, predictable lifecycle transitions).

## Implementation pointers

- Tests should exercise the request/response surface: `setBreakpoints`, `setFunctionBreakpoints`, `setExceptionBreakpoints`, `setDataBreakpoints`, `dataBreakpointInfo`.
- When implementing log points, ensure formatting is performed in a sandboxed or minimized evaluation routine to avoid unexpected side-effects in the debugged program.
- Architect the design to allow a Phase 1 bookkeeping-only implementation for data breakpoints with later phases activating runtime watchpoints.

## See also

- Checklist & status: [CHECKLIST & status](../reference/checklist.md)
- Frame evaluation (usage & guidance): [Frame Evaluation user guide](../getting-started/frame-eval/index.md)
- Operational modes & diagrams: [Operational modes (reference)](../reference/operational_modes.md)

### Code & tests

- Adapter request handlers (breakpoint wiring): `dapper/adapter/request_handlers.py`
- Adapter IPC and lifecycle touches: `dapper/adapter/server.py`
- Tests exercising log points / breakpoint flows: `tests/integration/test_log_points.py`
