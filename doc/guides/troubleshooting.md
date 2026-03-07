# Troubleshooting

This page consolidates common issues across all areas of Dapper. For frame evaluation-specific troubleshooting, see the [Frame Evaluation guide](frame-eval.md#troubleshooting).

## Connection Issues

**Can't connect to the adapter on port 4711:**

- Verify the adapter is running: `python -m dapper.adapter --port 4711`
- Check that no firewall or port-binding rule is blocking the port.
- Confirm that `"debugServer": 4711` in your `launch.json` matches the port the adapter was started with.
- Look for a `[Errno 98] Address already in use` error — another process may already be using the port. Try a different port or kill the existing process.

If connection setup still fails, start the adapter with `--log-level DEBUG` and review the adapter output for bind, handshake, or launch-time errors.

## Attach By PID Issues

- `processId` attach only works for live **CPython 3.14** targets. The local helper interpreter must also be CPython 3.14, and pre-release builds must match exactly.
- If Dapper reports that `sys.remote_exec()` is unavailable, point the extension at a CPython 3.14 interpreter with `pythonPath` or `venvPath` and verify that the target process is also CPython 3.14.
- If Dapper reports that remote debugging is disabled, restart the target without `PYTHON_DISABLE_REMOTE_DEBUG=1`, without `-X disable_remote_debug`, and with a CPython build that was not compiled with `--without-remote-debug`.
- If Dapper reports missing privileges, re-run VS Code or the attach helper with enough rights to inspect the target process. On Linux this may require matching ownership plus `CAP_SYS_PTRACE` or a relaxed `/proc/sys/kernel/yama/ptrace_scope`; macOS often requires `sudo`; Windows often requires Administrator rights or `SeDebugPrivilege`.
- A bootstrap timeout means the target did not execute the injected script quickly enough. The most common causes are blocked main-thread execution, long-running native code, or an attach attempt against a process that cannot be remotely debugged.
- `sys.remote_exec()` is asynchronous. The helper returns before the remote script runs, so deleting or moving the bootstrap script too early can break attach flows in custom tooling.

## Breakpoints Not Hitting

- Ensure the file path in VS Code exactly matches the path the Python interpreter sees. Symlinks and relative paths can cause mismatches.
- Check that the file was not reloaded after the breakpoint was set (e.g. hot-reload or importlib reimport). Re-set the breakpoint after reloading.
- If using `justMyCode: true` (the default), breakpoints inside `site-packages` or the standard library will be skipped.
- For async code, breakpoints inside coroutines require that the event loop is running. Refer to the [Async Debugging Guide](../guides/async-debugging.md).

If VS Code shows an unverified breakpoint, confirm that the source path, interpreter, and workspace folder all match the program being launched.

## Variable Display Issues

- Complex objects (custom `__repr__`, very deeply nested structures) may display as `<…>` or truncated. Use the Debug Console to evaluate sub-expressions manually.
- Variables inside comprehensions or generator frames may not be accessible; this is a known CPython limitation.
- Setting a variable to a new value via the Variables panel requires the adapter to support `setVariable`. Check that `"supportsSetVariable": true` appears in the adapter capabilities.

For details on display formatting and presentation hints, see the [Variable Presentation guide](variable-presentation.md).

## Frame Evaluation Issues

Frame evaluation is an optional subsystem that significantly reduces tracing overhead. If you have enabled `"frameEval": true` and are seeing problems:

- See the dedicated [Frame Evaluation — Troubleshooting](frame-eval.md#troubleshooting) section for the full diagnosis guide and health-check script.
- As a quick fix, disable frame evaluation by setting `"frameEval": false` in your `launch.json` to fall back to standard tracing.

## Performance Issues

- High CPU usage during a long debugging session is usually caused by the sys.settrace overhead. Enable frame evaluation (`"frameEval": true`) to reduce this.
- Large numbers of breakpoints (>100 per file) degrade frame evaluation efficiency. Consider using conditional breakpoints or logpoints instead.
- Memory usage grows if the breakpoint cache is not bounded. Set `max_cache_size` in `frameEvalConfig` to limit it.

When reporting performance regressions, include the Python version, launch configuration, and whether frame evaluation or `sys.monitoring` was enabled.

## VS Code Extension Issues

- If the Dapper extension fails to activate, check the **Output** panel → **Dapper** channel for error messages.
- After updating the extension, reload VS Code (`Ctrl+Shift+P` → **Developer: Reload Window**).
- For extension development issues, see [VS Code Extension Development](../getting-started/using-vscode.md).

If activation still fails, rebuild the extension and confirm that the selected Python environment matches the environment expected by the extension.

## Getting Help

- **Open an issue**: If you've found a bug or can't resolve an issue with this guide, open a GitHub issue with the adapter log output and a minimal reproduction.
- **Check the logs**: Start the adapter with `--log-level DEBUG` and attach the log file to your report.
- **Review the architecture docs**: The [Architecture Overview](../architecture/overview.md) may help you understand where a failure is occurring.
