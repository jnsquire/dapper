# LM Tools

Dapper exposes a small set of public language model tools for launching,
inspecting, and controlling Python debug sessions from agents and other
tool-driven workflows.

This page documents the important runtime behavior that is easy to miss from the
JSON schemas alone.

## Public Tool Surface

The current public tools are:

- `dapper_cli`
- `dapper_python_diagnostics`
- `dapper_python_environment`
- `dapper_python_autofix`
- `dapper_python_format`
- `dapper_python_project_model`
- `dapper_python_rename`
- `dapper_python_symbol`
- `dapper_python_typecheck`
- `dapper_launch`
- `dapper_state`
- `dapper_execution`
- `dapper_evaluate`
- `dapper_breakpoints`
- `dapper_variable`
- `dapper_session_info`

## Common Rules

- Most tools accept an optional `sessionId`.
- When `sessionId` is omitted, Dapper resolves the active Dapper debug session.
- Many Python-oriented tools also accept an optional `searchRootPath` to anchor
  the workspace folder used for tool execution when multiple workspace roots or
  nested projects are present.
- Tools do not fall back to arbitrary non-Dapper sessions.
- Thread routing for `dapper_state` and `dapper_execution` remains controlled by
  the tool input `threadId`; the CLI does not add a separate thread-selector
  grammar.

## dapper_python_environment

`dapper_python_environment` reports the selected Python environment and the
current Ty/Ruff tooling view for the workspace.

Important behavior:

- It is read-only and does not require an active debug session.
- It reports Python interpreter selection, search roots, Ty availability,
  Ruff availability, and Ty/Ruff config-file discovery.
- `searchRootPath` can be used to anchor venv discovery and config discovery to
  a nested project root.

## dapper_python_diagnostics

`dapper_python_diagnostics` reports structured Python diagnostics for the
current workspace or for a selected file set.

Important behavior:

- It is read-only and does not require an active debug session.
- Ruff and Ty diagnostics are normalized into a shared schema with
  file/position, code, message, source, and backend-specific metadata.
- Backend coverage is reported explicitly, so agents can see when one backend
  produced diagnostics and the other was unavailable or failed.
- `files` narrows the backend invocation to selected paths.
- `limit` bounds the number of normalized diagnostics returned while preserving
  the total count and truncation state.

## dapper_python_autofix

`dapper_python_autofix` runs Ruff autofix for the current workspace or for a
selected file set.

Important behavior:

- It is a mutating tool: by default it applies fixable Ruff edits.
- Set `apply: false` to preview the Ruff diff without changing files.
- The result reports whether files changed and returns diff output in preview
  mode.

## dapper_python_format

`dapper_python_format` runs Ruff formatting for the current workspace or for a
selected file set.

Important behavior:

- It is a mutating tool: by default it applies formatting edits.
- Set `apply: false` to preview the Ruff formatting diff without changing
  files.
- The result reports whether files changed and returns diff output in preview
  mode.

## dapper_python_imports

`dapper_python_imports` runs Ruff-backed import hygiene actions for the current
workspace or for a selected file set.

Important behavior:

- It is a mutating tool: by default it applies changes.
- `mode` supports `cleanup`, `organize`, and `all` (default).
- `cleanup` removes unused imports with Ruff's `F401` fix path.
- `organize` runs Ruff's import-sorting path.
- Set `apply: false` to preview the diff without changing files.

## dapper_python_project_model

`dapper_python_project_model` reports a structured Python workspace model for
the current workspace or a selected search root.

Important behavior:

- It is read-only and does not require an active debug session.
- It reports search roots, source roots, test roots, config files, and
  package boundaries using bounded filesystem heuristics.
- It also returns the selected Python interpreter summary from the shared
  environment snapshot so agents can relate the project model to the active
  environment.
- `searchRootPath` can be used to anchor project-model discovery to a nested
  project root.

## dapper_python_typecheck

`dapper_python_typecheck` runs Ty-backed type checking for the current
workspace or for a selected file set.

Important behavior:

- It is read-only and does not require an active debug session.
- It returns only Ty diagnostics, normalized into the same shared schema used
  by `dapper_python_diagnostics`.
- When Ty provides richer semantic context, diagnostics may also include
  `typeInfo` and `diagnosticContext` fields with declared or inferred types,
  notes, related locations, and backend rule metadata.
- `files` narrows the Ty invocation to selected paths.
- `limit` and `offset` support paginating normalized diagnostics while
  preserving the total count and truncation state.
- The result also includes `completionStatus` and `outputBudget` so agents can
  distinguish a fully returned result from a paged, truncated, or failed one.
