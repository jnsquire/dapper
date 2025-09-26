# Dapper Debugger Architecture — Coroutines & Threads

This document describes the architecture of the Dapper debugger with a focus on coroutine and thread management, failure modes observed during testing, and recommended improvements.

## Overview

The debugger is split into two main runtime roles:

- Debug adapter (controller): an asyncio-based debugger implementing high-level control and protocol handling (`dapper/debugger.py`, class `PyDebugger`). This component exposes async APIs (launch, breakpoints, evaluate, shutdown) and communicates with the client via `server.send_event(...)`.

- Debuggee (target): the debugged Python program, driven by a bdb-based engine implemented in `dapper/debug_launcher.py` (`DebuggerBDB`).

There are now two transport/execution modes:

1) Subprocess mode (default, existing): The debuggee runs as a separate Python process launched by the adapter. The adapter and debuggee communicate via a simple protocol over stdin/stdout.

2) In-process mode (opt-in): The debuggee runs in the same process as the adapter. The debugee program remains on the main thread, while the debug adapter server runs on a background thread with its own asyncio event loop. In this mode, the adapter calls the debug engine directly via an in-process bridge for faster, simpler control flow.

Enable in-process mode by setting `inProcess: true` in the DAP `launch` request (details below). Backward-compatibility is preserved; when omitted or false, subprocess mode is used.

## Adapter ↔ Launcher IPC (subprocess mode)

By default the adapter and launcher communicate over the launcher process's stdio. For lower overhead and better framing guarantees, you can enable a local IPC channel by setting `useIpc: true` in the DAP `launch` request. This affects only the adapter↔launcher hop; client↔adapter transport remains whatever the adapter server exposes (TCP or named pipe).

Transports supported:

- Windows named pipes (AF_PIPE): fastest on Windows; the adapter creates a Listener with a unique pipe name and passes it to the launcher (`--ipc pipe --ipc-pipe <name>`).
- Unix domain sockets (AF_UNIX): preferred on POSIX; the adapter creates a temporary socket path (e.g., in `tempfile.gettempdir()`), cleans up the filesystem entry on close, and passes it to the launcher (`--ipc unix --ipc-path <path>`).
- TCP loopback: cross-platform fallback; binds to `127.0.0.1` on an ephemeral port and passes host/port (`--ipc tcp --ipc-host 127.0.0.1 --ipc-port <port>`).

Platform defaults when `useIpc` is true:

- Windows: `pipe` (named pipe) by default.
- Non-Windows: `unix` (AF_UNIX) by default when available; otherwise automatic fallback to `tcp`.

Request wiring:

- Server forwards `useIpc` and optional `ipcTransport`/`ipcPipeName` to `PyDebugger.launch(...)` only when `useIpc` is truthy, preserving positional-args expectations in legacy tests.
- The launcher accepts `--ipc` options and connects accordingly. Messages tagged `DBGP:` flow adapter→launcher; `DBGCMD:` flow launcher→adapter.

Resource management:

- The adapter owns the listener and cleans up on shutdown (closing sockets/files and unlinking `AF_UNIX` paths).
- Reader threads catch and log exceptions; `spawn_threadsafe(lambda: ...)` (factory form) ensures events are forwarded on the adapter loop without creating coroutine objects off-loop.
- All transient IPC state (listener sockets, pipe handles, r/w files, unix path, binary flag) is centralized in an `IPCContext` dataclass (`dapper/ipc_context.py`). The debugger exposes legacy private attributes (e.g. `_ipc_listen_sock`) via a property bridge to avoid churn; internal code increasingly prefers `self.ipc.<field>`.

### IPCContext

`IPCContext` groups related fields that were previously individual attributes on `PyDebugger`:

| Field | Purpose |
|-------|---------|
| `enabled` | Whether an IPC channel is currently active |
| `listen_sock` | Passive listening socket (UNIX/TCP) |
| `sock` | Accepted active socket connection |
| `rfile` / `wfile` | File-like wrappers around the active socket/pipe (text or binary) |
| `pipe_listener` | Windows named pipe listener (AF_PIPE) |
| `pipe_conn` | Accepted named pipe connection |
| `unix_path` | Filesystem path for AF_UNIX socket (for cleanup) |
| `binary` | Whether binary framed IPC (`--ipc-binary`) is in use |

Encapsulation benefits:

- Clear lifecycle ownership (initialize in `launch`, cleaned in `_cleanup_ipc_resources`).
- Reduced attribute sprawl in `server.py` (improved readability & type hinting).
- Easier to evolve framing/transport logic without widening `PyDebugger`'s surface.

Backward compatibility is maintained through properties so tests referencing `_ipc_*` continue to pass. New code should prefer the `ipc` object directly.

## Concurrency model

- The adapter uses a dedicated asyncio event loop for most logic. The loop is stored as `self.loop` on the `PyDebugger` instance.

