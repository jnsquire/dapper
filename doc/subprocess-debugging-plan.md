# Subprocess Debugging Plan for Dapper

This document captures a proposal, design decisions, and a phased implementation plan
for adding subprocess debugging to Dapper. It is informed by debugpy's subprocess
debugging approach and adapted to Dapper's current architecture by leveraging a
direct connection strategy.

## Goals

- Allow automatic detection and debugging of Python subprocesses spawned by a
  debugged program.
- Provide a reliable end-to-end experience where each child process can be
  inspected in VS Code as a separate debug session.
- Establish a highly performant architecture avoiding IPC relay bottlenecks by
  having child processes connect directly to the active VS Code extension.
- Keep the design incremental and reversible: ship a minimal, working
  prototype first, then expand features (multiprocessing, execv, pools).

## Terminology

- Debuggee process: a process being debugged (root or child).
- Extension / Adapter: the TypeScript `DapperDebugSession` + VS Code extension
  code that acts as the adapter for DAP messages.
- Launcher: Python process run with `-m dapper.launcher` (which imports the `debug_launcher` module) that
  hosts the in-process BDB debugger and connects to the extension via binary
  IPC.
- SubprocessManager: Python component that intercepts `subprocess.Popen` and
  prepares child launches.

## Current state (summary)

- Dapper runs a `debug_launcher` per debug session (one root process). The
  launcher connects to the extension over a binary IPC channel.
- `SubprocessManager` in the launcher patches `subprocess.Popen` and prepares
  child command lines by prepending `dapper.launcher` and
  `--ipc` args. It emits `dapper/childProcess` events to the extension.
- The extension (`DapperDebugSession`) and adapter factory have plumbing to
  start the root launcher and accept its IPC connection.
- There is now an end-to-end flow that accepts and creates full child debug
  sessions in the extension for rewritten Python subprocess launches.
- The extension also exposes a process tree with tracked-PID commands, but it
  does not yet support true attach-by-PID for an arbitrary already-running
  Python interpreter.

## Design decision

- Use a per-child debug session model (one VS Code debug session per child
  process) rather than multiplexing all processes through a single adapter
  instance. This leverages VS Code's multi-session UI and is simpler to
  implement in the existing codebase.
- **Direct Connection Architecture**: Instead of maintaining intermediate relay
  threads in the `SubprocessManager`, child processes connect directly to the
  extension through a shared child-session listener owned by the extension.
  This avoids per-child listener churn, keeps framing logic centralized, and
  ensures lower latency child attachment without compounding resource costs.

## Recommended end-to-end flow (high-level)

Below is the simplified message flow after adopting the *direct connection*
architecture. The adapter (the TypeScript extension) runs one root
`pythonIpcServer` listener plus one shared child-session listener per parent
debug session. It spawns a new `DapperDebugSession` each time a child socket is
correlated through the shared listener.

```mermaid
sequenceDiagram
    participant IDE
    participant Adapter as TS Extension
    participant Root as launcher (parent)
    participant Child as launcher (child)

    IDE->>Adapter: launch request
    Adapter->>Root: spawn and pass --ipc-port=ROOT_PORT
    Root-->>Adapter: connect to ROOT_PORT (root)
    Adapter-->>IDE: initialized, process event

    note right of Root: user code spawns child
    Adapter->>Root: provide --subprocess-ipc-port=CHILD_PORT
    Root->>Child: Popen modified with --ipc-port=CHILD_PORT --session-id=UUID
    Adapter->>IDE: emit dapper/childProcess {sessionId, pid, ipcPort=CHILD_PORT}
    Child-->>Adapter: connect to CHILD_PORT
    Child-->>Adapter: first frame dapper/sessionHello {sessionId}
    IDE->>Adapter: startDebugging (attach child)
    Adapter->>Child: DAP initialization/attach
    loop
        IDE<->>Child: propagate DAP messages
    end
```

1. `SubprocessManager` intercepts `Popen` for a Python child invocation.
2. It generates a unique identifier (UUID) for the new child process.
3. The child command line is rewritten to inherit the extension's shared child
   IPC port (`--ipc tcp --ipc-port <child-port>`) and is given its logical
   session identifier via `--session-id <uuid>`.
4. `SubprocessManager` emits a `dapper/childProcess` event to the extension over
   the parent's DAP stream, including the child session id, command line, and process ID.
5. The child begins execution and connects directly to the extension's shared child listener.
   As its first IPC communication, it sends an initial `dapper/sessionHello`
   payload containing its logical session id.
6. The extension dynamically accepts the connection, parses the handshake session id, correlates
   the socket to the pending `dapper/childProcess` event, and invokes
   `vscode.debug.startDebugging()` with an internal child launch configuration carrying the session marker.
7. A new `DapperDebugSession` is initialized for the child process. It locates the
   dynamically queued direct IPC socket using the session id, establishing a full DAP debug
   flow without any proxy relay.

