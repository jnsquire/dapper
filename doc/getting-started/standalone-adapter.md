# Standalone Adapter Setup

*Use this guide if you want to run the Dapper adapter as a separate process and connect to it from VS Code (or any DAP-compatible editor) without the managed VS Code extension.*

## Overview

1. Install **Python** & **Python Debug** extensions in VS Code.
2. Install Dapper: `pip install dapper`.
3. Run `python -m dapper.adapter --port 4711` in a terminal.
4. Add a launch config with `"debugServer": 4711`.
5. Press **F5**.

---

## Step 1 – Install Dapper into your environment

Open a terminal targeting the environment used for your project (virtualenv, Poetry shell, conda env, etc.):

```bash
uv pip install dapper
# ...or...
pip install dapper
```

> 🛠️ For hacking on the adapter itself: `uv pip install -e ".[dev]"` inside the cloned repo.

## Step 2 – Start the adapter

```bash
python -m dapper.adapter --port 4711
```

Leave this process running; VS Code will connect to it. The port number is arbitrary—pick any open port, but reuse the same number in `launch.json`.

**Named pipe / Unix socket:** prefer local IPC over TCP? Use `--pipe` (Windows) or `--unix` (POSIX). See the [architecture IPC section](../architecture/ipc.md) for the full matrix.

## Step 3 – Create a launch config

In `.vscode/launch.json`, set `"debugServer"` to tell VS Code to connect to the running adapter instead of spawning its own:

```jsonc
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Python: Run with Dapper",
            "type": "python",
            "request": "launch",
            "program": "${file}",
            "debugServer": 4711,
            "console": "integratedTerminal"
        }
    ]
}
```

- `"type": "python"` keeps VS Code's Python experience (path discovery, environment selection).
- `"debugServer"` routes the transport to Dapper instead of the built-in debugpy.
- All standard options (`args`, `env`, `cwd`, `justMyCode`) work as normal.

### IPC and attach configs

```jsonc
// Named pipe on Windows
{
    "name": "Python: Dapper (Named Pipe)",
    "type": "python",
    "request": "launch",
    "program": "${file}",
    "debugServer": 4711,
    "useIpc": true,
    "ipcTransport": "pipe",
    "ipcPipeName": "\\\\.\\pipe\\dapper-demo"
}
```

```jsonc
// In-process mode (adapter runs on a background thread)
{
    "name": "Python: Dapper (In-Process)",
    "type": "python",
    "request": "launch",
    "program": "${file}",
    "debugServer": 4711,
    "inProcess": true
}
```

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
```

```jsonc
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
```

```jsonc
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

## Step 4 – Start debugging

1. Confirm the adapter terminal is still running.
2. Select **Python: Run with Dapper** from the debug dropdown.
3. Press **F5**.

> ✨ Use VS Code's **Python: Select Interpreter** command to match the environment that installed Dapper. If the adapter process runs in a different interpreter, paths for breakpoints may not align.

---

## Launch options reference

### Child process auto-attach

`subprocessAutoAttach` (`boolean`, default `false`): when `true`, Dapper auto-instruments Python child processes created via `subprocess.Popen(...)` so they can be attached as child debug sessions.

```jsonc
{
    "type": "dapper",
    "request": "launch",
    "name": "Dapper: Launch with child auto-attach",
    "program": "${file}",
    "subprocessAutoAttach": true
}
```

### Full options table

| Option | Type | Notes |
|---|---|---|
| `program` | string | Python file to run. Mutually exclusive with `module`. |
| `module` | string | Python module name (like `python -m`). Mutually exclusive with `program`. |
| `moduleSearchPaths` | string[] | Extra import search paths prepended to `PYTHONPATH`. |
| `venvPath` | string | Virtual environment path for interpreter selection. |
| `args` | string[] | Arguments passed to the target program. |
| `cwd` | string | Working directory for the debuggee. |
| `env` | object | Environment variables for the debuggee. |
| `stopOnEntry` | boolean | Break at entry (default `false`). |
| `noDebug` | boolean | Run without debugger control (default `false`). |
| `justMyCode` | boolean | Filter library/internal frames (default `true`). |
| `strictExpressionWatchPolicy` | boolean | Stricter expression watchpoint checks (default `false`). |
| `inProcess` | boolean | Use in-process backend instead of a subprocess (default `false`). |
| `ipcTransport` | `"auto"\|"pipe"\|"unix"\|"tcp"` | Adapter↔launcher transport (default `auto`). |
| `ipcPipeName` | string | Named pipe path when using `pipe`. |
| `useBinaryIpc` | boolean | Binary framing for IPC (default `true`). |
| `subprocessAutoAttach` | boolean | Auto-attach Python child processes (default `false`). |

### Example: advanced launch

```jsonc
{
    "type": "dapper",
    "request": "launch",
    "name": "Dapper: Advanced Launch",
    "program": "${file}",
    "args": ["--verbose"],
    "cwd": "${workspaceFolder}",
    "env": { "PYTHONUNBUFFERED": "1" },
    "justMyCode": true,
    "inProcess": false,
    "ipcTransport": "auto",
    "subprocessAutoAttach": true
}
```

### Example: module launch

```jsonc
{
    "type": "dapper",
    "request": "launch",
    "name": "Dapper: Module Launch",
    "module": "my_app.main",
    "moduleSearchPaths": ["${workspaceFolder}/src"],
    "args": ["--port", "8080"]
}
```

```jsonc
// Using a virtual environment directly
{
    "type": "dapper",
    "request": "launch",
    "name": "Dapper: Module Launch in venv",
    "module": "my_app.main",
    "venvPath": "${workspaceFolder}/.venv",
    "args": ["--port", "8080"]
}
```

Prefer `venvPath` when module dependencies are installed in that environment. Use `moduleSearchPaths` when you need extra source directories added to resolution.

### Advanced: debug launcher target modes

The internal launcher supports these mutually exclusive target forms (mainly used by Dapper internals):

- `--program <path>`
- `--module <module>` (like `python -m <module>`)
- `--code <code>` (like `python -c <code>`)
- `--module-search-path <path>` (repeatable)

For normal usage, prefer `launch.json` with `program`.

---

## Troubleshooting

| Symptom | Quick Fix |
|---|---|
| VS Code times out with "Cannot connect to runtime" | Ensure the adapter terminal shows a listening port on the correct port number. |
| Breakpoints are hollow (not bound) | Mismatch between the adapter interpreter and the project interpreter — use `--interpreter` when launching the adapter. |
| Program launches outside VS Code's environment | Add `"console": "integratedTerminal"` or specify `"env"` / `"envFile"`. |
| No output in the Debug Console | Ensure `redirectOutput` is not set to `false` in your configuration. |

Still stuck? The [Manual Testing guide](manual-testing.md) lists end-to-end flows for validating transports and breakpoints.
