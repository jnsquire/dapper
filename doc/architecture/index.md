<!-- Architecture landing page -->
# Architecture

This section documents the system architecture, design analyses and lifecycle management guidance for the Dapper debugger.

Core architecture pages

- [Overview and architecture details](./overview.md) — high-level architecture, transport and concurrency model, important patterns and design rationale.
- [Lifecycle management and process guidance](./lifecycle-management.md) — describes standardized lifecycle/state management for backends and recommended operational practices.

- **Frame Evaluation (architecture)** — implementation & performance details for frame evaluation:
	- [Implementation & design notes](./frame-eval/implementation.md)
	- [Performance & benchmarks](./frame-eval/performance.md)
	- [Build & developer guide](./frame-eval/build-guide.md)

- Breakpoints & controller — design and responsibilities for breakpoint handling and bookkeeping:
  - [Breakpoints Controller](./breakpoints_controller.md)

- **Protocol & Message Flows** — DAP protocol flows and message sequences:
  - [DAP Message Flow Diagrams](./message_flows.md) — sequence diagrams for launch, attach, breakpoints, and session lifecycle flows.
