# Dapper - Debug Adapter Protocol for Python

A Debug Adapter Protocol implementation in Python.

[![CI](https://github.com/jnsquire/dapper/actions/workflows/ci.yml/badge.svg)](https://github.com/jnsquire/dapper/actions/workflows/ci.yml)
[![Tests](https://github.com/jnsquire/dapper/actions/workflows/tests.yml/badge.svg)](https://github.com/jnsquire/dapper/actions/workflows/tests.yml)
[![Docs check](https://github.com/jnsquire/dapper/actions/workflows/docs-check.yml/badge.svg)](https://github.com/jnsquire/dapper/actions/workflows/docs-check.yml)

## Features

- Implements the Debug Adapter Protocol specification
- Connects to Python's built-in debugging tools
- Supports both TCP sockets and named pipes using asyncio
- Provides core debugging functionality (breakpoints, stepping, variable inspection)

### Debugger Features Overview

For a detailed checklist of implemented and planned debugger features, see:
- **[Debugger Features Checklist](doc/reference/checklist.md)** - Complete feature matrix with implementation status

### VS Code Integration

Dapper works directly with VS Code's built-in debugger. See **[Using Dapper with VS Code](doc/getting-started/using-vscode.md)** for setup, launch configuration, attach configs, and all VS Code-specific features.

## Installation

```bash
pip install dapper
```

For development setup, see [Development Setup](doc/development/setup.md).

## Usage

For a full walkthrough, see the **[Getting Started](doc/getting-started/index.md)** section of the documentation:

- [Quick Start](doc/getting-started/quickstart.md) — first debugging session in minutes
- [Using Dapper with VS Code](doc/getting-started/using-vscode.md) — launch configs, attach, IPC, and VS Code-specific features
- [Examples](examples/README.md) — practical code examples

### Running the Test Suite 🔬

When developing locally you should execute tests via `uv` to ensure the correct environment and avoid
Python warnings about unsupported async tests. The [development testing page](doc/development/testing.md)
contains detailed instructions, but in VS Code you can also invoke the bundled tasks:

* **`Tasks → Run Test Task → Tests: run all (uv)`** – runs the entire suite with `uv run pytest`
* **`Tasks → Run Test Task → Tests: unit+integration (uv)`** – exercises just the unit and integration directories

These make it obvious from the editor how to get a clean test run without spurious warnings.


## License

MIT
