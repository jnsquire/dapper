<!-- Full architecture document migrated -->
# Dapper Debugger Architecture — Coroutines & Threads

This document describes the architecture of the Dapper debugger with a focus on coroutine and thread management, failure modes observed during testing, and recommended improvements.

## Overview

The debugger is split into two main runtime roles:

- Debug adapter (controller): an asyncio-based debugger implementing high-level control and protocol handling (see `PyDebugger` in `dapper/adapter/debugger/py_debugger.py`, re-exported via `dapper/adapter/server.py`). This component exposes async APIs (launch, breakpoints, evaluate, shutdown) and communicates with the client via `server.send_event(...)`.

- Debuggee (target): the debugged Python program, driven by a bdb-based engine implemented in `dapper/launcher/debug_launcher.py` (`DebuggerBDB`).  The launcher is invoked via `python -m dapper.launcher` when running subprocess mode.

There are now two transport/execution modes:

1) Subprocess mode (default): The debuggee runs as a separate Python process launched by the adapter. The adapter and debuggee communicate via a local IPC channel using binary framing.

2) In-process mode (opt-in): The debuggee runs in the same process as the adapter. The debugee program remains on the main thread, while the debug adapter server runs on a background thread with its own asyncio event loop. In this mode, the adapter calls the debug engine directly via an in-process bridge for faster, simpler control flow.

Enable in-process mode by setting `inProcess: true` in the DAP `launch` request (details below). Backward-compatibility is preserved; when omitted or false, subprocess mode is used.

## Adapter ↔ Launcher IPC (subprocess mode)

The adapter and launcher communicate via a local IPC channel using binary framing. This provides lower overhead and better framing guarantees than plain text protocols. IPC is always enabled in subprocess mode; there is no fallback to stdio.

Transports supported:

- Windows named pipes (AF_PIPE): fastest on Windows; the adapter creates a Listener with a unique pipe name and passes it to the launcher (`--ipc pipe --ipc-pipe <name>`).
- Unix domain sockets (AF_UNIX): preferred on POSIX; the adapter creates a temporary socket path (e.g., in `tempfile.gettempdir()`), cleans up the filesystem entry on close, and passes it to the launcher (`--ipc unix --ipc-path <path>`).
- TCP loopback: cross-platform fallback; binds to `127.0.0.1` on an ephemeral port and passes host/port (`--ipc tcp --ipc-host 127.0.0.1 --ipc-port <port>`).

Platform defaults:

- Windows: `pipe` (named pipe) by default.
- Non-Windows: `unix` (AF_UNIX) by default when available; otherwise automatic fallback to `tcp`.

Binary framing (default) wraps each message in an 8-byte header containing message kind and payload length, enabling efficient parsing and eliminating delimiter issues.

Request wiring:

- Server builds a `DapperConfig` from the incoming DAP `launch` request and calls `PyDebugger.launch(config)`.
	IPC preferences (for example `ipcTransport` and `ipcPipeName`) are set on `config.ipc` rather than passed as individual keyword args.
- The launcher requires `--ipc` (mandatory) and connects accordingly. Binary framing is the default.

Resource management:

- The adapter owns the listener and cleans up on shutdown (closing sockets/files and unlinking `AF_UNIX` paths).
- Reader threads catch and log exceptions; `spawn_threadsafe(lambda: ...)` (factory form) ensures events are forwarded on the adapter loop without creating coroutine objects off-loop.
- All transient IPC state is managed by the `IPCManager` class (`dapper/ipc/ipc_manager.py`) which delegates transport-specific logic to `TransportFactory` and `ConnectionBase` implementations. `PyDebugger` accesses IPC through `self.ipc` (an `IPCManager` instance).

### IPCManager

`IPCManager` provides a streamlined IPC lifecycle interface built on the `ConnectionBase` abstraction:

| Member | Purpose |
|--------|---------|
| `is_enabled` | Whether an IPC channel is currently active |
| `connection` | The active `ConnectionBase` instance (TCP, pipe, or UNIX) |
| `create_listener(config)` | Create a transport listener and return launcher CLI args |
| `connect(config)` | Connect to an existing IPC endpoint |
| `start_reader(handler)` | Spawn a daemon thread that reads messages and dispatches to `handler` |
| `send_message(msg)` | Async — write a dict message through the connection |
| `cleanup()` / `acleanup()` | Close connection and reset state (sync/async variants) |

Encapsulation benefits:

- Clear lifecycle ownership (initialized in `launch`, cleaned via `ipc.cleanup()` during shutdown or error paths).
- Transport details are hidden behind `ConnectionBase`; the manager only orchestrates listener creation, reader threading, and cleanup.
- Context manager support (`with ipc_manager:`).

## Concurrency model

- The adapter uses a dedicated asyncio event loop for most logic. The loop is stored as `self.loop` on the `PyDebugger` instance.

- Blocking or CPU-bound tasks are dispatched to the event loop `ThreadPoolExecutor` via `loop.run_in_executor(...)`.

- Subprocess mode: The debuggee process is started in a worker thread that launches the external Python process. In test mode a real `threading.Thread` is used to more closely match production sequencing.

- In-process mode: The debugee remains on the main thread (your program runs normally). The debug adapter server (`DebugAdapterServer`) runs on a daemon background thread with its own event loop (see `dapper/adapter_runner.py`). Cross-thread signaling uses `loop.call_soon_threadsafe(...)` and small helpers to schedule work safely on the adapter loop.

- Output from the debuggee (stdout/stderr) is consumed by plain threads (`_read_output`) which schedule coroutine work on the adapter loop.

- `asyncio.Event` instances (e.g., `stopped_event`, `configuration_done`) are used for coroutine-side synchronization. When set from other threads, these events are set either directly (if possible) or via `loop.call_soon_threadsafe(...)`.

- Command/response tracking uses asyncio `Future` objects stored in `_pending_commands`. Tests and certain code paths can produce cross-loop futures (created on a different loop than `self.loop`), so shutdown code attempts multiple strategies to fail/resolve futures safely across loops.

## Key helpers and patterns

### Task scheduling helper: `spawn_threadsafe`

Work is typically scheduled on the adapter event loop via direct
`loop.create_task(...)` when already executing on that loop.  A single
public helper remains to make it safe to schedule work from other threads.

`spawn_threadsafe(factory)`
* Use from any thread, including I/O reader threads, subprocess wait
  threads, or tests.  If you're certain you are already on the debugger
  loop you may simply call `loop.create_task` instead.
* The argument must be a zero-argument callable returning a coroutine
  object.  The factory is invoked on the adapter loop; if it returns an
  awaitable the helper wraps it in a task and tracks it in an internal
  `_bg_tasks` set for orderly shutdown.
* **Test-friendly behaviour:** if the debugger loop is not yet running
  but another loop is active (e.g. pytest's event loop), the factory
  executes immediately on that active loop.  This lets helpers such as
  `send_event` appear synchronous in unit tests.

Design goals:
* Never create coroutine objects off their target loop thread.
* Preserve deterministic visibility for tests relying on immediate event dispatch.
* Centralize task tracking and error handling.

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

## New: In-process debugging mode (opt-in)

... (content continues)

