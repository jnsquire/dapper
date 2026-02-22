<!-- Architecture landing page -->
# Architecture

This section documents the system architecture, design analyses and lifecycle management guidance for the Dapper debugger.

Core architecture pages

- [Overview and architecture details](./overview.md) — high-level architecture, transport and concurrency model, important patterns and design rationale.
- [Lifecycle management and process guidance](./backends.md) — describes standardized lifecycle/state management for backends and recommended operational practices.

- **Frame Evaluation (architecture)** — build guide for the frame eval extension:
	- [Build & developer guide](./frame-eval/build-guide.md)

- Breakpoints & controller — design and responsibilities for breakpoint handling and bookkeeping:
  - [Breakpoints Controller](./breakpoints.md)

- **Standardized Patterns** — guidelines for error handling and system evolution:
  - [Error Handling Guide](./error-handling.md)
  - [IPC Design Guide](./ipc.md)

- **Protocol & Message Flows** — DAP protocol flows and message sequences:
  - [DAP Message Flow Diagrams](../reference/message-flows.md) — sequence diagrams for launch, attach, breakpoints, and session lifecycle flows.
