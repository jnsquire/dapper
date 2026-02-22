<!-- Project README: copied from repository root and adapted for doc site -->
# Dapper - Debug Adapter Protocol for Python

A Debug Adapter Protocol implementation in Python.

[![Docs check](https://github.com/jnsquire/dapper/actions/workflows/docs-check.yml/badge.svg)](https://github.com/jnsquire/dapper/actions/workflows/docs-check.yml)

## Features

- Implements the Debug Adapter Protocol specification
- Connects to Python's built-in debugging tools
- Supports both TCP sockets and named pipes using asyncio
- Provides core debugging functionality (breakpoints, stepping, variable inspection)
- **High-performance frame evaluation system** for reduced debugging overhead (60-80% faster than traditional tracing)
- **Async / concurrency debugging** — asyncio tasks exposed as pseudo-threads, async-aware stepping skips event-loop internals, live thread names
- **Rich variable presentation** — dataclasses, namedtuples, and Pydantic models (v1 & v2) expand field-by-field with `property` hints and a named-field count badge; callables and classes carry semantic kind hints

### Debugger Features Overview

For a detailed checklist of implemented and planned debugger features, see:
- **[Debugger Features Checklist](reference/checklist.md)** - Complete feature matrix with implementation status

### Async & concurrency debugging

- **[Async Debugging Reference](reference/async-debugging.md)** — asyncio task inspector, async-aware stepping, dynamic thread names

### Rich variable presentation

- **[Variable Presentation Reference](reference/variable-presentation.md)** — dataclass / namedtuple / Pydantic rendering, presentation hints, field-level expansion

### Frame Evaluation System

Dapper includes an advanced frame evaluation system that significantly improves debugging performance:

- **[Frame Evaluation User Guide](getting-started/frame-eval/index.md)** - How to enable and configure frame evaluation
- **[Frame Evaluation Performance](architecture/frame-eval/performance.md)** - Performance characteristics and benchmarks
- **[Frame Evaluation Troubleshooting](getting-started/frame-eval/troubleshooting.md)** - Common issues and solutions
- **[Frame Evaluation Implementation](architecture/frame-eval/implementation.md)** - Technical implementation details

Quick start with frame evaluation:
```json
{
    "name": "Python: Dapper with Frame Evaluation",
    "type": "python", 
    "request": "launch",
    "program": "${file}",
    "frameEval": true,
    "subprocessAutoAttach": true,
    "justMyCode": true
}
```

Module launch example:
```json
{
    "name": "Python: Dapper Module Launch",
    "type": "python",
    "request": "launch",
    "module": "my_app.main",
    "moduleSearchPaths": ["${workspaceFolder}/src"],
    "env": {
        "PYTHONPATH": "${workspaceFolder}/vendor"
    }
}
```

## Installation

```bash
pip install dapper
```

For development:

```bash
# Install uv, the Rust-based Python package installer and resolver
pip install uv

# Install dependencies and sync environment
uv sync

# Run tests
uv run pytest
```

See also: [Getting started — Development](getting-started/development.md)

## Usage and Links

- [Getting Started](getting-started/index.md)
- [Architecture](architecture/index.md)
- [Examples](examples/README.md)

---

This page is a documentation mirror of the project README to ensure internal doc links resolve during site builds. For the canonical repository README see the project root.
