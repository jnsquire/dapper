# Concurrency Model

Dapper's adapter uses a single asyncio event loop with a small set of thread-safe helpers for cross-thread task scheduling. Understanding this model is important when adding new I/O paths, writing tests, or working with the IPC layer.

## Event Loop Architecture

`PyDebugger` (in `dapper/server.py`) owns the asyncio event loop for the lifetime of a debugging session. The following components run *outside* the loop on dedicated threads:

- **stdin reader thread** — reads raw DAP messages from the client and dispatches them onto the loop.
- **stdout writer thread** — serialises outgoing DAP messages and writes them to stdout.
- **process wait threads** — wait for debugged sub-processes to exit and signal the loop when they do.

All mutable debugger state (breakpoints, thread registry, session state) is accessed exclusively from the event loop. Cross-thread state mutations must be scheduled via `spawn_threadsafe` (see below) rather than accessed directly, which would introduce data races.

```
┌─────────────────────────────────────────────┐
│            asyncio event loop               │
│  PyDebugger state, DAP handlers, IPC tasks  │
└────────────────┬────────────────────────────┘
                 │ spawn_threadsafe / call_soon_threadsafe
     ┌───────────┴───────────┐
     │                       │
 stdin reader            process wait
   thread(s)               threads
```

## spawn and spawn_threadsafe

These are the canonical helper methods documented on `PyDebugger`. Also see [Development — Documentation](../development/docs.md) for additional context.

### `spawn(factory)`

- Call **only** when you know you are already running on the debugger's loop (`debugger.loop`).
- `factory` is a zero-argument callable returning a coroutine object.
- Returns the created `asyncio.Task` (tracked internally in `_bg_tasks`) or `None` if creation fails.
- Using this from a different thread is a bug — use `spawn_threadsafe` instead.

### `spawn_threadsafe(factory)`

- Safe to call from any thread, including threads with no running event loop.
- Schedules the factory for execution on the debugger loop **without** creating the coroutine object off-loop (avoids attaching the coroutine to the wrong loop).
- **Test-friendly behaviour**: if the debugger loop is not yet running but another loop is active (e.g. pytest's event loop), the factory executes immediately on that active loop. This ensures that mocks observing `send_event` see results synchronously in tests without requiring the debugger loop to be fully started.

**Minimal usage example:**

```python
# From a thread reading child process output:
def _read_stdout(self, data: bytes) -> None:
    self._debugger.spawn_threadsafe(lambda: self._handle_output(data))
```

## Thread Safety Guidelines

- **Always use `spawn_threadsafe` from threads.** Never call `asyncio` primitives like `loop.call_soon` directly — let `spawn_threadsafe` centralise task tracking and error handling.
- **Prefer factory lambdas.** Pass `lambda: some_coro(arg)` rather than a pre-created coroutine object. Creating coroutines off the loop thread can attach them to the wrong running loop.
- **Do not use `asyncio.run_coroutine_threadsafe` directly** unless you specifically need the returned `Future` for synchronisation (e.g. blocking until a result is ready). Otherwise, `spawn_threadsafe` is simpler and integrates with the internal task registry.
- **Discard tasks when done.** If you cancel or await a task manually, also discard it from `_bg_tasks` to prevent unbounded memory growth.
- **IPC is managed by `IPCManager`.** The `IPCManager` (`dapper/ipc/ipc_manager.py`) handles all inter-process communication. It delegates transport details to `ConnectionBase` implementations via `TransportFactory`. Do not create raw sockets or pipes without going through this layer.

## See Also

- [Architecture Overview](overview.md)
- [Backends](backends.md)
- [IPC](ipc.md)
