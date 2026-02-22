# Troubleshooting

This page consolidates common issues across all areas of Dapper. For frame evaluation-specific troubleshooting, see the [Frame Evaluation guide](frame-eval.md#troubleshooting).

## Connection Issues

**Can't connect to the adapter on port 4711:**

- Verify the adapter is running: `python -m dapper.adapter --port 4711`
- Check that no firewall or port-binding rule is blocking the port.
- Confirm that `"debugServer": 4711` in your `launch.json` matches the port the adapter was started with.
- Look for a `[Errno 98] Address already in use` error — another process may already be using the port. Try a different port or kill the existing process.

!!! note "TODO"
    Document error messages emitted to the adapter log and how to read them.

## Breakpoints Not Hitting

- Ensure the file path in VS Code exactly matches the path the Python interpreter sees. Symlinks and relative paths can cause mismatches.
- Check that the file was not reloaded after the breakpoint was set (e.g. hot-reload or importlib reimport). Re-set the breakpoint after reloading.
- If using `justMyCode: true` (the default), breakpoints inside `site-packages` or the standard library will be skipped.
- For async code, breakpoints inside coroutines require that the event loop is running. Refer to the [Async Debugging Guide](../guides/async-debugging.md).

!!! note "TODO"
    Add step-by-step diagnosis flow for the "grey breakpoint" (unverified) state.

## Variable Display Issues

- Complex objects (custom `__repr__`, very deeply nested structures) may display as `<…>` or truncated. Use the Debug Console to evaluate sub-expressions manually.
- Variables inside comprehensions or generator frames may not be accessible; this is a known CPython limitation.
- Setting a variable to a new value via the Variables panel requires the adapter to support `setVariable`. Check that `"supportsSetVariable": true` appears in the adapter capabilities.

!!! note "TODO"
    Document the variable presentation pipeline and how to extend it.

## Frame Evaluation Issues

Frame evaluation is an optional subsystem that significantly reduces tracing overhead. If you have enabled `"frameEval": true` and are seeing problems:

- See the dedicated [Frame Evaluation — Troubleshooting](frame-eval.md#troubleshooting) section for the full diagnosis guide and health-check script.
- As a quick fix, disable frame evaluation by setting `"frameEval": false` in your `launch.json` to fall back to standard tracing.

## Performance Issues

- High CPU usage during a long debugging session is usually caused by the sys.settrace overhead. Enable frame evaluation (`"frameEval": true`) to reduce this.
- Large numbers of breakpoints (>100 per file) degrade frame evaluation efficiency. Consider using conditional breakpoints or logpoints instead.
- Memory usage grows if the breakpoint cache is not bounded. Set `max_cache_size` in `frameEvalConfig` to limit it.

!!! note "TODO"
    Add guidance on profiling the adapter itself and reporting performance regressions.

## VS Code Extension Issues

- If the Dapper extension fails to activate, check the **Output** panel → **Dapper** channel for error messages.
- After updating the extension, reload VS Code (`Ctrl+Shift+P` → **Developer: Reload Window**).
- For extension development issues, see [VS Code Extension Development](../getting-started/using-vscode.md).

!!! note "TODO"
    Document the extension activation sequence and common activation failures.

## Getting Help

- **Open an issue**: If you've found a bug or can't resolve an issue with this guide, open a GitHub issue with the adapter log output and a minimal reproduction.
- **Check the logs**: Start the adapter with `--log-level DEBUG` and attach the log file to your report.
- **Review the architecture docs**: The [Architecture Overview](../architecture/overview.md) may help you understand where a failure is occurring.
