# Debug Python in VS Code with Dapper

*Guide to using the Dapper VS Code extension (managed venv) or the standalone adapter with VS Code's Python tooling.*

## TL;DR (Two Paths)

### A. Using the Dapper VS Code Extension (managed environment)
1. Install **Dapper Python Debugger** extension.
2. (Optional) Configure settings under `dapper.python.*` (e.g. `installMode: wheel`).
3. Press **F5** on a `dapper` launch configuration. The extension creates a venv in global storage, installs the bundled `dapper` wheel (or PyPI), and launches the debug adapter with `-m dapper.adapter`.

### B. Using Dapper Standalone (external adapter)
1. Install **Python** & **Python Debug** extensions in VS Code.
2. `uv build` (optional for dev) then `uv pip install dapper` (or `pip install dapper`).
3. Run `python -m dapper.adapter --port 4711` in a terminal.
4. Use a Python launch config with `"debugServer": 4711`.
5. Hit **F5**.

Read on for details, options, and troubleshooting.

---

## Why pair VS Code with Dapper?

Visual Studio Code already ships with first-class Python debugging, but Dapper adds:

- **Protocol-first design** – A pure-Python implementation of the Debug Adapter Protocol that you can instrument, extend, or embed.
- **Legibility & hackability** – The adapter is written with type-checked, well-documented code; perfect if you want to learn or customize the DAP.
- **Advanced transports** – Switch between TCP, named pipes, or in-process execution without leaving the comfort of VS Code.
- **Async / concurrency awareness** – Every live `asyncio.Task` appears as a pseudo-thread in the Threads view, step-over skips event-loop internals, and live `threading.Thread` names are reflected in real time.
- **Rich variable display** – Dataclasses, `NamedTuple`s, and Pydantic models (v1 & v2) expand field-by-field with proper `property` hints and a field-count badge; callable and class objects carry their own semantic icons.
- **Friendly for automation** – Dapper is easy to script or run inside CI pipelines while still playing nicely with VS Code's UI.

If you're curious about what powers your debugging sessions—or you want to tailor them—this setup is for you.

## Prerequisites

Before you start, make sure you have:

- **VS Code (1.80+)**
- **Python 3.9 or newer** on your PATH
- **Python extension** (`ms-python.python`) installed in VS Code
- **Python Debug extension** (`ms-python.debugpy`) installed alongside it
- A workspace folder containing the Python project you want to debug

> 💡 *Check your extensions quickly:* open the Command Palette (`Ctrl+Shift+P` / `Cmd+Shift+P`), run **Extensions: Show Installed Extensions**, and verify both "Python" and "Python Debug" are listed.

## Path B Step 1 – Install Dapper into your environment

Open a terminal that targets the environment used for your project (virtualenv, Poetry shell, conda env, etc.). Then install the adapter:

```bash
uv pip install dapper
# ...or...
pip install dapper
```

> 🛠️ Dapper works from any editable install as well. If you are hacking on the adapter itself, run `uv pip install -e ".[dev]"` inside the cloned repo.

## Path B Step 2 – Start the adapter alongside VS Code

Dapper runs as a standalone adapter process. You can keep it in a separate terminal or wire it into a task—whatever fits your workflow.

```bash
python -m dapper.adapter --port 4711
```

Leave this process running; VS Code will connect to it. The number `4711` is arbitrary—pick any open port you like, but reuse the same number in the upcoming `launch.json` configuration.

### Optional twists

- **Named pipe / Unix socket:** prefer local IPC over TCP? Use `--pipe` (Windows) or `--unix` (POSIX). See the [architecture IPC section](../architecture/overview.md) for the full matrix.

## Path B Step 3 – Create a VS Code debug configuration

1. Inside VS Code, open the "Run and Debug" pane (`Ctrl+Shift+D` / `Cmd+Shift+D`).
2. Click **create a launch.json file** (or the gear icon if one already exists).
3. Choose **Python** when prompted.
4. Replace the generated configuration (or add a new one) with:

```jsonc
// .vscode/launch.json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Python: Run with Dapper",
            "type": "python",
            "request": "launch",
            "program": "${file}",
            // WATCH THIS: tell VS Code to connect to the external adapter
            "debugServer": 4711,
            // The remaining fields behave exactly like standard Python launch configs
            "console": "integratedTerminal"
        }
    ]
}
```

What this does:

- `type": "python"` keeps VS Code's existing Python experience (path discovery, environment selection, etc.).
- `debugServer` hijacks the transport layer so VS Code speaks to Dapper instead of the built-in `debugpy` adapter.
- The rest of the options (`program`, `args`, `env`, `cwd`, `justMyCode`) behave exactly as they do in the stock Python debugger.

### Bonus configs you can copy

