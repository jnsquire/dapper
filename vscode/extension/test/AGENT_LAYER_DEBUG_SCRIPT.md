# Agent-Layer Debug Script

This guide is for exercising the Dapper language model tools against a real Python debug session from the agent layer.

The goal is not to unit test internals. The goal is to confirm that an agent can reliably drive the end-to-end debugging workflow with the public tools.

## Fixture Workspace

Use the prepared sources under:

`vscode/extension/test/fixtures/agent_debug_workspace`

Important: the active workspace in this repository is the repo root, so prefer explicit `file`, `module`, `cwd`, and `moduleSearchPaths` inputs when using `dapper_launch`.

## Files To Use

- `vscode/extension/test/fixtures/agent_debug_workspace/app.py`
- `vscode/extension/test/fixtures/agent_debug_workspace/src/agent_fixture_pkg/__main__.py`
- `vscode/extension/test/fixtures/agent_debug_workspace/src/agent_fixture_pkg/scenario.py`
- `vscode/extension/test/fixtures/agent_debug_workspace/README.md`

## Breakpoint Discovery Rule

Before calling `dapper_breakpoints`, read the relevant source file and find the exact line number for the marker string.

Markers used by this fixture:

- `BREAKPOINT: order-summary`
- `BREAKPOINT: main-after-summary`
- `BREAKPOINT: inventory-summary`
- `BREAKPOINT: focus-decision`
- `BREAKPOINT: module-report`

## Tool Coverage Goals

A successful run should exercise all of these tools:

- `dapper_launch`
- `dapper_session_info`
- `dapper_breakpoints`
- `dapper_state`
- `dapper_evaluate`
- `dapper_variable`
- `dapper_execution`

## Scenario 1: File Launch Workflow

### 1. Prepare line numbers

Read `vscode/extension/test/fixtures/agent_debug_workspace/app.py` and record the line numbers for:

- `BREAKPOINT: order-summary`
- `BREAKPOINT: main-after-summary`

### 2. Clear stale breakpoints

Call `dapper_breakpoints`:

```json
{
  "action": "clear",
  "file": "vscode/extension/test/fixtures/agent_debug_workspace/app.py"
}
```

### 3. Add the two file breakpoints

Call `dapper_breakpoints` with the line numbers you found:

```json
{
  "action": "add",
  "file": "vscode/extension/test/fixtures/agent_debug_workspace/app.py",
  "lines": [ORDER_SUMMARY_LINE, MAIN_AFTER_SUMMARY_LINE]
}
```

### 4. Launch the file target

Call `dapper_launch`:

```json
{
  "target": {
    "file": "vscode/extension/test/fixtures/agent_debug_workspace/app.py"
  },
  "cwd": "vscode/extension/test/fixtures/agent_debug_workspace",
  "stopOnEntry": false,
  "justMyCode": true,
  "waitForStop": true
}
```

Expected outcome:

- a `sessionId` is returned
- `resolvedTarget.kind == "file"`
- `stopped == true`
- the initial stop is at `BREAKPOINT: order-summary`

### 5. Check session metadata

Call `dapper_session_info` with the returned `sessionId`.

Confirm:

- exactly one relevant Dapper session is reported
- the session program points at `app.py`
- the session state is `stopped`
- `breakpointRegistrationComplete == true`
- `readyToContinue == true`
- the accepted breakpoint count is at least `1`

### 6. Read a snapshot at the first stop

Call `dapper_state`:

```json
{
  "sessionId": "SESSION_ID",
  "mode": "snapshot",
  "depth": 5
}
```

Confirm the snapshot indicates the stop is in `app.py` at the order-summary breakpoint.

### 7. Evaluate local values at the first stop

Call `dapper_evaluate`.

Suggested expressions:

```json
{
  "sessionId": "SESSION_ID",
  "expressions": [
    "subtotal",
    "discount_rate",
    "discounted_subtotal",
    "tax",
    "total",
    "status"
  ]
}
```

Expected values:

- `subtotal == 19.25`
- `discount_rate == 0.1`
- `discounted_subtotal == 17.32`
- `tax == 1.39`
- `total == 18.71`
- `status == "clear"`

Note: `dapper_evaluate` executes code in the debuggee and may ask for confirmation.

### 8. Inspect a structured value

Call `dapper_variable`:

```json
{
  "sessionId": "SESSION_ID",
  "expression": "self.lines",
  "depth": 3,
  "maxItems": 10
}
```

Confirm the result expands into three `OrderLine` entries with the expected SKUs and numeric values.

### 9. Continue to the second breakpoint with a report

Call `dapper_execution`:

```json
{
  "sessionId": "SESSION_ID",
  "action": "continue",
  "report": true
}
```

Confirm:

- `stopped == true`
- the new location is `BREAKPOINT: main-after-summary`
- the diff shows movement from the first stop to the second

### 10. Re-check state at the second stop

Call `dapper_state` again with `mode: "snapshot"`.

Confirm the current frame now includes:

- `summary`
- `threshold`
- `needs_follow_up`

### 11. Evaluate post-summary expressions

Call `dapper_evaluate`:

```json
{
  "sessionId": "SESSION_ID",
  "expressions": [
    "summary['total']",
    "summary['status']",
    "needs_follow_up",
    "threshold"
  ]
}
```

Expected values:

- `summary['total'] == 18.71`
- `summary['status'] == "clear"`
- `needs_follow_up is True`
- `threshold == 15`

### 12. Terminate the session

Call `dapper_execution`:

```json
{
  "sessionId": "SESSION_ID",
  "action": "terminate"
}
```

Success criteria for Scenario 1:

- breakpoints were added successfully
- launch stopped at the expected breakpoint
- state/evaluate/variable tools all returned coherent values
- execution control reached the second breakpoint
- termination succeeded cleanly

## Scenario 2: Module Launch Workflow

### 1. Prepare line numbers

Read both source files and record the line numbers for:

- `BREAKPOINT: inventory-summary` in `vscode/extension/test/fixtures/agent_debug_workspace/src/agent_fixture_pkg/scenario.py`
- `BREAKPOINT: focus-decision` in `vscode/extension/test/fixtures/agent_debug_workspace/src/agent_fixture_pkg/scenario.py`
- `BREAKPOINT: module-report` in `vscode/extension/test/fixtures/agent_debug_workspace/src/agent_fixture_pkg/__main__.py`

### 2. Clear stale breakpoints

Call `dapper_breakpoints` for both files:

```json
{
  "action": "clear",
  "file": "vscode/extension/test/fixtures/agent_debug_workspace/src/agent_fixture_pkg/scenario.py"
}
```

```json
{
  "action": "clear",
  "file": "vscode/extension/test/fixtures/agent_debug_workspace/src/agent_fixture_pkg/__main__.py"
}
```

### 3. Add module breakpoints

Call `dapper_breakpoints` for the scenario file and the module entrypoint:

```json
{
  "action": "add",
  "file": "vscode/extension/test/fixtures/agent_debug_workspace/src/agent_fixture_pkg/scenario.py",
  "lines": [INVENTORY_SUMMARY_LINE, FOCUS_DECISION_LINE]
}
```

```json
{
  "action": "add",
  "file": "vscode/extension/test/fixtures/agent_debug_workspace/src/agent_fixture_pkg/__main__.py",
  "lines": [MODULE_REPORT_LINE]
}
```

### 4. Launch the module target

Call `dapper_launch`:

```json
{
  "target": {
    "module": "agent_fixture_pkg"
  },
  "cwd": "vscode/extension/test/fixtures/agent_debug_workspace",
  "moduleSearchPaths": [
    "vscode/extension/test/fixtures/agent_debug_workspace/src"
  ],
  "stopOnEntry": false,
  "justMyCode": true,
  "waitForStop": true
}
```

Expected outcome:

- `resolvedTarget.kind == "module"`
- `resolvedTarget.value == "agent_fixture_pkg"`
- execution stops first at `BREAKPOINT: inventory-summary`
- `readyToContinue == true`

### 5. Snapshot the first module stop

Call `dapper_state` with `mode: "snapshot"`.

Confirm the stop location is inside `scenario.py` at the inventory-summary breakpoint.

### 6. Evaluate first-stop expressions

Call `dapper_evaluate`:

```json
{
  "sessionId": "SESSION_ID",
  "expressions": [
    "total_count",
    "average_count",
    "descriptor"
  ]
}
```

Expected values:

- `total_count == 10`
- `average_count == 3.3333333333333335`
- `descriptor == "items=3 total=10 average=3.33"`

### 7. Inspect the inventory payload

Call `dapper_variable`:

```json
{
  "sessionId": "SESSION_ID",
  "expression": "items",
  "depth": 3,
  "maxItems": 10
}
```

Confirm the list contains three dictionaries for `alpha`, `beta`, and `gamma`.

### 8. Continue to the focus decision

Call `dapper_execution` with `action: "continue"` and `report: true`.

Confirm the next stop is `BREAKPOINT: focus-decision`.

### 9. Evaluate focus logic

Call `dapper_evaluate`:

```json
{
  "sessionId": "SESSION_ID",
  "expressions": [
    "counts",
    "focus"
  ]
}
```

Expected values:

- `counts == [3, 5, 2]`
- `focus == "restock"`

### 10. Continue to the module report breakpoint

Call `dapper_execution` with `action: "continue"` and `report: true`.

Confirm the stop is now at `BREAKPOINT: module-report` in `__main__.py`.

### 11. Inspect the final report object

Call `dapper_variable`:

```json
{
  "sessionId": "SESSION_ID",
  "expression": "report",
  "depth": 3,
  "maxItems": 10
}
```

Confirm:

- `report.focus == "restock"`
- `report.summary_line == "restock:items=3 total=10 average=3.33"`

### 12. Terminate the session

Call `dapper_execution`:

```json
{
  "sessionId": "SESSION_ID",
  "action": "terminate"
}
```

Success criteria for Scenario 2:

- module launch resolves imports through `moduleSearchPaths`
- breakpoints hit in the expected order across two files
- evaluate and variable inspection agree on the same data
- execution control advances the program deterministically

## Optional Scenario 3: Named Launch Configs

The fixture workspace also contains `vscode/extension/test/fixtures/agent_debug_workspace/.vscode/launch.template.json` with:

- `Agent Fixture: File`
- `Agent Fixture: Module`

Copy this template to `.vscode/launch.json` only if the fixture folder itself is opened as a VS Code workspace folder. In the current repo-root workspace, explicit `file` and `module` targets are the more reliable path.

## Failure Checklist

If a scenario fails, capture which layer broke:

- breakpoint add/list mismatch
- launch failed before session creation
- session launched but never stopped
- stopped in the wrong file or line
- snapshot missing expected locals
- evaluate or variable inspection disagrees with the snapshot
- continue did not stop at the next prepared breakpoint
- terminate failed or left a stale session
