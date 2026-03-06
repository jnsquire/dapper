# Extension Host Launch Harness

This harness exercises the `dapper_launch` tool interface through the VS Code mock layer used by the extension's Vitest suite. It is designed for agent-driven coverage of Dapper launch scenarios without spawning a real debug adapter or real Python process.

## Start Here

If you are the agent extending or running this harness, start in this order:

1. Run `cd /home/jnsquire/dapper/vscode/extension && npm run test:launch-harness`.
2. Read `test/__harness__/launchHarness.ts` to see how the fake extension host is assembled.
3. Read `test/launchTool.test.ts` for the current scenario matrix.
4. Add new cases by configuring the harness, then calling `LaunchTool.invoke(...)`.
5. Keep the harness mock-only: do not spawn the real adapter, Python, or a VS Code window here.

## What The Harness Covers

- active Python editor launch
- workspace-relative file launch
- module launch
- named Dapper config from `launch.json`
- named saved Dapper config from `dapper.debug`
- explicit `pythonPath`
- explicit `venvPath`
- wait-for-stop flow via fake debug events

## Related Agent-Layer Acceptance Assets

For a higher-level workflow that exercises the public Dapper tools against prepared Python sources, see:

- `vscode/extension/test/AGENT_LAYER_DEBUG_SCRIPT.md`
- `vscode/extension/test/fixtures/agent_debug_workspace/README.md`

Those assets are meant for agent-driven end-to-end validation rather than mock-only harness coverage.

## Recommended Pattern For New Cases

Use this structure when adding coverage:

```ts
const harness = createLaunchHarness({ workspaceRoot: tmpRoot });
const registry = new JournalRegistry();
const launchService = new LaunchService(registry);
const launchTool = new LaunchTool(registry, launchService);

harness.setActivePythonFile(path.join(tmpRoot, 'app.py'));
const result = await invokeLaunchTool(launchTool, { target: { currentFile: true } });

expect(result.configuration.program).toContain('app.py');
```

## Harness Controls

- `setActivePythonFile(filePath)`: simulates the active editor in the extension host.
- `setSavedDapperConfig(config)`: injects the saved `dapper.debug` configuration.
- `setLaunchConfigurations(configs)`: injects `launch.json` configurations.
- `setPythonInterpreter(pythonPath)`: changes the interpreter returned by the mocked Python extension.
- `fireStopped(body)`: emits a fake Dapper `stopped` event for `waitForStop` scenarios.
- `fireTerminated(body)`: emits a fake Dapper `terminated` event.

## Ground Rules

- Prefer asserting on the tool result first, then the generated Dapper debug configuration when needed.
- Only extend the shared `vscode` mock when a scenario needs a new host capability.
- If a new scenario needs journal-backed snapshots, create or inject a `StateJournal` explicitly rather than starting a real session.
- Keep filesystem fixtures temporary and local to the test.

## Quick Debugging Tips

- If a test hangs, check whether `waitForStop: true` needs `fireStopped(...)`.
- If a named config fails, inspect `workspace.getConfiguration('launch')` or `workspace.getConfiguration('dapper')` stubs in the harness.
- If interpreter selection looks wrong, inspect the mocked Python extension return value in `setPythonInterpreter(...)`.