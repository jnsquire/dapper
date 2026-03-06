# Custom DAP Extensions

Dapper extends the standard [Debug Adapter Protocol](https://microsoft.github.io/debug-adapter-protocol/) with custom events and requests. This page documents all non-standard messages so that clients and tools integrating with Dapper know what to expect.

All custom message types use the `dapper/` namespace prefix to avoid collisions with any future DAP standard additions.

## Custom Events

### `dapper/childProcess`

Emitted when a child process is detected and automatically attached (requires `autoAttachChildProcesses: true` in the launch configuration).

**Body fields:**

| Field | Type | Description |
|-------|------|-------------|
| `pid` | int | Process ID of the child process. |
| `parentPid` | int | Process ID of the parent that spawned it. |
| `command` | string | Command line used to start the child process. |
| `ipcEndpoint` | string | IPC endpoint address the child's adapter is listening on. |

### `dapper/processStarted`

Emitted when a debugged child process has started and the adapter has successfully connected to it.

**Body fields:**

| Field | Type | Description |
|-------|------|-------------|
| `pid` | int | Process ID of the newly started process. |
| `ipcEndpoint` | string | IPC endpoint for this process's adapter connection. |

### `dapper/processExited`

Emitted when a debugged child process has exited.

**Body fields:**

| Field | Type | Description |
|-------|------|-------------|
| `pid` | int | Process ID of the exited process. |
| `exitCode` | int | Exit code returned by the process. |

## Custom Requests

Dapper currently documents only the custom requests and events that are considered stable enough for external consumers. Additional request types may be added here as they are finalized.

## Capability Flags

Dapper advertises non-standard capabilities in the `initialize` response body alongside the standard DAP capability flags.

| Flag | Type | Description |
|------|------|-------------|
| `supportsChildProcessDebugging` | bool | `true` when the adapter can automatically attach to child processes spawned by the debugged program. Clients should show the `autoAttachChildProcesses` option in their UI when this is `true`. |

Capability flags that are experimental, internal, or still evolving are intentionally omitted from this page until their external contract is stable.

## See Also

- [Message Flows](../development/message-flows.md)
- [Architecture Overview](../architecture/overview.md)
- [Hot Reload Roadmap](../roadmap/dep-001-hot-reload.md)
