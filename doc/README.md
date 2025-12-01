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

### Debugger Features Overview

For a detailed checklist of implemented and planned debugger features, see:
- **[Debugger Features Checklist](CHECKLIST.md)** - Complete feature matrix with implementation status

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
    "frameEval": true
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
