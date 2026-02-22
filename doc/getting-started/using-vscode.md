# Debug Python in VS Code with Dapper

*Install the Dapper VS Code extension, press F5. The extension handles the rest.*

> **Using Dapper without the extension?** See [Standalone Adapter Setup](standalone-adapter.md) for manual adapter launch configs and the full launch options reference.

---

## Quick setup

1. Install the **Dapper Python Debugger** extension from the VS Code marketplace.
2. (Optional) Tune settings under `dapper.python.*` — see [Extension settings](#extension-settings) below.
3. Add a `dapper` launch configuration to `.vscode/launch.json` and press **F5**.

```jsonc
// .vscode/launch.json
{
    "version": "0.2.0",
    "configurations": [
        {
            "type": "dapper",
            "request": "launch",
            "name": "Dapper: Launch Current File",
            "program": "${file}",
            "stopOnEntry": false,
            "args": []
        }
    ]
}
```

---

## Why use Dapper with VS Code?

VS Code already ships first-class Python debugging, but Dapper adds:

- **Protocol-first design** — A pure-Python DAP implementation you can instrument, extend, or embed.
- **Legibility & hackability** — Type-checked, well-documented code; ideal if you want to learn or customize the DAP.
- **Advanced transports** — Switch between TCP, named pipes, or in-process execution without leaving VS Code.
- **Async / concurrency awareness** — Every live `asyncio.Task` appears as a pseudo-thread in the Threads view; step-over skips event-loop internals; live `threading.Thread` names update in real time.
- **Rich variable display** — Dataclasses, `NamedTuple`s, and Pydantic models (v1 & v2) expand field-by-field with proper `property` hints and a field-count badge.
- **Automation-friendly** — Easy to script or run inside CI pipelines.

## Prerequisites

- **VS Code 1.80+**
- **Python 3.9 or newer** on your PATH
- **Python extension** (`ms-python.python`) installed

## How the extension manages the adapter

On activation, the extension's `EnvironmentManager`:

1. Creates (or reuses) a virtual environment under the extension's global storage path using `python -m venv`.
2. Installs the bundled `dapper-<version>.whl` (or falls back to PyPI).
3. Records a manifest (`dapper-env.json`) with installed version and source.

The debug adapter factory then launches `python -m dapper.adapter` with flags derived from your launch configuration.

## Extension settings

| Setting | Values | Description |
|---|---|---|
| `dapper.python.installMode` | `auto \| wheel \| pypi \| workspace` | Where to source the dapper package. |
| `dapper.python.baseInterpreter` | path | Python used for venv creation. |
| `dapper.python.forceReinstall` | boolean | Force reinstall on activation. |
| `dapper.python.expectedVersion` | string | Override target dapper version. |

To reset the managed environment, delete the venv folder from the extension's global storage directory.

## Quality-of-life features

- **Persistent watchpoints:** Dapper supports variable and expression watchpoints through `setDataBreakpoints` (including `frame:<id>:expr:<expression>`). Variable read watchpoints are available on Python 3.12+ (`sys.monitoring`); older versions fall back to write semantics. See the [Watchpoints reference](../guides/watchpoints.md).
- **Hot reload while paused:** Use **Dapper: Hot Reload Current File** (default `Ctrl+Alt+R` / `Cmd+Alt+R`) to reload the active Python file during a stopped session. Enable automatic reload on save with `dapper.hotReload.autoOnSave`. See the [Hot Reload reference](../guides/hot-reload.md).
- **Task integration:** Create a VS Code task that runs `python -m dapper.adapter --port 4711`, then add a [`preLaunchTask`](https://code.visualstudio.com/docs/editor/tasks#_compound-tasks) to your debug configuration so the adapter spins up automatically.
- **Multi-root workspaces:** Include one adapter task per workspace folder, each on its own port, and set `debugServer` accordingly.

## Quick configuration UI

The extension provides a configuration web UI accessible via the Command Palette:

- **Dapper: Configure Settings** — opens a form to edit and preview a debug configuration.
- **Save & Insert to launch.json** — inserts the configuration directly into `.vscode/launch.json`.
- **Dapper: Start Debugging with Saved Config** — start a session from the saved configuration.

## Troubleshooting

| Symptom | Quick Fix |
|---|---|
| VS Code times out with "Cannot connect to runtime" | Check the output channel **Dapper Python Env** for spawn errors. |
| Breakpoints are hollow (not bound) | Confirm the managed venv installed the expected dapper version (`dapper.python.expectedVersion`). |
| Program launches outside VS Code's environment | Add `"console": "integratedTerminal"` or specify `"env"` / `"envFile"` in your launch config. |
| No output in the Debug Console | Ensure `redirectOutput` is not set to `false`. |
| Need to stop everything fast | Shift+F5 stops the session; close the session to leave the managed venv intact. |

For standalone adapter issues, see the [Standalone Adapter Setup](standalone-adapter.md) troubleshooting section.
Still stuck? The [Manual Testing guide](manual-testing.md) lists end-to-end flows for validating transports and breakpoints.

## Next steps

- Try the [examples](../examples/README.md) for creative ways to embed Dapper into scripts and services.
- Read the [architecture overview](../architecture/overview.md) if you want to extend or customize the adapter.
