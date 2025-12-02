<!-- Architecture landing page -->
# Architecture

This section documents the system architecture, design analyses and lifecycle management guidance for the Dapper debugger.

Core architecture pages

- [Overview and architecture details](./overview.md) — high-level architecture, transport and concurrency model, important patterns and design rationale.
- [Current architecture analysis](./current-analysis.md) — an analysis of the current debugger architecture, tracing flow and integration points (good background for changes like frame-evaluation).
- [Lifecycle management and process guidance](./lifecycle-management.md) — describes standardized lifecycle/state management for backends and recommended operational practices.

- **Frame Evaluation (architecture)** — implementation & performance details for frame evaluation:
	- [Implementation & design notes](./frame-eval/implementation.md)
	- [Performance & benchmarks](./frame-eval/performance.md)
	- [Build & developer guide](./frame-eval/build-guide.md)

- Breakpoints & controller — design and responsibilities for breakpoint handling and bookkeeping:
  - [Breakpoints Controller](./breakpoints_controller.md)