- Blocking or CPU-bound tasks are dispatched to the event loop `ThreadPoolExecutor` via `loop.run_in_executor(...)`.

- Subprocess mode: The debuggee process is started in a worker thread that launches the external Python process. In test mode a real `threading.Thread` is used to more closely match production sequencing.

- In-process mode: The debugee remains on the main thread (your program runs normally). The debug adapter server (`DebugAdapterServer`) runs on a daemon background thread with its own event loop (see `dapper/adapter_runner.py`). Cross-thread signaling uses `loop.call_soon_threadsafe(...)` and small helpers to schedule work safely on the adapter loop.

- Output from the debuggee (stdout/stderr) is consumed by plain threads (`_read_output`) which schedule coroutine work on the adapter loop.

- `asyncio.Event` instances (e.g., `stopped_event`, `configuration_done`) are used for coroutine-side synchronization. When set from other threads, these events are set either directly (if possible) or via `loop.call_soon_threadsafe(...)`.

- Command/response tracking uses asyncio `Future` objects stored in `_pending_commands`. Tests and certain code paths can produce cross-loop futures (created on a different loop than `self.loop`), so shutdown code attempts multiple strategies to fail/resolve futures safely across loops.

## Key helpers and patterns

### Task scheduling helpers: `spawn` and `spawn_threadsafe`

`spawn(factory)`
* Use when you are already running on the debugger's own event loop (`self.loop`).
* `factory` MUST be a zero-argument callable returning a coroutine object. The coroutine is created and immediately scheduled with `loop.create_task(...)`.
* Returns the created `asyncio.Task` (or `None` on failure) and tracks it in an internal `_bg_tasks` set for lifecycle/shutdown management.

`spawn_threadsafe(factory)`
* Use from any other thread (I/O reader threads, subprocess wait thread, tests) or when you are not sure you are on the debugger loop.
* Accepts the same zero-argument coroutine factory. The factory is invoked only on a loop that is already running, preventing creation of "orphan" coroutine objects on the wrong thread.
* Behavior:
   - If the debugger loop is running: schedules a small `_submit` via `loop.call_soon_threadsafe`, then invokes the factory on the debugger loop.
   - If the debugger loop is NOT running but there is a currently running (pytest-managed) loop: executes immediately on that current loop (useful for tests that assert synchronous side-effects like `send_event` calls).
   - If the loop is closed or scheduling fails, the failure is logged at debug level and otherwise ignored.

Design goals:
* Never create coroutine objects off their target loop thread.
* Preserve deterministic visibility for tests relying on immediate event dispatch.
* Centralize task tracking and error handling.

Internal helper `_schedule_factory(factory, loop)` backs both public helpers, ensuring a single code path for task creation and tracking.

### Cross-loop shutdown helpers

Shutdown must fail any outstanding futures in `_pending_commands`, including those created on other loops. Strategies (in order):

1. If future's loop == current loop => call `future.set_exception(...)` directly.
2. If future's owning loop is known => use `fut_loop.call_soon_threadsafe(fut.set_exception, ...)`.
3. Fallback: `asyncio.run_coroutine_threadsafe` with a tiny coroutine that sets the exception and wait briefly for the result.
4. Best-effort direct `fut.set_exception(...)`.
5. Final fallback: call `self.loop.call_soon_threadsafe(fut.set_exception, ...)`.

After scheduling exceptions across loops the shutdown routine polls a small grace period (250ms) to allow callbacks on other loops to run and mark futures done.

## Common failure modes and mitigations

1. `RuntimeError: no running event loop` in worker threads
   - Root cause: calling `asyncio.get_running_loop()` in threads that have no loop. This raises `RuntimeError` and can bubble out of thread functions, causing pytest to emit `PytestUnhandledThreadExceptionWarning`.
   - Mitigation: call `get_running_loop()` defensively:
     ```py
     current_loop = None
     with contextlib.suppress(RuntimeError):
         current_loop = asyncio.get_running_loop()
     ```

2. Cross-loop Future races during shutdown
   - Root cause: scheduling exception callbacks on other loops is asynchronous.
   - Mitigation: short graceful wait (already present), or use a deterministic acknowledgement Future scheduled on the target loop and waited for (more deterministic, recommended for critical paths).

3. Orphaned coroutine objects
   - Root cause: creating coroutine objects on one loop and not scheduling them properly.
   - Mitigation: use the callable form to create awaitables on the target loop thread; prefer `loop.create_task` on the correct loop.

4. Uncaught exceptions in plain threads
   - Root cause: threads that raise uncaught exceptions cause noisy test warnings.
   - Mitigation: ensure thread entrypoints catch exceptions and log them with `logger.exception(...)`.

## Recommended incremental fixes (safe)