```jsonc
// Launch with Dapper using IPC named pipes on Windows
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
// Launch with in-process mode for lower latency
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

These extra switches are interpreted by Dapper; VS Code will happily pass them through.

### Dapper-specific launch options (standalone + extension)

- `subprocessAutoAttach` (`boolean`, default `false`):
    - When `true`, Dapper auto-instruments Python child processes created via
        `subprocess.Popen(...)` so they can be attached as child debug sessions.
    - Current scope is Phase 1 (`subprocess.Popen` Python children).
    - Non-Python children are passed through unchanged.

Example:

```jsonc
{
        "type": "dapper",
        "request": "launch",
        "name": "Dapper: Launch with child auto-attach",
        "program": "${file}",
        "subprocessAutoAttach": true
}
```

### Launch options reference (DAP `launch` request)

The following launch fields are recognized by Dapper in VS Code launch configs:

| Option | Type | Notes |
| --- | --- | --- |
| `program` | string | Python file path to run. Mutually exclusive with `module`. |
| `module` | string | Python module name (like `python -m`). Mutually exclusive with `program`. |
| `moduleSearchPaths` | string[] | Optional extra import search paths. |
| `venvPath` | string | Optional virtual environment path used for interpreter selection. |
| `subprocessAutoAttach` | boolean | Auto-attach supported Python child processes. |

- Core target/runtime
    - `program` (`string`): Python file to launch.
    - `module` (`string`): Python module to launch (equivalent to `python -m <module>`).
    - Exactly one of `program` or `module` must be provided.
    - `moduleSearchPaths` (`string[]`, default `[]`): Extra module-resolution paths prepended to `PYTHONPATH` for module launches.
    - `venvPath` (`string`, optional): Virtual environment path (or direct Python executable path) used to run the debug launcher/debuggee.
    - `args` (`string[]`, default `[]`): Arguments passed to the target program.
    - `cwd` (`string`, optional): Working directory for the debuggee.
    - `env` (`object`, default `{}`): Environment variables for the debuggee.
- Debug behavior
    - `stopOnEntry` (`boolean`, default `false`): Break at entry.
    - `noDebug` (`boolean`, default `false`): Run without debugger control.
    - `justMyCode` (`boolean`, default `true`): Filter library/internal frames.
    - `strictExpressionWatchPolicy` (`boolean`, default `false`): Enforce stricter expression watchpoint checks.
- Runtime mode
    - `inProcess` (`boolean`, default `false`): Use in-process backend instead of external debuggee subprocess.
- IPC/transport
    - `ipcTransport` (`"auto" | "pipe" | "unix" | "tcp"`, default `auto`): Adapter↔launcher transport selection.
    - `ipcPipeName` (`string`, optional): Named pipe path when using `pipe`.
    - `useBinaryIpc` (`boolean`, default `true`): Use binary framing for IPC.
- Multi-process
    - `subprocessAutoAttach` (`boolean`, default `false`): Auto-attach Python child processes.

Example with commonly-used advanced options:

```jsonc
{
    "type": "dapper",
    "request": "launch",
    "name": "Dapper: Advanced Launch",
    "program": "${file}",
    "args": ["--verbose"],
    "cwd": "${workspaceFolder}",
    "env": {
        "PYTHONUNBUFFERED": "1"
    },
    "stopOnEntry": false,
    "justMyCode": true,
    "strictExpressionWatchPolicy": false,
    "inProcess": false,
    "ipcTransport": "auto",
    "useBinaryIpc": true,
    "subprocessAutoAttach": true
}
```

Example: module launch with explicit module search environment

```jsonc
{
    "type": "dapper",
    "request": "launch",
    "name": "Dapper: Module Launch",
    "module": "my_app.main",
    "moduleSearchPaths": [
        "${workspaceFolder}/src",
        "${workspaceFolder}/libs"
    ],
    "env": {
        "PYTHONPATH": "${workspaceFolder}/vendor"
    },
    "args": ["--port", "8080"]
}
```

Example: module launch using a virtual environment directly

```jsonc
{
    "type": "dapper",
    "request": "launch",
    "name": "Dapper: Module Launch in venv",
    "module": "my_app.main",
    "venvPath": "${workspaceFolder}/.venv",
    "args": ["--port", "8080"]
}
```

Tip: prefer `venvPath` when your module dependencies are installed in that
environment. Use `moduleSearchPaths` when you specifically need extra source
directories added to resolution.

### Advanced: debug launcher target modes

The internal launcher now supports mutually exclusive target forms:

- `--program <path>`
- `--module <module>` (like `python -m <module>`)
- `--code <code>` (like `python -c <code>`)
- `--module-search-path <path>` (repeatable)

These are mainly used by Dapper internals (notably child-process auto-attach rewrite paths).
For normal VS Code usage, prefer `launch.json` with `program`.

## Path B Step 4 – Start debugging

1. Make sure the adapter terminal is still running.
2. Select **Python: Run with Dapper** from the debug dropdown.
3. Press **F5**.

You should see your terminal process (running Dapper) log the incoming client connection and the Python program start under the debugger. Breakpoints, `watch` expressions, call stack inspection, and step controls all work just like the stock experience.

> ✨ *Hot tip:* Use VS Code's "Python: Select Interpreter" command to match the environment that installed Dapper. If the adapter process lives in a different interpreter, you'll want to pass `--interpreter` when launching it so breakpoint paths align.

## Extension Path A – Managed venv details

When using the VS Code extension:

- On activation the extension calls its `EnvironmentManager` to:
    - Create (or reuse) a virtual environment under the extension's global storage path using `python -m venv`.
    - Install the bundled `dapper-<version>.whl` (or PyPI fallback) via `pip`.
    - Record a manifest (`dapper-env.json`) with installed version and source.
- The debug adapter factory launches `python -m dapper.adapter` with flags derived from your launch configuration.
- Settings you can tune:
    - `dapper.python.installMode`: `auto | wheel | pypi | workspace`
    - `dapper.python.baseInterpreter`: path to Python used for venv creation.
    - `dapper.python.forceReinstall`: force package reinstall on activation.
    - `dapper.python.expectedVersion`: override target dapper version.
- To reset: run the internal reset command (planned) or manually delete the venv folder from the extension global storage directory.

### Launch configuration with the extension

Use a debugger type of `dapper` instead of `python`:

```jsonc
{
    "type": "dapper",
    "request": "launch",
    "name": "Dapper: Launch Current File",
    "program": "${file}",
    "stopOnEntry": true,
    "subprocessAutoAttach": false,
    "args": [],
    "noDebug": false
}
```

Breakpoints, stack inspection, variables, and evaluation flow through the extension's adapter process.

## Quality-of-life improvements (Both Paths)

- **Persistent watchpoints:** Dapper supports variable and expression watchpoints through `setDataBreakpoints` (including `frame:<id>:expr:<expression>`). Variable read watchpoints are available on Python 3.12+ (`sys.monitoring`); older versions gracefully fall back to write semantics. See the [Watchpoints reference](../guides/watchpoints.md) for payload format and behavior.
- **Hot reload while paused:** Use `Dapper: Hot Reload Current File` (default `Ctrl+Alt+R` / `Cmd+Alt+R`) to reload the active Python file during a stopped session. You can also enable automatic reload on save with `dapper.hotReload.autoOnSave`. Current runtime support is in-process sessions.
- **Reference:** See the [Hot Reload reference](../guides/hot-reload.md) for request/event details, safety checks, limitations, and telemetry counters.
- **Task integration:** Create a VS Code task that runs `python -m dapper.adapter --port 4711`, then add a [`preLaunchTask`](https://code.visualstudio.com/docs/editor/tasks#_compound-tasks) to your debug configuration so the adapter spins up automatically.
- **multi-root workspaces:** Include one adapter task per workspace folder, each with its own port, and set `debugServer` accordingly.
- **Version pinning:** If you rely on specific Dapper features, add `dapper==<version>` to your `requirements.txt` to keep teammates in sync.
- **Source-mapped debugging:** When editing Dapper itself, launch VS Code's debugger against the adapter process so you can step through its code while it controls your program—turtles all the way down.

### Quick configuration UI

- The extension provides a small configuration web UI that you can open via the command palette: **Dapper: Configure Settings**. This opens a form where you can edit and preview a debug configuration.
- Once you save a configuration, you can insert it directly into `.vscode/launch.json` using the **Save & Insert to launch.json** action, or by running the command **Dapper: Add Saved Debug Configuration to launch.json**. This will insert the configuration into your active workspace `launch.json` and prompt you on conflicts.
- You can also start a debug session from the UI using **Start Debugging**, or from the command palette with **Dapper: Start Debugging with Saved Config**.

## Troubleshooting

| Symptom | Quick Fix |
| --- | --- |
| VS Code times out with "Cannot connect to runtime" | Path B: ensure the adapter terminal shows a listening port. Path A (extension): check the output channel "Dapper Python Env" for spawn errors. |
| Breakpoints are hollow (not bound) | Extension path: confirm the managed venv installed the same version of dapper you expect. Standalone path: mismatch between adapter interpreter and project interpreter. |
| Program launches outside VS Code's environment | Add `"console": "integratedTerminal"` or specify `"env"` / `"envFile"` so Dapper inherits the same environment variables. |
| No output in the Debug Console | Dapper defaults to forwarding stdout/stderr. If you've changed `redirectOutput`, flip it back to `true` in your configuration. |
| Need to stop everything fast | Shift+F5 stops the session. For standalone adapter, Ctrl+C the terminal. For extension, close the session; the managed venv persists. |

Still stuck? The [`Manual Testing` guide](manual-testing.md) lists end-to-end flows for validating transports and breakpoints.

## Next steps

- Explore the [examples](../examples/README.md) for creative ways to embed Dapper into scripts and services.
- Skim the [architecture overview](../architecture/overview.md) if you want to extend or customize the adapter.
- File issues or share your hacks—Dapper is open-source and eager for contributions!

Happy debugging—whether via the managed extension or standalone adapter! 🎯
