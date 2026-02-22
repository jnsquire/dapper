# Quick Start

Get from zero to a working debugging session in a few minutes.

## 1. Prerequisites

Before you begin, make sure Dapper is installed. See the [Installation](installation.md) guide if you haven't done this yet.

## 2. Start the Debug Adapter

Open a terminal and launch the Dapper debug adapter:

```bash
python -m dapper.adapter --port 4711
```

The adapter will listen on port 4711 and wait for a client to connect. Keep this terminal open while you debug.

## 3. Configure VS Code

Create or open `.vscode/launch.json` in your project and add this configuration:

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Python: Dapper",
            "type": "python",
            "request": "attach",
            "debugServer": 4711
        }
    ]
}
```

This tells VS Code to attach to the running adapter rather than launching its own.

## 4. Set a Breakpoint

Open the Python file you want to debug in VS Code. Click in the left gutter next to a line of code to set a breakpoint (a red dot will appear).

## 5. Start Debugging

Press `F5` or open the **Run and Debug** panel (`Ctrl+Shift+D`) and click **Start Debugging**. VS Code will connect to the Dapper adapter and run your program. Execution will pause at your breakpoint.

!!! note "TODO"
    Screenshots of the VS Code debugging UI will be added here to illustrate each step.

## 6. Inspect Variables

When execution is paused at a breakpoint:

- The **Variables** panel (left sidebar) shows local and global variables in the current scope.
- Hover over any variable in the editor to see its value in a tooltip.
- Use the **Debug Console** (`Ctrl+Shift+Y`) to evaluate arbitrary expressions in the current frame.
- Use the **Call Stack** panel to navigate between stack frames.

## Next Steps

- [Using VS Code](using-vscode.md) — full walkthrough of Dapper's VS Code integration
- [Guides](../guides/async-debugging.md) — advanced debugging scenarios