1. Ensure thread entrypoints (`_start_debuggee_process`, `_read_output`) catch/log exceptions (they do).
2. Use factory-based scheduling (`spawn_threadsafe`) to avoid creating coroutine objects off-loop.
3. Optionally add a small configurable shutdown wait parameter and/or implement an acknowledgement Future for cross-loop shutdown (future enhancement).

## Example minimal patch

The helpers internally use a defensive `get_running_loop()` wrapped in a `try/except` to avoid `RuntimeError` in threads without a running loop.

## Testing guidance

- After the minimal changes: run the full pytest suite. The earlier `PytestUnhandledThreadExceptionWarning` should disappear.
- Add a regression test that starts the debuggee in test mode and asserts no unhandled exceptions surface in worker threads.
- Consider adding a deterministic shutdown test that uses an acknowledgement Future scheduled on the target loop (instead of naive polling) to validate cross-loop cleanup.

---

If you'd like, I can create the minimal patch and run tests now, or implement the acknowledgement-based shutdown for more determinism. Which would you prefer?

---

## New: In-process debugging mode (opt-in)

In-process mode keeps the debugged program (debugee) on the main thread and runs the debug adapter on a background thread. This can simplify integration and avoid subprocess management while keeping the DAP transport (TCP/named pipes) unchanged.

### Components

- `dapper/adapter_runner.py` — AdapterThread
   - Starts `DebugAdapterServer` on a background daemon thread with its own asyncio event loop.
   - Manages server lifecycle (start/stop) and loop scheduling.

- `dapper/inprocess_debugger.py` — InProcessDebugger
   - A small object-oriented bridge over `DebuggerBDB` that mirrors the command handlers from `debug_launcher.py` but returns plain Python dicts instead of JSON over stdio.
   - Exposes methods such as `continue_`, `next_`, `step_in`, `step_out`, `stack_trace`, `variables`, `set_variable`, `evaluate`.
   - Provides optional callbacks set by the adapter to forward events directly:
      - `on_stopped(data: dict) -> None`
      - `on_thread(data: dict) -> None`
      - `on_exited(data: dict) -> None`
      - `on_output(category: str, output: str) -> None`

- `dapper/debugger.py` — PyDebugger additions
   - `in_process` flag and an internal `_inproc` reference.
   - `_launch_in_process()` performs a lazy import of `InProcessDebugger`, sets up callbacks to forward DAP events (`stopped`, `thread`, `exited`, `output`) via `server.send_event(...)`, and signals a `process` event with the current PID.
   - `_send_command_to_debuggee(...)` maps DAP commands directly to `InProcessDebugger` methods in in-process mode; subprocess JSON/stdio path remains for the default mode.

- `dapper/server.py` — request handlers
   - Passes `inProcess` from the `launch` request to `PyDebugger.launch(...)`.
   - Execution flow handlers accept legacy expectations used by tests (`next` maps to `step_over` when available; `stepIn` passes optional `targetId`).
   - `configurationDone` awaits only awaitable results (test doubles may return non-awaitables).

### Launch & lifecycle

- Launch request (DAP):

```json
{
   "command": "launch",
   "arguments": {
      "program": "${workspaceFolder}/your_script.py",
      "args": ["--flag"],
      "stopOnEntry": false,
      "noDebug": false,
      "inProcess": true
   }
}
```

- When `inProcess: true`:
   - The adapter server starts on a background thread/loop.
   - The program continues to run on the main thread; the debugger engine operates in-process via direct calls.
   - Events are forwarded via callbacks without stdio serialization.

- When `inProcess` is omitted or false:
   - The legacy subprocess path is used; the adapter speaks to the debuggee over stdin/stdout.

### Termination & disconnect semantics

- Subprocess mode: `terminate`/`disconnect` tears down the child process and cleans up pending futures and transports.

- In-process mode: `terminate`/`disconnect` must not exit the host process. Current behavior makes these no-ops or graceful stops (e.g., clear stepping, remove breakpoints) and returns success to the client. The host application stays alive unless it chooses to exit.

### Event routing

In in-process mode, `InProcessDebugger` calls adapter-supplied callbacks. The adapter forwards these as DAP events using `_forward_event`/`server.send_event(...)`. This avoids JSON encoding and IO, lowering latency and complexity.

### Limitations and notes

- `exceptionInfo` in the in-process bridge currently returns a generic body. The subprocess path provides richer details; parity can be added if needed.
- `setVariable` performs a straightforward `eval` into the selected scope (`locals`/`globals`) and returns the updated value—mirroring launcher semantics.
- Handlers maintain test/back-compat mappings (e.g., `next` -> `step_over`) to accommodate existing clients/tests.

### Testing & compatibility

- Existing tests continue to pass in subprocess mode (default). In-process mode is opt-in and designed to be transparent to clients unless enabled.
- Server handlers tolerate both async and non-async test doubles.

---