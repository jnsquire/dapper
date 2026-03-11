# Custom DAP Extensions

Dapper extends the standard [Debug Adapter Protocol](https://microsoft.github.io/debug-adapter-protocol/) with custom events and requests. This page documents all non-standard messages so that clients and tools integrating with Dapper know what to expect.

All custom message types use the `dapper/` namespace prefix to avoid collisions with any future DAP standard additions.

## Custom Events

### `dapper/childProcess`

Emitted when a Python child process is detected and rewritten for Dapper
auto-attach (requires `subprocessAutoAttach: true` in the launch configuration).

**Body fields:**

| Field | Type | Description |
|-------|------|-------------|
| `pid` | int | Process ID of the child process. |
| `parentPid` | int | Process ID of the parent that spawned it. |
| `name` | string | Best-effort child display name. |
| `command` | string[] | Original child command line arguments before launcher rewrite. |
| `cwd` | string | Child working directory when known. |
| `isPython` | bool | Whether the intercepted child command was recognized as Python. |
| `ipcPort` | int | Shared extension-side TCP port used for child IPC under the current parent debug session. |
| `sessionId` | string | Logical child session identifier used to correlate the child socket. |
| `parentSessionId` | string | Logical parent session identifier when known. |

The extension allocates one shared child IPC listener per parent debug session.
Each rewritten child process connects to that port and sends an internal
`dapper/sessionHello` handshake carrying its `sessionId`. That handshake is
transport-internal and is not forwarded as a public DAP event.

### `dapper/childProcessExited`

Emitted when a tracked child process exits.

**Body fields:**

| Field | Type | Description |
|-------|------|-------------|
| `pid` | int | Process ID of the exited child process. |
| `name` | string | Best-effort child display name. |

### `dapper/childProcessCandidate`

Emitted when Dapper detects a potential child-process source in an API path that
is not yet fully auto-attached.

**Body fields:**

| Field | Type | Description |
|-------|------|-------------|
| `source` | string | Detector source, for example `multiprocessing.Process`. |
| `name` | string | Best-effort display name for the candidate child source. |
| `target` | string | Best-effort callable or target name when known. |
| `parentPid` | int | Process ID of the parent that detected the candidate. |
| `sessionId` | string | Logical current session identifier when known. |
| `parentSessionId` | string | Logical parent session identifier when known. |
| `autoAttachImplemented` | bool | Whether full auto-attach is implemented for that source path. |

## Custom Requests

Dapper currently documents only the custom requests and events that are considered stable enough for external consumers. Additional request types may be added here as they are finalized.

## Capability Flags

Dapper advertises non-standard capabilities in the `initialize` response body alongside the standard DAP capability flags.

| Flag | Type | Description |
|------|------|-------------|
| `supportsChildProcessDebugging` | bool | `true` when the adapter can automatically attach to supported child processes spawned by the debugged program. Clients should expose the `subprocessAutoAttach` option in their UI when this is `true`. |

Capability flags that are experimental, internal, or still evolving are intentionally omitted from this page until their external contract is stable.

## See Also

- [Message Flows](../development/message-flows.md)
- [Architecture Overview](../architecture/overview.md)
- [Hot Reload Roadmap](../roadmap/dep-001-hot-reload.md)
