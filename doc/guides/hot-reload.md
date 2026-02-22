# Hot Reload (reference)

This page documents Dapper's hot reload support during a paused debug session.

Current status: hot reload is implemented for in-process Dapper debug sessions. External-process support is planned.

## What it does

When the debugger is stopped, Dapper can reload a Python module from disk without restarting the session. The reload flow:

- resolves the loaded module by source path
- runs `importlib.reload(...)`
- refreshes breakpoint state for the file
- emits `loadedSource` (`reason: "changed"`)
- emits `dapper/hotReloadResult` with counters and warnings

In in-process sessions, Dapper also attempts to rebind matching function references in live frame locals so resumed execution can pick up updated code more quickly.

## How to use it in VS Code

### Manual reload

- Command Palette: `Dapper: Hot Reload Current File`
- Default keybinding:
  - Linux/Windows: `Ctrl+Alt+R`
  - macOS: `Cmd+Alt+R`

### Auto on save

Set this extension setting:

- `dapper.hotReload.autoOnSave` (default: `true`)

When enabled, saving a Python file auto-triggers hot reload only if all of the following are true:

- the active debug session is Dapper
- the session is currently stopped
- the saved file belongs to that session's loaded sources

## DAP extension surface

### Capability

- `supportsHotReload: true`

### Request

- `dapper/hotReload`
- Arguments:
  - `source.path` (required)
  - `options` (optional)

### Response body

Successful responses can include:

- `reloadedModule`
- `reloadedPath`
- `reboundFrames`
- `updatedFrameCodes`
- `patchedInstances`
- `warnings`

### Event

- `dapper/hotReloadResult`
- Includes module/path, timing, frame counters, and warnings.

## Supported options

`dapper/hotReload` accepts optional `options`:

- `invalidatePycache` (default: `true`)
- `updateFrameCode` (default: `true`; only effective on compatible runtimes/frames)
- `rebindFrameLocals` (protocol-defined; currently not runtime-configurable and may be ignored)
- `patchClassInstances` (protocol-defined, experimental; currently not enabled in runtime behavior)

## Safety checks and limitations

- Hot reload requires a stopped debugger.
- Current runtime support is in-process sessions; external-process support is not available yet.
- Non-Python files are rejected.
- C-extension modules (`.so`, `.pyd`, etc.) are rejected.
- Functions using closures are skipped for rebinding and reported via warnings.
- `frame.f_code` updates are attempted only when structural compatibility checks pass.
- `importlib.reload` re-executes module top-level code; side effects can run again.

## Telemetry and diagnostics

Frame-eval telemetry tracks hot reload attempt outcomes:

- `HOT_RELOAD_SUCCEEDED`
- `HOT_RELOAD_FAILED`

Use `dapper._frame_eval.telemetry.get_frame_eval_telemetry()` to inspect counters and recent events.

## Troubleshooting

If a reload request fails:

- Ensure execution is paused at a breakpoint.
- Ensure the file is part of the currently loaded debug session.
- Check response/event warnings for compatibility skips.
- For C-extension modules, restart-based workflows are required.

See also: [Frame-eval telemetry reference](../reference/telemetry.md).
