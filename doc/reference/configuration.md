# Configuration Reference

This page documents all launch configuration options recognised by Dapper's debug adapter.

These options are passed via VS Code `launch.json` (under the `"configurations"` array) or programmatically to the adapter as the `arguments` object of the `launch` or `attach` DAP request.

## Core Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `program` | string | required | Path to the Python script to debug. Supports `${workspaceFolder}` and other VS Code variables. |
| `args` | list[str] | `[]` | Arguments to pass to the debugged program, available as `sys.argv[1:]`. |
| `cwd` | string | workspace root | Working directory for the debugged process. |
| `env` | object | `{}` | Environment variables to set in the debugged process. Merged with the current environment. |
| `stopOnEntry` | bool | `false` | Pause execution at the first statement of the program entry point. |
| `debugServer` | int | — | Port number of a running Dapper adapter (attach mode). When set, VS Code attaches to an already-running adapter instead of launching one. |
| `port` | int | `4711` | Port for the adapter to listen on when launching a new adapter process. |
| `justMyCode` | bool | `true` | Skip frames inside `site-packages` and the standard library when stepping and displaying the call stack. |
| `redirectOutput` | bool | `true` | Capture stdout/stderr from the debugged process and display them in the Debug Console. |
| `logToFile` | bool | `false` | Write the adapter log to a file for troubleshooting. The log path is printed to stderr on startup. |
| `autoAttachChildProcesses` | bool | `false` | Automatically attach to child processes spawned by the debugged program. See `dapper/childProcess` in the [DAP extensions reference](dap-extensions.md). |

## Frame Evaluation Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `frameEval` | bool | `false` | Enable the frame evaluation subsystem for reduced tracing overhead (60-80% improvement in typical workloads). |
| `frameEvalConfig` | object | — | Advanced frame evaluation configuration. See sub-keys below. |

### `frameEvalConfig` Sub-keys

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `selective_tracing` | bool | `true` | Only trace frames that contain active breakpoints. |
| `bytecode_optimization` | bool | `true` | Rewrite bytecode to embed fast-path breakpoint checks. Disable for compatibility with unusual code patterns. |
| `cache_enabled` | bool | `true` | Cache code objects and breakpoint locations to avoid redundant analysis. |
| `performance_monitoring` | bool | `true` | Collect performance statistics accessible via `get_integration_statistics()`. |
| `fallback_on_error` | bool | `true` | Automatically fall back to standard `sys.settrace` tracing if frame evaluation raises an error. |
| `max_cache_size` | int | `1000` | Maximum number of entries in the frame evaluation cache. |
| `cache_ttl` | int | `300` | Time-to-live (seconds) for cache entries. `0` disables TTL-based eviction. |
| `trace_overhead_threshold` | float | `0.1` | Fraction of trace-call overhead (0.0–1.0) above which the system logs a warning. |

For a full usage guide and troubleshooting steps, see the [Frame Evaluation Guide](../guides/frame-eval.md).

## Example launch.json

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Python: Debug with Frame Eval",
            "type": "python",
            "request": "launch",
            "program": "${workspaceFolder}/main.py",
            "args": ["--config", "dev.toml"],
            "cwd": "${workspaceFolder}",
            "env": { "MY_ENV_VAR": "value" },
            "stopOnEntry": false,
            "justMyCode": true,
            "redirectOutput": true,
            "frameEval": true,
            "frameEvalConfig": {
                "selective_tracing": true,
                "bytecode_optimization": true,
                "cache_enabled": true,
                "performance_monitoring": false
            }
        }
    ]
}
```

## See Also

- [Using VS Code](../getting-started/using-vscode.md)
- [Frame Evaluation Guide](../guides/frame-eval.md)
