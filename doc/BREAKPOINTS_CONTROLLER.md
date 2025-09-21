# BreakpointController API (Proposed)

This document proposes a small, thread-safe API to programmatically set all breakpoint types while the debug adapter is running in its background thread.

Status: Proposed design (not yet implemented)

## Goals

- Provide a clean API to set all supported breakpoint types:
  - Source/line breakpoints
  - Function breakpoints
  - Exception breakpoints
  - Data breakpoints (Phase 1: bookkeeping, consistent with current implementation)
- Safe to call from the main thread while the adapter runs its own asyncio loop in a background thread.
- Return useful results (verified, messages, etc.) consistent with the existing server/debugger contracts.
- Preserve DAP semantics: “set” fully replaces the prior set for that category (e.g., by source for line breakpoints).

## High-level overview

We introduce a controller object, exposed from the running adapter thread as `adapter.breakpoints`, which offers both synchronous (Future-returning) and asynchronous methods.

- Synchronous methods return `concurrent.futures.Future` so callers on the main thread can `future.result(timeout=...)` safely.
- Async counterparts are awaitable and intended for tests or advanced use where the caller already has an async context.

The controller internally schedules work onto the adapter’s asyncio loop and delegates to existing methods on `PyDebugger`.

```
 Main thread                         Adapter thread (asyncio loop)
 ─────────────────────────────────────────────────────────────────
 adapter.breakpoints.set_source() →  schedule → PyDebugger.set_breakpoints()
 adapter.breakpoints.set_function() → schedule → PyDebugger.set_function_breakpoints()
 adapter.breakpoints.set_exception() → schedule → PyDebugger.set_exception_breakpoints()
 adapter.breakpoints.data_info() →    schedule → PyDebugger.data_breakpoint_info()
 adapter.breakpoints.set_data() →     schedule → PyDebugger.set_data_breakpoints()
```

## Public API surface

Controller: `BreakpointController`

- Construction: created by `AdapterThread` once the server/debugger are ready.
  - Holds references to:
    - `loop: asyncio.AbstractEventLoop` (the adapter loop)
    - `debugger: PyDebugger`
  - Provides a private helper `_schedule(coro) -> concurrent.futures.Future` to run work on the adapter loop.

### Input specs (lightweight types)

- `LineBreakpointSpec`
  - `line: int`
  - `condition: str | None = None`
  - `hit_condition: str | None = None`
  - `log_message: str | None = None`

- `FunctionBreakpointSpec`
  - `name: str`
  - `condition: str | None = None`
  - `hit_condition: str | None = None`

- `DataBreakpointSpec`
  - `data_id: str`
  - `access_type: str = "write"` (Phase 1 only supports write tracking)
  - `condition: str | None = None`
  - `hit_condition: str | None = None`

### Synchronous methods (return concurrent futures)

- `set_source(path: str | Path, breakpoints: list[LineBreakpointSpec]) -> Future[list[dict[str, Any]]]`
- `set_function(breakpoints: list[FunctionBreakpointSpec]) -> Future[list[dict[str, Any]]]`
- `set_exception(filters: list[str]) -> Future[list[dict[str, Any]]]`
- `data_info(name: str, frame_id: int) -> Future[dict[str, Any]]`
- `set_data(breakpoints: list[DataBreakpointSpec]) -> Future[list[dict[str, Any]]]`

### Asynchronous methods (awaitable counterparts)

- `async_set_source(path: str | Path, breakpoints: list[LineBreakpointSpec]) -> list[dict[str, Any]]`
- `async_set_function(breakpoints: list[FunctionBreakpointSpec]) -> list[dict[str, Any]]`
- `async_set_exception(filters: list[str]) -> list[dict[str, Any]]`
- `async_data_info(name: str, frame_id: int) -> dict[str, Any]`
- `async_set_data(breakpoints: list[DataBreakpointSpec]) -> list[dict[str, Any]]`

Returned lists/dicts mirror the shapes produced by `PyDebugger` methods and/or DAP response bodies (e.g., each breakpoint entry has `verified`, optional `message`, and optionally `line`).