This approach keeps the child process fully debugged via the normal DAP mechanisms
while keeping connection logic strictly unified at the VS Code extension tier.

## Implementation phases

Phase 1 — Protocol Handshake & Direct Link Routing
- Overhaul `ipc_binary.py` (or related connection bootstrapper) to prepend
  a structured `dapper/sessionHello` handshake when a child launcher connects to
  the shared child-session listener.
- Modify `patched_popen_init()` in `dapper/adapter/subprocess_manager.py` to:
  - reuse the existing shared `--subprocess-ipc-port`,
  - generate a UUID-backed logical session id and append `--session-id <uuid>`.
- Expand `pythonIpcServer` logic in `dapperDebugAdapter.ts` to accept multi-session
  socket connections, read the handshake session id, and queue sockets structurally.

Phase 2 — Extension: Handle `dapper/childProcess` Event & Session Mapping
- Propagate `dapper/childProcess` events from `SubprocessManager` injecting the
  child's identifier.
- Add event processing inside `DapperDebugSession.handleGeneralEvent()` to respond
  by calling `vscode.debug.startDebugging()` matching an internal `attach` configuration
  with the child `sessionId` marker.
- Track resulting child sessions securely for synchronized teardown.

Phase 3 — Child-Aware Adapter Creation
- Through `DapperDebugAdapterDescriptorFactory.createDebugAdapterDescriptor()`:
  - Validate the child session marker.
  - Subvert invoking a redundant process terminal; instead, extract the fully setup socket
    from the pending socket queue mapping the session id.
  - Return the respective `DebugAdapterServer` assigning the captured child connection directly.

Phase 4 — Lifecycle and Error Handling
- Guard network queues cleanly. If a `dapper/childProcess` is terminated before
  association concludes, discard pending stale session sockets to prevent resource leaks.
- Retain `SubprocessManager` `on_child_exited` bounds to dispatch cleanup validations locally.

Phase 5 — Recursive Subprocesses
- Support nested debugging (`--subprocess-auto-attach`) so child launchers cascade the extension's
  shared child IPC port securely while generating their own grandchildren logical session ids natively.
- Apply equivalent adaptations to standard multiprocessing or ProcessPool implementations.

Phase 6 — Tests, Docs, and UX
- Solidify automated test loops around shared-listener multi-socket handshake bindings.
- Expose configurations and visibility for overarching auto-attach parameters enabling recursive hooks.

Phase 7 — Attach by PID for live Python 3.14 interpreters
- Reuse the process tree / tracked-PID UX as the entry point for a true
  `processId` attach flow.
- Allocate the extension-side IPC listener before attach and invoke a local
  CPython 3.14 helper to call `sys.remote_exec(pid, script)` against the
  target interpreter.
- Have the injected bootstrap initialize Dapper inside the target process and
  reconnect over the existing IPC session path rather than inventing a second
  debugger transport.
- Treat attach-by-PID as a complementary flow to child auto-attach: child
  auto-attach handles processes Dapper launches or rewrites, while PID attach
  handles already-running compatible Python interpreters.

## Minimal first PR scope (suggested)

- Target Phase 1 (connection handshake integration) and Phase 2 (handler integration)
  structuring the core foundation enabling a single subprocess root-node demo producing
  two robust debugging sessions connecting un-multiplexed back against the single VS Code adapter tier.
- Update `doc/` with this rewritten architectural plan.

## Files likely to change

- `dapper/launcher/debug_launcher.py`: ingest the shared child port and emit the `dapper/sessionHello` mapping handshake.
- `dapper/adapter/subprocess_manager.py`: orchestrate `childProcess` events carrying explicit session ids alongside shared connection ports.
- `vscode/extension/src/debugAdapter/dapperDebugAdapter.ts`: manage the root adapter session and provision the shared child listener used by `ChildSessionManager`.

## Risks & open questions

- **Protocol Handshake Design**: Implementing the bridging handshake correctly
  within standard Dapper binary IPC boundaries ensuring clear packet demarcations.
- **Race conditions**: It's possible the child process successfully connects before
  the parent DAP event fires. By relying on the session-id handshake queueing on the extension tier,
  order sensitivity remains strictly disjointed effectively preventing data races.
- **Security Context**: Children will span directly exposing equivalent `localhost` TCP connections; security topology mirrors general debug adapter standards natively.

## Next steps

1. Continue hardening the shared-listener `dapper/sessionHello` handshake path across more runtime matrices.
2. Advance Python-side `SubprocessManager` capabilities for multiprocessing and pool entry points that do not already flow through rewritten Python subprocess launches.
3. Migrate VS Code's IPC architecture accepting multiple buffered connections correlated dynamically into VS Code APIs invoking `startDebugging`.
4. Add the Python 3.14 attach-by-PID bootstrap and extension-side `processId`
  attach handshake as the next phase after the child-session tree work.