- When Ty is unavailable, the backend status is reported explicitly instead of
  silently returning an empty success result.

Example request:

```json
{
  "files": ["app.py"],
  "limit": 1,
  "offset": 1,
  "pathFilter": "source"
}
```

Example paged response:

```json
{
  "status": "complete",
  "completionStatus": "partial",
  "limit": 1,
  "offset": 1,
  "totalDiagnostics": 3,
  "outputBudget": {
    "requestedLimit": 1,
    "appliedLimit": 1,
    "requestedOffset": 1,
    "appliedOffset": 1,
    "returnedItems": 1,
    "totalItems": 3,
    "truncated": true,
    "nextOffset": 2
  },
  "diagnostics": [
    {
      "source": "ty",
      "code": "invalid-return-type",
      "message": "Return type does not match returned value: expected `str`, found `Literal[42]`",
      "typeInfo": {
        "declaredType": "str",
        "inferredType": "Literal[42]",
        "symbolKind": "function",
        "source": "ty"
      },
      "diagnosticContext": {
        "summary": "Invalid Return Type",
        "explanation": "Return type does not match returned value: expected `str`, found `Literal[42]`",
        "rule": "invalid-return-type",
        "code": "invalid-return-type"
      }
    }
  ]
}
```

## dapper_python_symbol

`dapper_python_symbol` resolves definition, references, implementations, or
hover information for a symbol occurrence in a Python file.

Important behavior:

- It is read-only and does not require an active debug session.
- It is location-based: provide `file`, `line`, and optionally `column` for an
  existing symbol occurrence.
- It uses VS Code language feature providers, so the actual provider may be Ty,
  Pylance, or another active semantic backend.
- The result reports Ty availability as the preferred semantic backend for the
  workspace, but VS Code does not expose which extension satisfied the request.
- `action` supports `definition`, `references`, `implementations`, and `hover`.
- `limit` and `offset` can page definition, reference, implementation, or hover
  results, and `outputBudget` reports the returned window and next offset.
- Hover results preserve the raw `contents` array and may additionally include
  derived `typeInfo`, `signatures`, and `documentation` fields when the hover
  payload contains enough structure to extract them safely.

Example request:

```json
{
  "action": "hover",
  "file": "examples/sample_programs/advanced_app.py",
  "line": 8,
  "column": 1,
  "limit": 1,
  "offset": 0
}
```

Example paged hover response:

```json
{
  "action": "hover",
  "status": "complete",
  "completionStatus": "partial",
  "count": 1,
  "outputBudget": {
    "requestedLimit": 1,
    "appliedLimit": 1,
    "requestedOffset": 0,
    "appliedOffset": 0,
    "returnedItems": 1,
    "totalItems": 2,
    "truncated": true,
    "nextOffset": 1
  },
  "results": [
    {
      "kind": "hover",
      "contents": [
        "python\n(method) def add_data(\n    self: Self@DataProcessor,\n    category: str,\n    items: list[Any]\n) -> None",
        "Add data to the processor."
      ],
      "typeInfo": {
        "declaredType": "def add_data( self: Self@DataProcessor, category: str, items: list[Any] ) -> None",
        "inferredType": "None",
        "symbolKind": "method",
        "source": "ty"
      },
      "signatures": [
        {
          "label": "def add_data( self: Self@DataProcessor, category: str, items: list[Any] ) -> None",
          "parameters": [
            { "name": "self", "kind": "positional-or-keyword", "type": "Self@DataProcessor", "optional": false },
            { "name": "category", "kind": "positional-or-keyword", "type": "str", "optional": false },
            { "name": "items", "kind": "positional-or-keyword", "type": "list[Any]", "optional": false }
          ],
          "returnType": "None"
        }
      ],
      "documentation": {
        "format": "plaintext",
        "summary": "Add data to the processor.",
        "docstring": "Add data to the processor."
      }
    }
  ]
}
```

## dapper_python_rename

`dapper_python_rename` runs semantic rename for a symbol occurrence in a Python
file.

Important behavior:

- It is a mutating tool: by default it applies the resulting workspace edit.
- Set `apply: false` to preview the rename result without changing files.
- It returns a normalized summary of file edits so agents can inspect the
  rename impact even when applying it.
- The input is location-based: provide `file`, `line` (1-based), and optionally
  `column` (1-based) for the symbol occurrence. `column` may be omitted to
  use the provider's default location resolution.
- It supports an optional `searchRootPath` to anchor workspace folder discovery
  when the workspace has multiple roots or nested projects.
