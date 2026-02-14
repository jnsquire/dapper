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
- **[Debugger Features Checklist](doc/reference/checklist.md)** - Complete feature matrix with implementation status

### Frame Evaluation System

Dapper includes an advanced frame evaluation system that significantly improves debugging performance:

- **[Frame Evaluation User Guide](doc/getting-started/frame-eval/index.md)** - How to enable and configure frame evaluation
- **[Frame Evaluation Performance](doc/architecture/frame-eval/performance.md)** - Performance characteristics and benchmarks
- **[Frame Evaluation Troubleshooting](doc/getting-started/frame-eval/troubleshooting.md)** - Common issues and solutions
- **[Frame Evaluation Implementation](doc/architecture/frame-eval/implementation.md)** - Technical implementation details

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

### VS Code Extension

The repository includes a VS Code extension in `vscode/extension`. This is a complete npm project that requires separate setup:

```bash
cd vscode/extension
npm install
npm run build
```

See [DEVELOPMENT.md](doc/DEVELOPMENT.md#vs-code-extension-development) for full details.

> **Note:** For detailed development setup instructions including uv usage, testing, and troubleshooting, see [DEVELOPMENT.md](doc/DEVELOPMENT.md).

## Usage

### Command Line

```bash
python -m dapper.adapter --port 4711
```

Or using named pipes:

```bash
python -m dapper.adapter --pipe debug_pipe
```

### In-Process Mode (Adapter-in-Thread)

Besides the default subprocess model, Dapper supports an opt-in in-process mode where your program stays on the main thread and the debug adapter runs on a background thread. The DAP transport (TCP/named pipe) remains unchanged, but the adapter uses an in-process bridge for faster, simpler control flow.

Enable it in your DAP launch request with `"inProcess": true`:

```json
{
    "name": "Python: Dapper AI (In-Process)",
    "type": "python",
    "request": "launch",
    "program": "${file}",
    "debugServer": 4711,
    "inProcess": true
}
```

See [Architecture: In-Process Mode](doc/architecture/overview.md#new-in-process-debugging-mode-opt-in) for lifecycle and termination semantics.

### Subprocess IPC (adapter ↔ launcher)

When launching the debuggee as a subprocess, the adapter and the in-process launcher can communicate over stdio (default) or an opt-in local IPC channel. Enable IPC by setting `useIpc: true` in the DAP `launch` request. This affects only the adapter↔launcher hop; how your DAP client connects to the adapter (TCP/pipe) is unchanged.

Platform defaults when `useIpc` is true:

- Windows: named pipes (`pipe`) via native AF_PIPE.
- Non-Windows: Unix domain sockets (`unix`) when available; otherwise falls back to TCP loopback.

You can override the transport explicitly with `ipcTransport`:

- `"pipe"` (Windows): optionally provide a pipe name via `ipcPipeName` (e.g., `\\.\pipe\dapper-demo`). If omitted, a unique name is generated.
- `"unix"` (POSIX): uses a temporary socket path managed by the adapter; no extra fields required.
- `"tcp"`: binds to `127.0.0.1` on an ephemeral port.

Examples:

```json
{
    "command": "launch",
    "arguments": {
        "program": "${workspaceFolder}/app.py",
        "useIpc": true
    }
}
```

Force a specific transport (Windows named pipe):

```json
{
    "command": "launch",
    "arguments": {
        "program": "${workspaceFolder}/app.py",
        "useIpc": true,
        "ipcTransport": "pipe",
        "ipcPipeName": "\\\\.\\pipe\\dapper-demo"
    }
}
```

Force TCP loopback on any platform:

```json
{
    "command": "launch",
    "arguments": {
        "program": "${workspaceFolder}/app.py",
        "useIpc": true,
        "ipcTransport": "tcp"
    }
}
```

### Attach to a running debuggee (IPC)

Dapper supports attaching to an already-running Python program that was started with a compatible launcher and is exposing an IPC endpoint. Use a DAP "attach" request and specify the IPC transport details:

- Common fields:
    - `useIpc: true`
    - `ipcTransport`: one of `"tcp" | "unix" | "pipe"`
- TCP: provide `ipcHost` and `ipcPort`
- Unix domain socket: provide `ipcPath`
- Windows named pipe: provide `ipcPipeName`

Example DAP attach request (TCP):

```json
{
    "command": "attach",
    "arguments": {
        "useIpc": true,
        "ipcTransport": "tcp",
        "ipcHost": "127.0.0.1",
        "ipcPort": 5000
    }
}
```

VS Code attach configuration examples:

```jsonc
// Attach via TCP to a running debuggee
{
    "name": "Dapper: Attach (tcp)",
    "type": "python",
    "request": "attach",
    "debugServer": 4711,
    "useIpc": true,
    "ipcTransport": "tcp",
    "ipcHost": "127.0.0.1",
    "ipcPort": 5000
}

// Attach via Unix domain socket (POSIX)
{
    "name": "Dapper: Attach (unix)",
    "type": "python",
    "request": "attach",
    "debugServer": 4711,
    "useIpc": true,
    "ipcTransport": "unix",
    "ipcPath": "/tmp/dapper.sock"
}

// Attach via Windows named pipe
{
    "name": "Dapper: Attach (pipe)",
    "type": "python",
    "request": "attach",
    "debugServer": 4711,
    "useIpc": true,
    "ipcTransport": "pipe",
    "ipcPipeName": "\\\\.\\pipe\\dapper-demo"
}
```

### Configuration in VS Code

Add this to your launch.json (for a step-by-step walkthrough, see [Debug Python in VS Code with Dapper](doc/getting-started/using-vscode.md)):

```json
{
    "name": "Python: Dapper AI",
    "type": "python",
    "request": "launch",
    "program": "${file}",
    "debugServer": 4711
}
```

IPC variants you can copy/paste:

```jsonc
// Default (let platform choose: Windows=pipe, non-Windows=unix)
{
    "name": "Dapper (IPC default)",
    "type": "python",
    "request": "launch",
    "program": "${file}",
    "debugServer": 4711,
    "useIpc": true
}

// Windows: named pipe with explicit name
{
    "name": "Dapper (IPC pipe)",
    "type": "python",
    "request": "launch",
    "program": "${file}",
    "debugServer": 4711,
    "useIpc": true,
    "ipcTransport": "pipe",
    "ipcPipeName": "\\\\.\\pipe\\dapper-demo"
}

// Force TCP on any platform
{
    "name": "Dapper (IPC tcp)",
    "type": "python",
    "request": "launch",
    "program": "${file}",
    "debugServer": 4711,
    "useIpc": true,
    "ipcTransport": "tcp"
}

// POSIX: force UNIX domain socket
{
    "name": "Dapper (IPC unix)",
    "type": "python",
    "request": "launch",
    "program": "${file}",
    "debugServer": 4711,
    "useIpc": true,
    "ipcTransport": "unix"
}
```

## Examples

The `examples/` directory contains practical examples of using Dapper AI:

### Integrated Debugging

Learn how to integrate the debugger directly into your Python applications:

```bash
# Run the integrated debugging example
python examples/integrated_debugging.py

# Run without debugging for comparison
python examples/integrated_debugging.py --no-debug
```

This example shows:
- Setting breakpoints programmatically
- Handling debug events
- Inspecting variables during execution
- Custom debugging workflows

### In-Process DAP Launch Example

Launch your code with the adapter running in a background thread:

```json
{
    "command": "launch",
    "arguments": {
        "program": "${workspaceFolder}/your_script.py",
        "args": ["--flag"],
        "stopOnEntry": false,
        "noDebug": false,
        "inProcess": true
    }
}
```

The default remains subprocess mode (omit `inProcess` or set `false`).

See `examples/README.md` for detailed documentation.

Quick start examples:
- Integrated debugging: `examples/integrated_debugging.py`
- Adapter-in-thread (in-process): `examples/adapter_in_thread.py`
- Simple command provider: `examples/simple_command_provider.py`

## Running Tests

To run all tests:

```bash
uv run pytest
```

To run tests with coverage reporting:

```bash
# Quick coverage report in terminal
uv run pytest --cov=dapper --cov-report=term-missing

# Generate detailed HTML coverage report
uv run pytest --cov=dapper --cov-report=html

# Use the coverage runner script (opens HTML report in browser)
uv run python run_coverage.py
```

To run specific tests:

```bash
uv run pytest tests/test_protocol.py
uv run pytest tests/test_request_handlers.py
```

### Coverage Reports

After running tests with coverage, you can find:

- **Terminal Report**: Shows coverage percentage and missing lines in the console
- **HTML Report**: Detailed interactive report at `htmlcov/index.html`
- **XML Report**: Machine-readable report at `coverage.xml` (useful for CI/CD)

Current coverage status: **51%** overall
- `server.py`: 82% ✅
- `connection.py`: 55%
- `debugger.py`: 38%
- `protocol.py`: 33%

## Development

### Setting Up Development Environment

1. Clone the repository:

```bash
git clone https://github.com/yourusername/dapper.git
cd dapper
```

2. Create and activate a virtual environment:

```bash
# Create a virtual environment
python -m venv venv

# Activate the virtual environment
# On Windows
venv\Scripts\activate
# On macOS/Linux
source venv/bin/activate
```

3. Install the package in development mode:

```bash
pip install -e ".[dev]"
```

This project uses pytest and pytest-asyncio for testing. The tests are in the `tests/` directory.

### Deactivating the Environment

When you're done working on the project, you can deactivate the virtual environment:

```bash
deactivate
```

## License

MIT
 
## Message flow diagrams

Visual diagrams for common Debug Adapter Protocol flows are available in the documentation:

- `doc/reference/message_flows.md` — editable Mermaid sequence diagrams showing Launch, Attach, and Breakpoint flows.

These are provided as inline Mermaid code blocks so they remain easy to edit. If your renderer doesn't support Mermaid, consider pre-rendering the diagrams to SVG with `mmdc` and committing the images alongside the markdown.
