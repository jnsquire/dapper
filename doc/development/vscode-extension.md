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

## Running the Extension

1. Open the `vscode/extension` folder in VS Code.
2. Press `F5` to launch the Extension Development Host.

The Extension Development Host opens a new VS Code window with the extension loaded. You can set breakpoints in the extension TypeScript source and debug it like any other Node.js project.

## For Agents

Dapper's LM tools are declared in `vscode/extension/package.json` and implemented under
`vscode/extension/src/agent/tools/`. The schema is intentionally compact; the notes below capture
the runtime behavior that is easy to miss.

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

- `dapper_breakpoints` accepts `list`, `add`, `remove`, and `clear`.
- On `add`, the extension updates the VS Code breakpoint registry and also sends a direct
  `setBreakpoints` request to the adapter so verification and registration happen immediately.
- On `list`, it always reports the VS Code breakpoint list. If a Dapper session is active, it also
  re-queries adapter verification state and merges a `verified` field into the result.
- If no active Dapper session is available, breakpoint data still returns, but `verified` may be
  missing.

### Session Info Caveat

- `dapper_session_info` can enumerate tracked journals, but only the active VS Code session has a
  live `DebugSession` object.
- Non-active sessions may therefore appear with `state: unknown` and a minimal configuration object.

## See Also

- [Setup](setup.md)