- It uses VS Code language feature providers, so the actual rename provider may
  be Ty, Pylance, or another active semantic backend.
- The result reports Ty availability as the preferred semantic backend for the
  workspace, but VS Code does not expose which extension satisfied the request.

## dapper_cli

`dapper_cli` is a pdb-style command interface over the public LM tools. It
keeps common debugging actions short while preserving the underlying structured
tool semantics.

### Command Model

- Commands can be chained with `;` and run left to right.
- Chained execution stops on the first parse or runtime error.
- Completed commands still return partial results even when a later command
  fails.
- Frame navigation updates a wrapper-managed `frameIndex`, and later `print`,
  `locals`, `globals`, and `inspect` calls use that selected frame.

Supported commands:

- `help` / `h`
- `run`
- `launch`
- `sessions`
- `info`
- `inspect`
- `state`
- `diff`
- `pause`
- `restart`
- `continue` / `c`
- `next` / `n`
- `step` / `s`
- `finish`
- `quit` / `q`
- `break` / `b`
- `breaks`
- `clear`
- `disable`
- `enable`
- `print` / `p`
- `where` / `bt`
- `locals`
- `globals`
- `list` / `l`
- `up`
- `down`
- `frame`

### Launch Commands

`run` is the short form for launching the active Python file and waiting for the
first stop.

`launch` exposes the richer `dapper_launch` surface.

Supported forms:

```text
launch
launch file app.py
launch module package.cli
launch config My Launch Config
```

Supported launch flags:

- `--cwd PATH`
- `--env KEY=VALUE`
- `--path PATH`
- `--python PATH`
- `--venv PATH`
- `--stop-on-entry`
- `--no-stop-on-entry`
- `--just-my-code`
- `--no-just-my-code`
- `--subprocess`
- `--wait`
- `-- ARG...`

Launch rules:

- `launch` with no target uses `target.currentFile = true`.
- Exactly one target form is allowed: implicit current file, `file`, `module`,
  or `config`.
- `run` stays restricted to cases where no Dapper session is already active.
- `launch` may start an additional Dapper session even when another Dapper
  session is already active.
- `--` ends launch-option parsing and passes all remaining tokens through to the
  debuggee as `args`.

Examples:

```text
launch module package.cli --cwd examples --wait -- --help --verbose
launch file app.py --python .venv/bin/python --no-stop-on-entry
```

### Inspection and State Commands

- `sessions` lists tracked Dapper sessions.
- `info [SESSION_ID]` returns metadata for the selected or specified session.
- `inspect` maps to `dapper_variable` and is intended for structured values.
- `state` maps to `dapper_state` with `mode: snapshot`.
- `diff [CHECKPOINT]` maps to `dapper_state` with `mode: diff`.
- `print` remains the focused scalar expression path through `dapper_evaluate`.

### Breakpoint Commands

- `break TARGET` adds a breakpoint.
- `break TARGET if EXPR` creates a conditional breakpoint.
- `break TARGET log MESSAGE` creates a logpoint.
- `breaks` lists breakpoints.
- `breaks FILE` filters to one file.
- `breaks FILE:LINE` filters to one line through the underlying
  `dapper_breakpoints` line filter.

Breakpoint target resolution order:

1. Explicit file path
2. Unique Python filename stem in the workspace
3. Function name in the selected session's current call stack

## dapper_launch

Use `dapper_launch` to start a new Dapper Python debug session for a file,
module, current editor, or named launch configuration.

Important behavior:

- Omit `target` to use the active Python file.
- Provide exactly one target: `currentFile`, `file`, `module`, or `configName`.
- `dapper_launch` prefers an explicit `pythonPath` or `venvPath`, then falls
  back to the configured or discovered workspace environment.
- Dapper may inject itself through `PYTHONPATH` instead of installing into the
  selected workspace interpreter.
- Set `waitForStop: true` when the next tool call needs a paused frame.
- The result now includes `readiness` and `readyToContinue` so callers can tell
  whether breakpoint registration has settled before trying to resume.
- The result also includes `trackedSessionsBeforeLaunch`, `trackedSessions`, and
  `warnings`. Treat a non-empty `warnings` list as a signal to inspect existing
  sessions and terminate stale ones before continuing the investigation.
- When another tracked session already targets the same `program` or `module`,
  `warnings` includes a stronger same-target warning because duplicate repros on
  the same fixture are the easiest way to leave accidental sessions behind.
- When `waitForStop: true` succeeds, `readiness.lifecycleState` typically ends
  up at `stopped` and `readyToContinue` should be `true` unless breakpoint
  registration failed.

## dapper_state

