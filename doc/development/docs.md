# Documentation

This page explains how to build and update the project documentation locally. It also documents the `spawn`/`spawn_threadsafe` async helper API used throughout the codebase.

## Building the Docs (MkDocs + Mermaid)

We provide a small helper (`scripts/update_docs.py`) that renders Mermaid `.mmd` diagrams and builds the MkDocs site locally.

**Recommended command** — ensures the project and development dependencies are available:

```bash
# Install dev dependencies for the run and make the project editable so the
# `docs` console-script entry point is available, then run the docs helper:
uv run --only-dev --with-editable . docs
```

If you only want to run the helper directly (without asking uv to install dev dependencies for the run), invoke the script directly. This requires that `mkdocs` and the Mermaid plugin are already available in the active environment:

```bash
uv run python scripts/update_docs.py
```

Force a full re-render of Mermaid diagrams by appending the `--force` flag:

```bash
uv run --only-dev --with-editable . docs -- --force
```

The helper writes the built site to `./site/` and skips re-rendering diagrams when the generated SVGs are already up-to-date (unless `--force` is provided).

## Asynchronous Task Scheduling Helpers

!!! note
    This section is also the canonical API reference for `spawn` and `spawn_threadsafe`. The architecture-level discussion (event loop ownership, thread safety) lives in [Concurrency Model](../architecture/concurrency.md).

The debugger codebase avoids creating coroutine objects off the target event-loop thread. Two helper APIs exist in `PyDebugger` (see `dapper/server.py`) to keep this consistent:

### `spawn(factory)`

- Call **only** when you know you are already running on the debugger's loop (`debugger.loop`).
- `factory` is a zero-argument callable returning a coroutine object.
- Returns the created `asyncio.Task` (tracked internally) or `None` if creation fails.

### `spawn_threadsafe(factory)`

- Use everywhere else: threads reading stdout/stderr, process-wait threads, tests, or any uncertain execution context.
- Schedules the factory for execution on the debugger loop **without** first creating the coroutine off-loop.
- **Test-friendly behaviour**: if the debugger loop is not yet running but another loop is active (e.g. pytest's loop), it executes immediately on that active loop so mocks observing `send_event` see results synchronously.

### Guidelines

- Prefer passing a factory (`lambda: some_coro(arg)`) instead of a pre-created coroutine object.
- Do not use `asyncio.run_coroutine_threadsafe` directly unless you require the returned `Future` for synchronisation; otherwise defer to `spawn_threadsafe` to centralise task tracking and error handling.
- If you remove tasks manually, also discard them from the `_bg_tasks` set to prevent memory growth.
- IPC management is handled by `IPCManager` (`dapper/ipc/ipc_manager.py`), which delegates transport details to `ConnectionBase` implementations via `TransportFactory`.

## See Also

- [Architecture Overview](../architecture/overview.md)
