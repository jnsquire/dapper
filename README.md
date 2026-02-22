# Dapper - Debug Adapter Protocol for Python

A Debug Adapter Protocol implementation in Python.

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

For VS Code launch and attach configuration examples, see [Using Dapper with VS Code](doc/getting-started/using-vscode.md).

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

## License

MIT
 
## Message flow diagrams

Visual diagrams for common Debug Adapter Protocol flows are available in the documentation:

- `doc/reference/message-flows.md` — editable Mermaid sequence diagrams showing Launch, Attach, and Breakpoint flows.

These are provided as inline Mermaid code blocks so they remain easy to edit. If your renderer doesn't support Mermaid, consider pre-rendering the diagrams to SVG with `mmdc` and committing the images alongside the markdown.
