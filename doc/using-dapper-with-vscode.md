# Debug Python in VS Code with Dapper

*A blog-style walkthrough for wiring up the Dapper debug adapter with Visual Studio Code's Python tooling.*

## TL;DR

1. Install the **Python** and **Python Debug** extensions in VS Code.
2. Add `dapper` to your Python environment: `uv pip install dapper` *(or `pip install dapper` if you prefer).* 
3. Launch the adapter: `python -m dapper --port 4711`.
4. Point your `launch.json` at that port with a standard Python configuration that sets `"debugServer": 4711`.
5. Hit **F5** and enjoy step-through debugging, breakpoints, and watch expressions powered by Dapper.

Read on for the full story, tips, and troubleshooting recipes.

---

## Why pair VS Code with Dapper?

Visual Studio Code already ships with first-class Python debugging, but Dapper adds:

- **Protocol-first design** – A pure-Python implementation of the Debug Adapter Protocol that you can instrument, extend, or embed.
- **Legibility & hackability** – The adapter is written with type-checked, well-documented code; perfect if you want to learn or customize the DAP.
- **Advanced transports** – Switch between TCP, named pipes, or in-process execution without leaving the comfort of VS Code.
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

## Step 1 – Install Dapper into your environment

Open a terminal that targets the environment used for your project (virtualenv, Poetry shell, conda env, etc.). Then install the adapter:

```bash
uv pip install dapper
# ...or...
pip install dapper
```

> 🛠️ Dapper works from any editable install as well. If you are hacking on the adapter itself, run `uv pip install -e ".[dev]"` inside the cloned repo.

## Step 2 – Start the adapter alongside VS Code

Dapper runs as a standalone adapter process. You can keep it in a separate terminal or wire it into a task—whatever fits your workflow.

```bash
python -m dapper --port 4711
```

Leave this process running; VS Code will connect to it. The number `4711` is arbitrary—pick any open port you like, but reuse the same number in the upcoming `launch.json` configuration.

### Optional twists

- **Named pipe / Unix socket:** prefer local IPC over TCP? Use `--pipe` (Windows) or `--unix` (POSIX). See the main [`README.md`](../README.md#subprocess-ipc-adapter--launcher) for the full matrix.
- **In-process mode:** add `--in-process` if you want the adapter to share the same Python interpreter as your program for faster, more direct control.

## Step 3 – Create a VS Code debug configuration

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

These extra switches are interpreted by Dapper; VS Code will happily pass them through.

## Step 4 – Start debugging

1. Make sure the adapter terminal is still running.
2. Select **Python: Run with Dapper** from the debug dropdown.
3. Press **F5**.

You should see your terminal process (running Dapper) log the incoming client connection and the Python program start under the debugger. Breakpoints, `watch` expressions, call stack inspection, and step controls all work just like the stock experience.

> ✨ *Hot tip:* Use VS Code's "Python: Select Interpreter" command to match the environment that installed Dapper. If the adapter process lives in a different interpreter, you'll want to pass `--interpreter` when launching it so breakpoint paths align.

## Quality-of-life improvements

- **Task integration:** Create a VS Code task that runs `python -m dapper --port 4711`, then add a [`preLaunchTask`](https://code.visualstudio.com/docs/editor/tasks#_compound-tasks) to your debug configuration so the adapter spins up automatically.
- **multi-root workspaces:** Include one adapter task per workspace folder, each with its own port, and set `debugServer` accordingly.
- **Version pinning:** If you rely on specific Dapper features, add `dapper==<version>` to your `requirements.txt` to keep teammates in sync.
- **Source-mapped debugging:** When editing Dapper itself, launch VS Code's debugger against the adapter process so you can step through its code while it controls your program—turtles all the way down.

## Troubleshooting

| Symptom | Quick Fix |
| --- | --- |
| VS Code times out with "Cannot connect to runtime" | Confirm the adapter terminal shows `Serving on 4711`. Ports blocked? Pick another port or disable firewalls temporarily. |
| Breakpoints are hollow (not bound) | Ensure the adapter's interpreter matches your project's interpreter. Verify file paths line up with the `program`/`cwd` values. |
| Program launches outside VS Code's environment | Add `"console": "integratedTerminal"` or specify `"env"` / `"envFile"` so Dapper inherits the same environment variables. |
| No output in the Debug Console | Dapper defaults to forwarding stdout/stderr. If you've changed `redirectOutput`, flip it back to `true` in your configuration. |
| Need to stop everything fast | Use **Shift+F5** in VS Code or send `Ctrl+C` to the adapter terminal; both will tear down the debug session. |

Still stuck? The [`MANUAL_TESTING_GUIDE`](MANUAL_TESTING_GUIDE.md) lists end-to-end flows for validating transports and breakpoints.

## Next steps

- Explore the [examples](../examples/README.md) for creative ways to embed Dapper into scripts and services.
- Skim the [ARCHITECTURE](ARCHITECTURE.md) notes if you want to extend or customize the adapter.
- File issues or share your hacks—Dapper is open-source and eager for contributions!

Happy debugging! 🎯
