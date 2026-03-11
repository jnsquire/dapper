# Dapper Python Debugger (VS Code Extension)

Enhance your Python debugging experience with the Dapper debug adapter and React-based UI. This extension provides improved variable inspection, frame evaluation, and an opinionated debugging flow backed by a fast backend Python launcher.

## Features

- Fast, binary IPC between the VS Code extension and Python debug adapter.
- Improved variable inspector with nested view and lazy evaluation.
- Frame evaluation support for fast and safe expression evaluation while paused.
- Quick launch configurations for Python files and saved configurations.
- Optional in-process or out-of-process debug adapter modes.

## Installation

- From VSIX: Build and package the extension, then install the generated `.vsix` file using the VS Code "Install from VSIX..." command.
- From Marketplace: Install directly from the Visual Studio Marketplace (if published).

### Build & Package (from source)

1. Install Node.js dependencies and build the extension:

```powershell
# From the root of the repo
cd vscode/extension
npm ci
npm run build
```

2. To create a VSIX package (packaging script uses vsce):

```powershell
npm run package
# The resulting VSIX will be written to vscode/extension/dist/<package>.vsix
```

3. To test the installed extension after rebuilding, reinstall the VSIX and
reload the VS Code window:

```powershell
code --install-extension dist/dapper-debugger-0.9.3.vsix --force
```

Notes:

- Use `command -v code` if you need the full CLI path, especially in WSL or
  remote environments where VS Code provides a remote CLI wrapper.
- Rebuilding or repackaging alone does not replace the code already loaded in
  the active extension host. After reinstalling the VSIX, run **Developer:
  Reload Window** before retrying extension-host behavior.

### Publish To Marketplace

1. Create a Visual Studio Marketplace Personal Access Token with `Marketplace (Manage)` scope and `All accessible organizations`.
2. Log in once with `vsce`:

```powershell
cd vscode/extension
npm run publisher:login
```

3. Publish a normal release:

```powershell
cd vscode/extension
$env:VSCE_PAT = "<your-pat>"
npm run publish:marketplace
```

4. Publish a pre-release instead:

```powershell
cd vscode/extension
$env:VSCE_PAT = "<your-pat>"
npm run publish:marketplace:pre
```

Notes:

- `publish:marketplace` reuses the existing package flow, produces a VSIX in `dist/`, and then publishes that exact package with `vsce`.
- Do not commit your PAT. Prefer setting `VSCE_PAT` in your shell or CI environment.

## Quick Start

1. Open **Dapper: Open Launch Configuration Wizard** to create and save a configuration.
2. Use **Save & Insert to launch.json** in the wizard (or run **Dapper: Add Saved Debug Configuration**) to write it to `launch.json`.
3. Start debugging with **F5** or the `Dapper: Debug This` command.
4. Use `Dapper: Run This` when you want the same interpreter and environment selection logic without attaching the debugger.

In the editor title run actions, hold `Alt` while clicking `Debug This` or `Run This` to pick the Python environment for that launch explicitly.

### How Debug This Works

`Dapper: Debug This` does not require an existing `launch.json` entry. It builds a temporary Dapper launch configuration for the active Python file, starts that file in an integrated terminal, and names the session from the file name.

`Dapper: Run This` uses the same target resolution and environment selection as `Debug This`, but starts the process through Dapper's own launcher in an owned terminal with `--no-debug` so it can still track logs, process metadata, and exit status consistently.

The Python environment is chosen in this order:

- Explicit interpreter hints. If a launch request already carries `pythonPath` or `venvPath`, Dapper uses that first.
- The active Python interpreter from the Python extension. For `Debug This`, `LaunchService` asks `ms-python.python` for the active interpreter in the current workspace and uses it when available.
- A workspace virtual environment. In `auto` mode, Dapper scans the active workspace for common venv folders such as `.venv`, `venv`, `env`, and `.env`.
- A new workspace virtual environment that Dapper offers to create. If no usable workspace venv exists, Dapper prompts to create `.venv` in the workspace and aborts the launch if you decline.

How Dapper becomes available inside that interpreter depends on the installation mode:

- `auto`: Prefer the selected workspace interpreter so the debuggee runs with the project's real dependencies. If that interpreter does not already have Dapper installed, the extension extracts the bundled Dapper wheel into extension storage and prepends that location to `PYTHONPATH` instead of modifying the workspace venv. If no workspace venv exists, Dapper offers to create `.venv` for the workspace before launching.
- `workspace`: Use the chosen workspace interpreter directly. This mode resolves the interpreter from `pythonPath`, `venvPath`, `dapper.python.baseInterpreter`, or finally `python3`/`python` on `PATH`.
- `wheel` or `pypi`: If no preferred interpreter can already run Dapper, the extension prepares its managed environment and installs Dapper there from the bundled wheel or PyPI.

At launch time, Dapper also builds the process environment by combining the VS Code extension host environment, any explicit `env` values from the launch request, Dapper-specific variables such as `DAPPER_LOG_FILE` and `DAPPER_LOG_LEVEL`, and a `PYTHONPATH` entry when Dapper is injected rather than installed into the selected interpreter.

