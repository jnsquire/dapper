# Watchpoints (Data + Expression)

Dapper supports persistent watchpoints through DAP `setDataBreakpoints`.

## What works now

- Variable watchpoints (write-triggered): `frame:<frameId>:var:<name>`
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

- Watchpoints are currently write/value-change oriented (no read-access trigger yet).
- Expression watchpoints are evaluated in the active runtime frame context.
- External/subprocess parity for expression watchpoint delivery is a follow-up item.
