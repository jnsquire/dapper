# VS Code Extension Development

The VS Code extension source code is located in `vscode/extension`. It is a separate npm project that must be built before running the Python unit tests that depend on it.

## Setup

1. **Navigate to the extension directory:**
   ```bash
   cd vscode/extension
   ```

2. **Install dependencies:**
   ```bash
   npm install
   ```

3. **Build the extension:**
   ```bash
   npm run build
   ```

   For development with auto-rebuild on changes:
   ```bash
   npm run watch
   ```

4. **Package and reinstall the VSIX when testing the installed extension:**
   ```bash
   npm run package
  code --install-extension dist/dapper-debugger-0.9.3.vsix --force
   ```

   Notes:
   - The package script writes the VSIX to `vscode/extension/dist/`.
   - On WSL or remote setups, `code` may resolve to the VS Code remote CLI.
     Use `command -v code` if you need the exact executable path.
   - Reinstalling the VSIX updates the installed extension, but the active
     extension host may still be running older code until the window reloads.
   - After reinstalling, run **Developer: Reload Window** before reproducing
     extension-host issues.

## Running the Extension

1. Open the `vscode/extension` folder in VS Code.
2. Press `F5` to launch the Extension Development Host.

The Extension Development Host opens a new VS Code window with the extension loaded. You can set breakpoints in the extension TypeScript source and debug it like any other Node.js project.

When you are debugging the packaged extension rather than the Extension
Development Host, prefer the `package -> code --install-extension --force ->
Developer: Reload Window` loop above. A rebuild alone does not update the code
running in the existing extension host.

## For Agents

Dapper's LM tools are declared in `vscode/extension/package.json` and implemented under
`vscode/extension/src/agent/tools/`. The schema is intentionally compact; the notes below capture
the runtime behavior that is easy to miss.

The public tool surface currently includes `dapper_cli`, `dapper_launch`, `dapper_state`,
`dapper_execution`, `dapper_evaluate`, `dapper_breakpoints`, `dapper_variable`, and
`dapper_session_info`.

### CLI Wrapper

- `dapper_cli` is the Phase 1 command-style wrapper over the existing tool set.
- Phase 1 supports semicolon-separated command chaining in a single request.
- Supported commands are `help`/`h`, `run`, `continue`/`c`, `next`/`n`, `step`/`s`, `finish`,
  `quit`/`q`, `break`/`b`, `clear`, `disable`, `enable`, `print`/`p`, `where`/`bt`, `locals`,
  `globals`, `list`/`l`, `up`, `down`, and `frame`.
- `help` returns a pdb-style quick-start plus a full summary of the public Dapper LM tools and their top-level arguments.
- Chained command execution stops on the first parse or runtime error and returns partial results for commands that already completed.
- When more than one Dapper session is active, `dapper_cli` requires an explicit `sessionId`
  rather than silently picking one.
- Frame navigation updates the wrapper-managed `frameIndex`, and later `print`, `locals`, and
  `globals` calls use that selected frame.
- `break` first resolves explicit file paths, then unique Python filename stems in the workspace,
  then function names found in the selected session's current call stack.

### Session Resolution

- Most tools accept an optional `sessionId`.
- When `sessionId` is omitted, the tool resolves to the active Dapper debug session.
- Tools do not fall back to arbitrary non-Dapper sessions.

### Snapshot and Journal Semantics

- `dapper_state` in `snapshot` mode reads through `StateJournal.getSnapshot()`.
- On a stop event, the journal first stores a placeholder snapshot with empty `callStack`,
  `locals`, and `globals`. A later custom request fills in the real data.
- If that request fails, `StateJournal` keeps the last successful snapshot and records the failure
  in `lastError`.
- `dapper_state` can therefore return cached data or `_adapterError` even when the session is still valid.

### Execution Tools

- `dapper_execution` with `report: true` combines a DAP step request, a wait for a new stopped
  event, and a diff of locals, location, and output since the previous checkpoint.
- `stopped: false` means the session did not report a new stop before the timeout or it terminated.
- `dapper_execution` without `report: true` returns acknowledgement-oriented status strings
  (`running`, `pausing`, `restarting`, `terminating`) rather than waiting for all downstream events
  to settle.

### Evaluation and Inspection

- `dapper_evaluate` and `dapper_variable` both execute expressions in the debuggee process.
- They should be treated as potentially side-effecting operations.
- `dapper_evaluate` normalizes single-expression and multi-expression inputs into the same batch
  request format.
- `dapper_variable` recursively expands dicts, lists, tuples, and public object attributes;
  it is better suited to structural inspection than `dapper_evaluate`.

### Breakpoint Tools

- `dapper_breakpoints` accepts `list`, `add`, `remove`, `clear`, `disable`, and `enable`.
- On `add`, the extension updates the VS Code breakpoint registry and also sends a direct
  `setBreakpoints` request to the adapter so verification and registration happen immediately.
- `remove`, `clear`, `disable`, and `enable` now also resync the adapter with the enabled source
  breakpoint set for the affected file.
- On `list`, it always reports the VS Code breakpoint list. If a Dapper session is active, it also
  re-queries adapter verification state and merges a `verified` field into the result when the
  adapter state is definitive.
- If the adapter reports `verified: false` without a rejection message, the tool now reports
  `verificationState: pending` instead of a hard `verified: false`.
- If no active Dapper session is available, breakpoint data still returns, but `verified` may be
  missing.

### Session Info Caveat

- `dapper_session_info` can enumerate tracked journals, but only the active VS Code session has a
  live `DebugSession` object.
- Non-active sessions may therefore appear with `state: unknown` and a minimal configuration object.

### Fixture Launch Configs

- Keep nested fixture launch examples as `.vscode/launch.template.json` files rather than active
  `.vscode/launch.json` files.
- This avoids noisy schema diagnostics in the repo workspace for custom Dapper-only fields such as
  `moduleSearchPaths` or for the unregistered debug type outside the extension host.

### Child Auto-Attach Transport

- `subprocessAutoAttach: true` allocates one shared child IPC listener per parent debug session in
  the extension rather than one listener per child.
- Rewritten child launchers inherit that shared port with `--subprocess-ipc-port` and connect back
  to it after startup.
- The first child-side frame on that socket is an internal `dapper/sessionHello` message carrying
  the logical child `sessionId`.
- `ChildSessionManager` correlates the socket with the pending `dapper/childProcess` event by that
  `sessionId` before constructing the child `DapperDebugSession`.
- The `ipcPort` field exposed in `dapper/childProcess` is therefore the shared listener port for the
  parent session, not a child-unique port.

## See Also

- [Setup](setup.md)
