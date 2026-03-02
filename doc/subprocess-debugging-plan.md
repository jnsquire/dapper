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
- There is not yet an end-to-end flow that accepts and creates full child
  debug sessions in the extension — child IPC ports currently have no listener
  and child sessions are not created automatically.

## Design decision

- Use a per-child debug session model (one VS Code debug session per child
  process) rather than multiplexing all processes through a single adapter
  instance. This leverages VS Code's multi-session UI and is simpler to
  implement in the existing codebase.
- **Direct Connection Architecture**: Instead of maintaining intermediate relay
  threads in the `SubprocessManager`, child processes connect directly to the
  extension's existing IPC server. This avoids the complexity of framing relays
  and ensures lower latency child attachment without compounding resource costs.

## Recommended end-to-end flow (high-level)

Below is the simplified message flow after adopting the *direct connection*
architecture.  The adapter (the TypeScript extension) plays two roles: it runs
one `pythonIpcServer` listener and it spawns a new `DapperDebugSession` each
time a new child connects.

```mermaid
sequenceDiagram
    participant IDE
    participant Adapter as TS Extension
    participant Root as launcher (parent)
    participant Child as launcher (child)

    IDE->>Adapter: launch request
    Adapter->>Root: spawn and pass --ipc-port=PORT
    Root-->>Adapter: connect to PORT (root)
    Adapter-->>IDE: initialized, process event

    note right of Root: user code spawns child
    Root->>Child: Popen modified with --ipc-port=PORT --child-id=UUID
    Child-->>Adapter: connect to PORT
    Adapter-->>Adapter: handshake {childId: UUID}
    Adapter->>IDE: emit dapper/childProcess {childId, pid}
    IDE->>Adapter: startDebugging (attach, __childId=UUID)
    Adapter->>Child: DAP initialization/attach
    loop
        IDE<->>Child: propagate DAP messages
    end
```

1. `SubprocessManager` intercepts `Popen` for a Python child invocation.
2. It generates a unique identifier (UUID) for the new child process.
3. The child command line is rewritten to inherit the extension's IPC communication
   port (`--ipc tcp --ipc-port <root-port>`) and is given its unique identifier
   via a new parameter `--child-id <uuid>`.
4. `SubprocessManager` emits a `dapper/childProcess` event to the extension over
   the parent's DAP stream, including the child's UUID, command line, and process ID.
5. The child begins execution and connects directly to the extension's `pythonIpcServer`.
   As its first IPC communication, it sends an initial handshake payload containing its UUID.
6. The extension dynamically accepts the connection, parses the handshake UUID, correlates
   the socket to the pending `dapper/childProcess` event, and invokes
   `vscode.debug.startDebugging()` with an attach configuration carrying the UUID marker.
7. A new `DapperDebugSession` is initialized for the child process. It locates the
   dynamically queued direct IPC socket using the UUID, establishing a full DAP debug
   flow without any proxy relay.

This approach keeps the child process fully debugged via the normal DAP mechanisms
while keeping connection logic strictly unified at the VS Code extension tier.

## Implementation phases

Phase 1 — Protocol Handshake & Direct Link Routing
- Overhaul `ipc_binary.py` (or related connection bootstrapper) to prepend
  a structured `ChildID` handshake when transitioning an IPC stream if `--child-id`
  is active.
- Modify `patched_popen_init()` in `dapper/adapter/subprocess_manager.py` to:
  - reuse the existing root `--ipc-port`,
  - generate a UUID and append `--child-id <uuid>`.
- Expand `pythonIpcServer` logic in `dapperDebugAdapter.ts` to accept multi-session
  socket connections, read the handshake UUID, and queue sockets structurally.

Phase 2 — Extension: Handle `dapper/childProcess` Event & Session Mapping
- Propagate `dapper/childProcess` events from `SubprocessManager` injecting the
  child's identifier.
- Add event processing inside `DapperDebugSession.handleGeneralEvent()` to respond
  by calling `vscode.debug.startDebugging()` matching an internal `attach` configuration
  with the `__childId: <uuid>` marker.
- Track resulting child sessions securely for synchronized teardown.

Phase 3 — Child-Aware Adapter Creation
- Through `DapperDebugAdapterDescriptorFactory.createDebugAdapterDescriptor()`:
  - Validate the `__childId` marker.
  - Subvert invoking a redundant process terminal; instead, extract the fully setup socket
    from the pending socket queue mapping the UUID.
  - Return the respective `DebugAdapterServer` assigning the captured child connection directly.

Phase 4 — Lifecycle and Error Handling
- Guard network queues cleanly. If a `dapper/childProcess` is terminated before
  association concludes, discard pending stale UUID sockets to prevent resource leaks.
- Retain `SubprocessManager` `on_child_exited` bounds to dispatch cleanup validations locally.

Phase 5 — Recursive Subprocesses
- Support nested debugging (`--subprocess-auto-attach`) so child launchers cascade the extension's
  IPC port securely while generating their own grandchildren process UUID configurations natively.
- Apply equivalent adaptations to standard multiprocessing or ProcessPool implementations.

Phase 6 — Tests, Docs, and UX
- Solidify automated test loops around UUID multi-socket handshake bindings.
- Expose configurations and visibility for overarching auto-attach parameters enabling recursive hooks.

## Minimal first PR scope (suggested)

- Target Phase 1 (connection handshake integration) and Phase 2 (handler integration)
  structuring the core foundation enabling a single subprocess root-node demo producing
  two robust debugging sessions connecting un-multiplexed back against the single VS Code adapter tier.
- Update `doc/` with this rewritten architectural plan.

## Files likely to change

re-DAP handshake bytes.
- `dapper/launcher/debug_launcher.py`: ingest the `--child-id` mapping constraint mapping initialization hooks.
- `dapper/adapter/subprocess_manager.py`: orchestrate `childProcess` events carrying explicit UUID links alongside shared connection ports.
- `vscode/extension/src/debugAdapter/dapperDebugAdapter.ts`: transition the singleton root `pythonIpcServer` socket processor into a multi-socket handshaking queue structure mapping direct Dapper sessions efficiently.

## Risks & open questions

- **Protocol Handshake Design**: Implementing the bridging handshake correctly
  within standard Dapper binary IPC boundaries ensuring clear packet demarcations.
- **Race conditions**: It's possible the child process successfully connects before
  the parent DAP event fires. By relying on the UUID handshake queueing on the extension tier,
  order sensitivity remains strictly disjointed effectively preventing data races.
- **Security Context**: Children will span directly exposing equivalent `localhost` TCP connections; security topology mirrors general debug adapter standards natively.

## Next steps

1. Define and implement the pre-DAP UUID connection handshake protocol.
2. Advance Python-side `SubprocessManager` capabilities configuring the explicit target routing payload.
3. Migrate VS Code's IPC architecture accepting multiple buffered connections correlated dynamically into VS Code APIs invoking `startDebugging`.