`dapper_state` reads Python debugger state in either snapshot or diff mode.

Important behavior:

- `snapshot` mode returns stop reason, location, call stack, locals, globals,
  and thread state.
- `snapshot` reads through `StateJournal.getSnapshot()`.
- Right after a stop event, the journal may still hold a placeholder snapshot
  with empty `callStack`, `locals`, and `globals` until the follow-up custom
  request completes.
- If that follow-up request fails, Dapper keeps the last successful snapshot and
  may include `_adapterError`.

## dapper_execution

`dapper_execution` controls debug execution.

Important behavior:

- Use `report: true` with `next`, `stepIn`, `stepOut`, or `continue` when you
  want one call to both advance execution and return the next stop plus diff.
- `stopped: false` means the session did not report a new stop before the wait
  ended, or the target thread/session terminated instead.
- Without `report: true`, the tool returns acknowledgement-style statuses such
  as `running`, `pausing`, `restarting`, and `terminating`.
- Use `action: terminate` as the standard cleanup path after an investigative
  launch when you do not intend to keep the session alive.

## dapper_evaluate and dapper_variable

These tools execute expressions in the debuggee process.

Use `dapper_evaluate` for focused scalar expressions and `dapper_variable` for
structured values.

Important behavior:

- Both tools run in the chosen `frameIndex` and can have side effects.
- `dapper_evaluate` accepts either `expression` or `expressions`, but executes
  them as a batch in the selected frame.
- `dapper_variable` expands dicts, lists, tuples, and public object attributes
  to the requested depth.

## dapper_breakpoints

`dapper_breakpoints` manages the VS Code breakpoint set and synchronizes it with
the live adapter when a Dapper session is available.

Important behavior:

- `action: list` reports the current VS Code source breakpoints.
- `action: list` accepts `file` as a file filter and `lines` as an optional
  line filter.
- With an active Dapper session, `list` merges adapter verification state into
  the returned records when that state is definitive.
- `verificationState: pending` means the adapter has not yet resolved whether a
  breakpoint binds to executable code. It is not the same as a rejection.
- `action: add` updates VS Code and also sends `setBreakpoints` immediately so
  the adapter sees the new breakpoint set without waiting for later editor
  events.

## dapper_session_info

`dapper_session_info` is the single public session-inspection tool. It returns
session metadata together with debugger readiness and breakpoint lifecycle
details.

Important behavior:

- It can list tracked sessions even when more than one exists.
- Only the active session is guaranteed to have a live `DebugSession`.
- A targeted lookup with `sessionId` returns the richer single-session payload;
  an untargeted call returns `{ sessions: [...] }` for enumeration.
- The payload includes `lifecycleState`, `breakpointRegistrationComplete`,
  `lastTransition`, `lastError`, `readyToContinue`, and grouped breakpoint
  counts plus details.
- Breakpoint details are split into `breakpoints.details.accepted`,
  `breakpoints.details.pending`, and `breakpoints.details.rejected`.
- `readyToContinue: false` usually means one of three things: breakpoint
  verification is still pending, one or more breakpoints were rejected, or the
  adapter recorded a readiness error.
- Non-active tracked sessions can still be reported from the journal, but they
  may have older snapshot state than the active VS Code session.

## Readiness Troubleshooting

Use `dapper_session_info` first when the debugger appears stalled or reports an
unexpected status.

Common interpretations:

- `lifecycleState: waiting-for-breakpoints` means Dapper is still waiting for
  adapter verification results.
- `breakpoints.rejected > 0` means at least one breakpoint did not bind to
  executable code; check `breakpoints.details.rejected[*].verificationMessage`.
- `lastError` means the journal or adapter recorded a concrete readiness or
  snapshot failure and should be surfaced directly instead of treating the
  session as generically unknown.
- A failed `continue` or `step` with a timeout message usually means
  `configurationDone` never observed breakpoint verification reaching a terminal
  state.

## Recommended Workflow While Paused

1. Call `dapper_session_info` if you need to identify the session.
2. Confirm `readyToContinue` and inspect any pending or rejected breakpoints.
3. Call `dapper_state` with `mode: snapshot` to understand the current stop.
4. Use `dapper_variable` for structured objects and `dapper_evaluate` for
   focused scalar expressions.
5. Use `dapper_execution` with `report: true` to advance execution while
   preserving checkpoint context.
6. Use `dapper_breakpoints` with `action: list` and `action: add/remove/clear`
   when checking whether a breakpoint is present but not yet verified.
7. When the investigation is complete, call `dapper_execution` with
  `action: terminate` unless you intentionally want to keep the session around
  for follow-up work.