## Threading and scheduling

- All calls ultimately execute on the adapter thread’s asyncio loop.
- Synchronous methods use `asyncio.run_coroutine_threadsafe` under the hood and return the resulting `concurrent.futures.Future`.
- Asynchronous methods directly `await` the underlying debugger methods (scheduled on the adapter loop).

## Eventing

- The server already forwards adapter-level `breakpoint` events around `setBreakpoints`. Consumers can subscribe to existing event streams.
- Optionally, the controller may expose a convenience `on_breakpoint` event that proxies server events for ergonomic use (non-essential for v1).

## Error handling and lifecycle

- If the adapter/thread is not running or the debugger is not available, methods should return Futures that raise a clear `RuntimeError("adapter not running")`.
- DAP semantics remain intact: calling `set_*` before launch is allowed; the adapter stores state and applies it to the debuggee when available.
- Shutdown behavior: if the adapter is terminated, outstanding Futures complete ASAP with an error (e.g., `CancelledError` or a domain-specific `RuntimeError`).

## Usage examples

### Synchronous (main thread)

```python
# Assume adapter is started and running in background
port = adapter.get_port_future().result(timeout=5)

# Line breakpoints
results = adapter.breakpoints.set_source(
    "app.py",
    [
        LineBreakpointSpec(line=42, condition="x > 0"),
        LineBreakpointSpec(line=108, log_message="hit {i}"),
    ],
).result(timeout=5)

# Function breakpoints
fb_results = adapter.breakpoints.set_function(
    [FunctionBreakpointSpec(name="module.func")] 
).result(timeout=5)

# Exception filters
ex_results = adapter.breakpoints.set_exception(["raised", "uncaught"]).result(timeout=5)

# Data breakpoints
info = adapter.breakpoints.data_info(name="counter", frame_id=current_frame_id).result(timeout=5)
db_results = adapter.breakpoints.set_data(
    [DataBreakpointSpec(data_id=info["dataId"], access_type="write")]
).result(timeout=5)
```

### Asynchronous (tests or advanced use)

```python
results = await adapter.breakpoints.async_set_source(path, specs)
ex_results = await adapter.breakpoints.async_set_exception(["raised"]) 
```

## Integration points

- `AdapterThread`
  - Create and expose `self.breakpoints` after the server/debugger are initialized.
  - Provide accessors to the adapter loop and debugger instance.

- `PyDebugger`
  - Reuse existing methods:
    - `set_breakpoints(source, breakpoints)` (line BPs)
    - `set_function_breakpoints(breakpoints)`
    - `set_exception_breakpoints(filters)`
    - `data_breakpoint_info(name, frame_id)`
    - `set_data_breakpoints(breakpoints)`

## Edge cases

- Calling API before adapter starts: raise clear error via the returned Future.
- Clearing breakpoints:
  - Per file: call `set_source(path, [])` to clear for that file.
  - Function/Exception/Data: pass empty lists to clear.
- Concurrency: multiple calls coalesce via underlying debugger semantics (last write wins for a given category/source).

## Testing approach

- Unit tests for controller scheduling: ensure methods schedule onto adapter loop and resolve Futures.
- Contract tests on return shapes: lists/dicts contain `verified`, `line` where applicable.
- Lifecycle: ensure calls before/after adapter shutdown behave predictably.
- Data breakpoints: `data_info` yields a `dataId`, `set_data` accepts it.

## Future enhancements

- Optional internal caching to support `add_source_breakpoint` without fetching the current set.
- `clear_all()` convenience to remove everything.
- Stronger typed returns (TypedDicts/dataclasses) and adapter-level type definitions for responses.

## Implementation checklist (next steps)

- [ ] Add `BreakpointController` class under `dapper/` (or `dapper/adapter_*`).
- [ ] Wire `AdapterThread` to construct and expose `adapter.breakpoints`.
- [ ] Implement sync/async methods and scheduling helper.
- [ ] Add example usage to `examples/adapter_in_thread.py`.
- [ ] Add unit tests for controller behavior and happy-path results.
