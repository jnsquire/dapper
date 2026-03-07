import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as vscode from 'vscode';
import { JournalRegistry } from '../src/agent/stateJournal.js';
import { LaunchService } from '../src/debugAdapter/launchService.js';
import { LaunchTool } from '../src/agent/tools/launch.js';
import { createLaunchHarness, type LaunchHarness } from './__harness__/launchHarness.js';

const vscodeMock = await import('./__mocks__/vscode.mjs');

describe('LaunchTool extension-host harness', () => {
  let tmpRoot: string;
  let registry: JournalRegistry;
  let launchService: LaunchService;
  let launchTool: LaunchTool;
  let harness: LaunchHarness;

  beforeEach(() => {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'dapper-launch-tool-harness-'));
    registry = new JournalRegistry();
    harness = createLaunchHarness({
      workspaceRoot: tmpRoot,
      activeInterpreter: path.join(tmpRoot, '.venv', process.platform === 'win32' ? 'Scripts' : 'bin', process.platform === 'win32' ? 'python.exe' : 'python'),
    });
    launchService = new LaunchService(registry);
    launchTool = new LaunchTool(registry, launchService);
    harness.onSessionStarted((session) => {
      registry.getOrCreate(session);
    });
  });

  afterEach(() => {
    registry.dispose();
    vscodeMock.resetDebugListeners();
    vi.restoreAllMocks();
    fs.rmSync(tmpRoot, { recursive: true, force: true });
  });

  it('launches the active Python file and reports the chosen interpreter', async () => {
    const filePath = path.join(tmpRoot, 'app.py');
    fs.writeFileSync(filePath, 'print("hello")\n');
    harness.setActivePythonFile(filePath);

    const result = await invokeLaunchTool(launchTool, { target: { currentFile: true } });

    expect(result.resolvedTarget).toEqual({ kind: 'file', value: filePath });
    expect(result.configuration.program).toBe(filePath);
    expect(result.pythonPath).toContain('.venv');
  });

  it('preserves an explicit stopOnEntry=false override for current-file launches', async () => {
    const filePath = path.join(tmpRoot, 'no_stop.py');
    fs.writeFileSync(filePath, 'print("hello")\n');
    harness.setActivePythonFile(filePath);

    const result = await invokeLaunchTool(launchTool, {
      target: { currentFile: true },
      stopOnEntry: false,
    });

    expect(result.configuration.stopOnEntry).toBe(false);
    expect(harness.lastStartDebuggingCall?.config.stopOnEntry).toBe(false);
  });

  it('launches a workspace-relative file target through the tool interface', async () => {
    const filePath = path.join(tmpRoot, 'src', 'cli.py');
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    fs.writeFileSync(filePath, 'print("cli")\n');

    const result = await invokeLaunchTool(launchTool, { target: { file: 'src/cli.py' } });

    expect(result.resolvedTarget).toEqual({ kind: 'file', value: filePath });
    expect(result.configuration.program).toBe(filePath);
  });

  it('launches a module target with module search paths and args', async () => {
    const result = await invokeLaunchTool(launchTool, {
      target: { module: 'pkg.main' },
      moduleSearchPaths: ['src'],
      args: ['--flag'],
    });

    expect(result.resolvedTarget).toEqual({ kind: 'module', value: 'pkg.main' });
    expect(result.configuration.module).toBe('pkg.main');
    expect(result.configuration.moduleSearchPaths).toEqual(['src']);
    expect(result.configuration.args).toEqual(['--flag']);
  });

  it('launches a named Dapper configuration from launch.json through the tool interface', async () => {
    const program = path.join(tmpRoot, 'fixture.py');
    fs.writeFileSync(program, 'print("fixture")\n');
    harness.setLaunchConfigurations([
      {
        type: 'dapper',
        request: 'launch',
        name: 'Fixture Launch',
        program,
        cwd: tmpRoot,
      },
    ]);

    const result = await invokeLaunchTool(launchTool, { target: { configName: 'Fixture Launch' } });

    expect(result.resolvedTarget).toEqual({ kind: 'config', value: 'Fixture Launch' });
    expect(result.configuration.program).toBe(program);
  });

  it('launches a saved Dapper configuration from workspace settings through the tool interface', async () => {
    const program = path.join(tmpRoot, 'saved.py');
    fs.writeFileSync(program, 'print("saved")\n');
    harness.setSavedDapperConfig({
      type: 'dapper',
      request: 'launch',
      name: 'Saved Launch',
      program,
      cwd: tmpRoot,
    });

    const result = await invokeLaunchTool(launchTool, { target: { configName: 'Saved Launch' } });

    expect(result.resolvedTarget).toEqual({ kind: 'config', value: 'Saved Launch' });
    expect(result.configuration.program).toBe(program);
  });

  it('preserves an explicit pythonPath over the Python extension interpreter', async () => {
    const filePath = path.join(tmpRoot, 'explicit_python.py');
    const pythonPath = path.join(tmpRoot, 'custom-python');
    fs.writeFileSync(filePath, 'print("explicit")\n');
    fs.writeFileSync(pythonPath, '');

    const result = await invokeLaunchTool(launchTool, {
      target: { file: filePath },
      pythonPath,
    });

    expect(result.pythonPath).toBe(pythonPath);
    expect(result.configuration.program).toBe(filePath);
  });

  it('preserves an explicit venvPath over discovered interpreters', async () => {
    const filePath = path.join(tmpRoot, 'explicit_venv.py');
    const venvPath = path.join(tmpRoot, 'env');
    const pythonPath = path.join(venvPath, process.platform === 'win32' ? 'Scripts' : 'bin', process.platform === 'win32' ? 'python.exe' : 'python');
    fs.mkdirSync(path.dirname(pythonPath), { recursive: true });
    fs.writeFileSync(filePath, 'print("venv")\n');
    fs.writeFileSync(pythonPath, '');

    const result = await invokeLaunchTool(launchTool, {
      target: { file: filePath },
      venvPath,
    });

    expect(result.venvPath).toBe(venvPath);
    expect(result.pythonPath).toBeUndefined();
  });

  it('waits for the first stop and returns a snapshot when requested', async () => {
    const filePath = path.join(tmpRoot, 'stop_me.py');
    fs.writeFileSync(filePath, 'print("stop")\n');

    const invokePromise = invokeLaunchTool(launchTool, {
      target: { file: filePath },
      waitForStop: true,
    });

    await vi.waitFor(() => {
      expect(harness.session).toBeDefined();
    });

    const journal = registry.getOrCreate(harness.sessionForRegistry());
    vi.spyOn(journal, 'getSnapshot').mockResolvedValue({
      checkpoint: 1,
      timestamp: Date.now(),
      stopReason: 'entry',
      threadId: 1,
      location: `${filePath}:1`,
      callStack: [],
      locals: {},
      globals: {},
      stoppedThreads: [1],
      runningThreads: [],
    });

    setTimeout(() => {
      (journal as any)._onStopped({ reason: 'entry', threadId: 1 });
    }, 250);

    const result = await invokePromise;
    expect(result.waitedForStop).toBe(true);
    expect(result.stopped).toBe(true);
    expect(result.snapshot).toMatchObject({ stopReason: 'entry' });
  });

  it('matches the launched session by token when another session with the same name starts first', async () => {
    const filePath = path.join(tmpRoot, 'same_name.py');
    fs.writeFileSync(filePath, 'print("same")\n');

    const originalStartDebugging = vscode.debug.startDebugging as typeof vscode.debug.startDebugging;
    (vscode.debug.startDebugging as unknown) = vi.fn(async (debugFolder, config) => {
      vscodeMock.fireDebugEvent('onDidStartDebugSession', {
        id: 'competing-session',
        type: 'dapper',
        name: String(config.name),
        configuration: {
          ...config,
          __dapperLaunchToken: 'other-launch-token',
        },
        workspaceFolder: debugFolder,
        customRequest: vi.fn(async () => undefined),
      });
      return originalStartDebugging(debugFolder, config);
    }) as typeof vscode.debug.startDebugging;

    const result = await launchService.launch({
      sessionName: 'Shared Launch Name',
      target: { file: filePath },
    });

    expect(result.session.id).toBe(harness.session.id);
    expect(result.session.id).not.toBe('competing-session');
  });

  it('returns promptly when the debug session terminates before the first stop', async () => {
    const filePath = path.join(tmpRoot, 'terminates_early.py');
    fs.writeFileSync(filePath, 'print("bye")\n');

    const invokePromise = invokeLaunchTool(launchTool, {
      target: { file: filePath },
      waitForStop: true,
    });

    await vi.waitFor(() => {
      expect(harness.session).toBeDefined();
    });

    vscodeMock.fireDebugEvent('onDidTerminateDebugSession', harness.sessionForRegistry());

    const result = await invokePromise;
    expect(result.waitedForStop).toBe(true);
    expect(result.stopped).toBe(false);
    expect(result.snapshot).toBeNull();
  });

  it('treats a journal-recorded stop as success even if the custom stopped event is missed', async () => {
    const filePath = path.join(tmpRoot, 'missed_event_stop.py');
    fs.writeFileSync(filePath, 'print("stop")\n');

    const invokePromise = invokeLaunchTool(launchTool, {
      target: { file: filePath },
      waitForStop: true,
    });

    await vi.waitFor(() => {
      expect(harness.session).toBeDefined();
    });

    const journal = registry.getOrCreate(harness.sessionForRegistry());
    vi.spyOn(journal, 'getSnapshot').mockResolvedValue({
      checkpoint: 1,
      timestamp: Date.now(),
      stopReason: 'breakpoint',
      threadId: 7,
      location: `${filePath}:1`,
      callStack: [],
      locals: {},
      globals: {},
      stoppedThreads: [7],
      runningThreads: [],
    });

    setTimeout(() => {
      (journal as any)._onStopped({ reason: 'breakpoint', threadId: 7 });
    }, 250);

    const result = await invokePromise;
    expect(result.waitedForStop).toBe(true);
    expect(result.stopped).toBe(true);
    expect(result.snapshot).toMatchObject({ stopReason: 'breakpoint' });
  });

  it('returns an error result when the tool receives conflicting targets', async () => {
    const result = await invokeLaunchToolRaw(launchTool, {
      target: { currentFile: true, module: 'pkg.main' },
    });

    expect(result).toContain('Error: Choose exactly one launch target');
  });
});

async function invokeLaunchTool(tool: LaunchTool, input: Record<string, unknown>): Promise<Record<string, any>> {
  const raw = await invokeLaunchToolRaw(tool, input);
  return JSON.parse(raw);
}

async function invokeLaunchToolRaw(tool: LaunchTool, input: Record<string, unknown>): Promise<string> {
  const result = await tool.invoke({ input } as any, { isCancellationRequested: false } as any);
  const parts = Array.isArray((result as any).content) ? (result as any).content : [];
  return parts.map((part: { value?: string }) => part.value ?? '').join('');
}