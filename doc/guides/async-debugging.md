# Async / Concurrency Debugging

Dapper provides first-class support for debugging `asyncio`-based Python programs.
Two features work together to make async code feel as natural to debug as
synchronous code: **async-aware stepping** and the **asyncio task inspector**.

---

## Async-aware stepping

When you step over (`F10`) a line that contains an `await` expression, Dapper
suspends at the next point where *your* code resumes — not inside the event loop
internals (`_run_once`, `_step`, `select`, etc.).

Without this, a naive step-over would dive into the asyncio machinery and require
many additional steps before landing back in user code. Dapper detects event-loop
frames via `_is_event_loop_frame` and filters them automatically, so the step
behaviour matches your mental model of the program.

### What this covers

| Scenario | Behaviour |
|---|---|
| `await some_coroutine()` | Lands at the first line of `some_coroutine` on step-in; skips the await machinery on step-over |
| `await asyncio.sleep(...)` | Step-over resumes after the sleep, not inside `asyncio` |
| `async for` / `async with` | Both protocol methods (`__aiter__`, `__aenter__`, `__aexit__`) are skipped transparently |
| `concurrent.futures` frames | Also filtered — `ThreadPoolExecutor`, `ProcessPoolExecutor` internals are hidden |

### Step-in behaviour

`Step In` (`F11`) *does* enter a coroutine body. Only the event-loop bookkeeping
around the suspension point is skipped.

---

## Asyncio task inspector

Every live `asyncio.Task` is exposed as a **pseudo-thread** in the Threads view.
This means:

- The **Threads** panel lists each task alongside real OS threads, with its
  coroutine name shown as the thread name (e.g. `Task: main_loop`).
- Selecting a task thread shows its **call stack** in the Call Stack panel —
  the coroutine chain from the innermost `await` back to `asyncio.create_task`.
- You can inspect locals, evaluate expressions, and navigate frames for any
  suspended task, not just the one that hit the current breakpoint.

The task registry is re-enumerated on every `threads` request, so newly created
or completed tasks appear and disappear in real time without restarting the
debug session.

### Identifying task threads

Task pseudo-thread names follow the pattern:

```
Task: <coroutine_name> (<task_name_or_id>)
```

For example:

```
Task: fetch_data (Task-3)
Task: process_queue (my-worker)
```

The `<task_name_or_id>` comes from `asyncio.Task.get_name()`, which you can set
with `asyncio.create_task(..., name="my-worker")` to make tasks easy to identify.

### Tips

- **Name your tasks** with `asyncio.create_task(coro(), name="worker")` — the
  name appears directly in the threads list and makes it much easier to find the
  right task when many are running.
- **Set breakpoints in coroutines** exactly as you would for synchronous
  functions; when a task hits the breakpoint its pseudo-thread is selected
  automatically.
- If a task is **pending** (has not yet been scheduled to run), it will appear
  in the list but its stack may show only the outermost frame.

---

## Dynamic thread names

For programs that use `threading.Thread`, Dapper reads the live name from
`threading.enumerate()` at query time. This means names set via
`thread.name = "worker-3"` are reflected immediately in the Threads panel — no
restart required.

---

## Related

- [Frame Evaluation](frame-eval.md) — high-performance
  tracing that is also async-aware.
- [Debugger Features Checklist](../reference/checklist.md) — full implementation status matrix.
