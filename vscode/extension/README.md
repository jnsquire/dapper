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
code --install-extension dist/dapper-debugger-0.9.0.vsix --force
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
3. Start debugging with **F5** or the `Dapper: Start Debugging` command.

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
| `subprocessAutoAttach` | boolean | Auto-attach supported Python child processes. |

## Commands

- `Dapper: Open Launch Configuration Wizard` - Open the step-by-step launch configuration wizard.
- `Dapper: Start Debugging` - Start debugging with the current configuration.
- `Dapper: Toggle Breakpoint` - Toggles a breakpoint at the current cursor.
- `Dapper: Show Variable Inspector` - Opens the variable inspector view for the active debug session.
- `Dapper: Configure Settings` - Legacy alias for opening the launch configuration wizard.
- `Dapper: Add Saved Debug Configuration to launch.json` - Save and insert a configuration.
- `Dapper: Start Debugging with Saved Config` - Start debugging using a saved configuration.

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