The session log level comes from the `dapper.debugger.logLevel` setting. The extension passes that value to the Python launcher through `DAPPER_LOG_LEVEL`, so the same setting applies to both debugger-attached launches and `Run This` launches.

### Launch Configuration Wizard

Use the wizard to configure `program`/`module`, runtime options, debug options, and then review the final JSON before saving.

You can open it from:

- Command Palette: `Dapper: Open Launch Configuration Wizard`
- Run and Debug view title actions (Debug sidebar)
- Active debug toolbar (for Dapper sessions)

The legacy command **Dapper: Configure Settings** is still available as an alias.

## Example Configurations

### Python file launch

```json
{
  "type": "dapper",
  "request": "launch",
  "name": "Python: Dapper Debug",
  "program": "${file}",
  "console": "integratedTerminal"
}
```

### Python module launch

```json
{
  "type": "dapper",
  "request": "launch",
  "name": "Python: Dapper Module",
  "module": "package.module",
  "moduleSearchPaths": ["${workspaceFolder}/src"],
  "venvPath": "${workspaceFolder}/.venv",
  "subprocessAutoAttach": true,
  "console": "integratedTerminal"
}
```

### Launch target rule

- Use exactly one launch target: `program` or `module`.

### Launch options quick reference

| Option | Type | Notes |
| --- | --- | --- |
| `program` | string | Python file path to run. Mutually exclusive with `module`. |
| `module` | string | Python module name (like `python -m`). Mutually exclusive with `program`. |
| `moduleSearchPaths` | string[] | Optional extra import search paths. |
| `venvPath` | string | Optional virtual environment path used for interpreter selection. |
| `subprocessAutoAttach` | boolean | Auto-attach supported Python child processes through one shared child IPC listener per parent debug session. |

When `subprocessAutoAttach` is enabled, Dapper allocates one shared child IPC
listener for the parent debug session and passes that port into rewritten Python
subprocess launches. Each child connects back to that shared listener and sends
an internal `dapper/sessionHello` handshake with its logical `sessionId` before
the extension starts the child VS Code debug session.

## Commands

- `Dapper: Open Launch Configuration Wizard` - Open the step-by-step launch configuration wizard.
- `Dapper: Debug This` - Start debugging the active Python file without first creating a `launch.json` entry.
- `Dapper: Debug This (Pick Environment)` - Start debugging the active Python file after choosing the interpreter from a quick pick.
- `Dapper: Run This` - Run the active Python file with Dapper's interpreter-selection logic but without attaching the debugger.
- `Dapper: Run This (Pick Environment)` - Run the active Python file after choosing the interpreter from a quick pick.
- `Dapper: Toggle Breakpoint` - Toggles a breakpoint at the current cursor.
- `Dapper: Show Variable Inspector` - Opens the variable inspector view for the active debug session.
- `Dapper: Configure Settings` - Legacy alias for opening the launch configuration wizard.
- `Dapper: Add Saved Debug Configuration to launch.json` - Save and insert a configuration.
- `Dapper: Start Debugging with Saved Config` - Start debugging using a saved configuration.

## Launches View

The **Dapper Launches** view in the Run and Debug sidebar keeps a recent in-memory list of launches started through Dapper commands and APIs.

For each launch, the view shows the launch mode, current process details when known, and the final exit status when Dapper can observe it. If Dapper created a log file for that launch, the entry also exposes an inline action to open that file.

You can remove a single launch record from the item actions, or clear the entire in-memory launch history from the view title actions.

The view includes both debug launches and `Run This` launches, because both now run through Dapper's launcher. That lets Dapper record the process metadata, exit status, and any log file path it created even when the debugger is not attached.

## Command API

For integrations, the extension also exposes two API-oriented VS Code commands that reuse the same launch and environment-selection path as `Debug This` and `Run This`:

- `dapper.api.debugLaunch` - Launch with the debugger attached.
- `dapper.api.runLaunch` - Launch with `noDebug: true`.

These commands are intended for `vscode.commands.executeCommand(...)`, not for the Command Palette. They accept the same options shape used by the shared launch service:

```ts
type DapperLaunchCommandOptions = {
  sessionName?: string;
  target?: {
    currentFile?: boolean;
    file?: string;
    module?: string;
    configName?: string;
  };
  args?: string[];
  cwd?: string;
  env?: Record<string, string>;
  moduleSearchPaths?: string[];
  venvPath?: string;
  pythonPath?: string;
  stopOnEntry?: boolean;
  justMyCode?: boolean;
  subprocessAutoAttach?: boolean;
  waitForStop?: boolean;
};
```

Rules:

- Omit `target` to use the active Python file.
- Provide exactly one target: `currentFile`, `file`, `module`, or `configName`.
- `dapper.api.runLaunch` always forces `noDebug: true` and disables `stopOnEntry`.
- Both commands return the same launch result shape produced by the shared launch flow.
- `dapper.api.runLaunch` returns without a `session` because it launches a Dapper-owned no-debug process rather than creating a VS Code debug session.

Examples:

```ts
await vscode.commands.executeCommand('dapper.api.debugLaunch', {
  target: { file: '/workspace/app.py' },
  stopOnEntry: false,
});

await vscode.commands.executeCommand('dapper.api.runLaunch', {
  target: { module: 'package.cli' },
  args: ['--help'],
  cwd: '/workspace',
});
```

## For Agents

The tool schema in `package.json` covers inputs. These notes cover the behavior agents usually need:

- Use `dapper_launch` to start debugging Python code when there is no active Dapper session yet.
- `dapper_launch` accepts a file, module, current editor, or named Dapper launch config. Omit `target`
  to use the active Python file.
- `dapper_launch` prefers an explicit `pythonPath` or `venvPath`, then falls back to the project's
  configured or discovered Python environment.
- `dapper_launch` may inject Dapper via `PYTHONPATH` instead of installing it into the workspace
  environment.
- Set `waitForStop: true` on `dapper_launch` when you want the initial pause before calling
  `dapper_state`, `dapper_variable`, or `dapper_evaluate`.
- Omit `sessionId` to use the active Dapper session. Tools do not fall back to non-Dapper sessions.
- Start with `dapper_state` in `snapshot` mode when paused. It returns stop reason, location, call stack,
  locals, globals, and thread state.
- `dapper_state` in `snapshot` mode can fall back to a cached placeholder snapshot. In that case `callStack`,
  `locals`, and `globals` may be empty, and `_adapterError` may be present.
- Use `dapper_execution` with `report: true` for next/stepIn/stepOut/continue when you want the action,
  the next stop, and the resulting diff in one call.
- `dapper_execution` returning `stopped: false` means the session did not stop again before the
  timeout or terminated.
- `dapper_execution` without `report: true` returns acknowledgement states like `running`, `pausing`,
  and `terminating`; it does not wait for all later events.
- `dapper_evaluate` and `dapper_variable` execute code in the debuggee and can have side
  effects.
- `dapper_evaluate` accepts `expression` or `expressions`, but always runs as a batch in the chosen
  `frameIndex`.
- `dapper_variable` is best for structured values; it expands dicts, lists, tuples, and
  public object attributes to the requested depth.
- `dapper_breakpoints` uses `list`, `add`, `remove`, and `clear`.
- `dapper_breakpoints` with `action: add` updates VS Code and also sends a direct `setBreakpoints`
  request so the adapter sees new breakpoints immediately.
- `dapper_breakpoints` with `action: list` always reports the VS Code breakpoint list and, with an
  active Dapper session, merges adapter verification state into `verified` when it is definitive.
- `dapper_breakpoints` may return `verificationState: pending` when the adapter has not yet bound a
  breakpoint to executable code. This is different from a definitive rejection.
- `dapper_session_info` can list tracked sessions, but only the active one has a live
  `DebugSession`; other tracked sessions may show `state: unknown` with minimal config.
- Test fixtures in this repo keep launch examples as `.vscode/launch.template.json` instead of a
  real `.vscode/launch.json` so VS Code does not schema-validate nested fixture files as active
  workspace launch configurations.

Recommended agent workflow while paused:

1. Call `dapper_session_info` if you need to identify the session.
2. Call `dapper_state` with `mode: snapshot` to understand the current stop.
3. Use `dapper_variable` for structured objects and `dapper_evaluate` for focused scalar expressions.
4. Use `dapper_execution` with `report: true` to advance execution while preserving checkpoint context.
5. Use `dapper_breakpoints` with `action: list` and `action: add/remove/clear` when checking whether a breakpoint is present but not verified.

## Settings

The extension exposes the following settings under `dapper`:

- `dapper.logLevel` (debug|info|warn|error) - Logging verbosity.
- `dapper.logToConsole` (boolean) - Also write logs to the dev tools console.
- `dapper.debugger.logFile` (string) - Persistent log file path for the Python debug session. Supports `${workspaceFolder}`.
- `dapper.debugger.logLevel` (TRACE|DEBUG|INFO|WARNING|ERROR) - Log level for the Python debug session log file. This is passed to the launcher as `DAPPER_LOG_LEVEL`.
- `dapper.python.installMode` (auto|wheel|pypi|workspace) - How the Python package is installed.
- `dapper.python.baseInterpreter` (string) - Absolute path to a base Python interpreter.
- `dapper.python.forceReinstall` (boolean) - Force reinstall the Python package on activation.
- `dapper.python.expectedVersion` (string) - Override the version of the dapper backend to expect.

## Troubleshooting

- If the extension fails to start or debug sessions do not initialize, check the Developer Tools console (Help → Toggle Developer Tools). Set `dapper.logLevel` to `debug` and `dapper.logToConsole` to `true` to get additional details.
- Use the `Dapper: Show Variable Inspector` to view variable data; sometimes frame eval may fail if the target process is in a restricted state (e.g., in C extensions).

## Contributing

Contributions are welcome! See the top-level repo README for development setup and contribution guidelines.

---

For more detailed documentation and the developer guide, see the repository docs under `/doc/` and the `examples/` folder for sample programs and workflows.
