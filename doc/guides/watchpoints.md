# Watchpoints (Data + Expression)

Dapper supports persistent watchpoints through DAP `setDataBreakpoints`.

## What works now

- Variable watchpoints (write-triggered): `frame:<frameId>:var:<name>`
- Variable read watchpoints (Python 3.12+):
  `frame:<frameId>:var:<name>` with `accessType: "read"` or `"readWrite"`
- Expression watchpoints (value-change-triggered): `frame:<frameId>:expr:<expression>`
- Conditions and hit conditions on watchpoints (`condition`, `hitCondition`)
- Stop reason emitted as `data breakpoint`

Expression watchpoints are re-evaluated whenever execution stops on a line,
and Dapper breaks when the expression value changes from its previous snapshot.

## Quick example

Set a data breakpoint with an expression payload:

```json
{
  "command": "setDataBreakpoints",
  "arguments": {
    "breakpoints": [
      {
        "dataId": "frame:42:expr:len(queue)",
        "accessType": "write"
      }
    ]
  }
}
```

Set a read watchpoint (Python 3.12+):

```json
{
  "command": "setDataBreakpoints",
  "arguments": {
    "breakpoints": [
      {
        "dataId": "frame:42:var:counter",
        "accessType": "read"
      }
    ]
  }
}
```

## Read-watchpoint behavior matrix

| Python runtime | Requested `accessType` | Effective behavior |
|---|---|---|
| 3.12+ (`sys.monitoring` available) | `write` | Write-triggered watchpoint |
| 3.12+ (`sys.monitoring` available) | `read` | Read-triggered watchpoint (variable-name loads) |
| 3.12+ (`sys.monitoring` available) | `readWrite` | Read + write-triggered watchpoint |
| 3.11 and earlier | `write` | Write-triggered watchpoint |
| 3.11 and earlier | `read` | Graceful fallback to write-triggered semantics |
| 3.11 and earlier | `readWrite` | Graceful fallback to write-triggered semantics |

## Strict expression watch policy

By default, expression watchpoints run in **permissive mode**.

Enable strict mode with launch/attach config:

```json
{
  "strictExpressionWatchPolicy": true
}
```

Or with launcher CLI:

```bash
python -m dapper.launcher.debug_launcher \
  --program app.py \
  --ipc tcp --ipc-host 127.0.0.1 --ipc-port 4711 \
  --strict-expression-watch-policy
```

### Not allowed in strict mode

When strict mode is enabled, expression watchpoints are blocked if they contain
any of the following policy tokens:

- `__`
- `import `
- `import(`
- `open(`
- `exec(`
- `eval(`
- `compile(`
- `globals(`
- `locals(`
- `vars(`
- `os.`
- `sys.`
- `subprocess`
- `socket`

Typical blocked examples in strict mode:

- `x.__class__`
- `open("/tmp/a")`
- `__import__("os")`
- `os.getenv("HOME")`

## Current limitations

- Read watchpoints require Python 3.12+ (`sys.monitoring` backend).
- On Python 3.11 and earlier, `accessType: "read"` / `"readWrite"` is
  accepted but gracefully downgraded to write semantics.
- Read detection is currently limited to variable-name loads (e.g. locals/globals);
  attribute-read precision (`obj.attr`) is not guaranteed yet.
- Expression watchpoints are evaluated in the active runtime frame context.
- External/subprocess parity for expression watchpoint delivery is a follow-up item.
