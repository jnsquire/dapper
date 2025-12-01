# Breakpoints Controller

This page describes the Breakpoints Controller in Dapper — the high-level design and the responsibilities that coordinate breakpoints, log points, function & exception breakpoints, and data breakpoints.

## Purpose

- Centralize breakpoint handling and bookkeeping for the adapter/debugger.
- Provide higher-level helpers and policies used by request handlers (e.g., `setBreakpoints`, `setFunctionBreakpoints`, `setExceptionBreakpoints`, `setDataBreakpoints`).
- Implement non-stopping log points (log messages that do not pause execution).

## Responsibilities

1. Maintain breakpoint state
   - Track sources, verified flags, and helper metadata.
   - Provide consistent responses to `setBreakpoints` and related requests.

2. Handle function & exception breakpoints
   - Translate high-level function breakpoints into underlying runtime checks where available.
   - Support filtering and partial implementations incrementally.

3. Support log points
   - Evaluate log message templates without stopping the program.
   - Ensure formatting is safe and performant when executed inside the runtime.

4. Data breakpoints (Phase 1)
   - Bookkeeping and server-side capability reporting (`dataBreakpointInfo`, `setDataBreakpoints`).
   - Phase 1 tracks requests; later phases will add runtime watchpoints/notification.

5. Source requests & navigation helpers
   - Serve `source` content and `goto`/navigation targets where available.

## Design notes

- Keep the controller implementation small and focused; it acts as a translator between the adapter's request handlers and lower-level debugger/runtime components (debugger/launcher).
- Design to be testable: unit tests should exercise bookkeeping, format handling for log points, and behavior when requested features are missing at runtime.

## Related docs & references

- Checklist (what's implemented & planned): `CHECKLIST.md`
- Frame evaluation docs (optimization-related breakpoints behavior): `getting-started/frame-eval/index.md`
- Operational modes & diagrams: `reference/operational_modes.md` and `debug_adapter_operational_modes.md`
- Error handling: `ERROR_HANDLING_GUIDE.md`

If you want, I can extend this page with a short class-level design and link to the exact adapter/handler code paths in the repository.
