# Dapper: Python Debug Adapter Protocol Implementation

Dapper is a Python implementation of the Debug Adapter Protocol (DAP), with support for core debugging workflows, VS Code integration, and lower-overhead runtime instrumentation.

[![CI](https://github.com/jnsquire/dapper/actions/workflows/ci.yml/badge.svg)](https://github.com/jnsquire/dapper/actions/workflows/ci.yml)
[![Tests](https://github.com/jnsquire/dapper/actions/workflows/tests.yml/badge.svg)](https://github.com/jnsquire/dapper/actions/workflows/tests.yml)
[![Docs check](https://github.com/jnsquire/dapper/actions/workflows/docs-check.yml/badge.svg)](https://github.com/jnsquire/dapper/actions/workflows/docs-check.yml)

[![Docs published](https://github.com/jnsquire/dapper/actions/workflows/docs-deploy.yml/badge.svg)](https://github.com/jnsquire/dapper/actions/workflows/docs-deploy.yml)

The full documentation is available at https://jnsquire.github.io/dapper/.


## Highlights

- Implements the Debug Adapter Protocol for Python debugging clients
- Integrates with Python runtime debugging facilities and DAP-compatible tooling
- Supports TCP sockets and IPC transports for adapter-launcher communication
- Provides breakpoints, stepping, stack inspection, and variable evaluation

### Debugger Features Overview

For a detailed checklist of implemented and planned debugger features, see:
- **[Debugger Features Checklist](doc/reference/checklist.md)** - Complete feature matrix with implementation status

### VS Code Integration

Dapper works directly with VS Code's built-in debugger. See **[Using Dapper with VS Code](doc/getting-started/using-vscode.md)** for setup, launch configuration, attach configs, and all VS Code-specific features.

For the public LM tool surface used by agents and tool-driven workflows, see
**[LM Tools Reference](doc/reference/lm-tools.md)**.

## Installation

Dapper is currently installed from source for development and evaluation:

```bash
git clone https://github.com/jnsquire/dapper.git
cd dapper
uv sync --extra dev
```

The development toolchain is declared in `pyproject.toml` and includes Ty,
Ruff, Pyright, and pytest in the `dev` dependency set.

For development setup, see [Development Setup](doc/development/setup.md).

## Usage

For a full walkthrough, see the **[Getting Started](doc/getting-started/index.md)** section of the documentation:

- [Quick Start](doc/getting-started/quickstart.md) — first debugging session in minutes
- [Using Dapper with VS Code](doc/getting-started/using-vscode.md) — launch configs, attach, IPC, and VS Code-specific features
- [Examples](examples/README.md) — practical code examples

### Running the Test Suite

When developing locally, run tests through `uv` to ensure the expected environment is used and to avoid spurious async-test warnings. The [development testing page](doc/development/testing.md) contains the full workflow, and VS Code also exposes the bundled tasks:

* **`Tasks → Run Test Task → Tests: run all (uv)`** - runs the full suite with `uv run pytest`
* **`Tasks → Run Test Task → Tests: unit+integration (uv)`** - runs the unit and integration suites only

These tasks provide a consistent way to run the test suite directly from the editor.


## License

MIT
