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
