import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as vscode from 'vscode';
import { JournalRegistry } from '../src/agent/stateJournal.js';
import { LaunchService } from '../src/debugAdapter/launchService.js';
import { DapperCliTool } from '../src/agent/tools/cli.js';
import { createLaunchHarness, type LaunchHarness } from './__harness__/launchHarness.js';

const vscodeMock = await import('./__mocks__/vscode.mjs');

const extensionPackageManifest = JSON.parse(
  fs.readFileSync(path.join(process.cwd(), 'package.json'), 'utf8'),
) as { contributes?: { languageModelTools?: unknown[] } };

function normalizePathSeparators(value: string): string {
  return value.replaceAll('\\', '/');
}

describe('DapperCliTool', () => {
  let tmpRoot: string;
  let registry: JournalRegistry;
  let launchService: LaunchService;
  let tool: DapperCliTool;
  let harness: LaunchHarness;

  beforeEach(() => {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'dapper-cli-tool-'));
    registry = new JournalRegistry();
    harness = createLaunchHarness({
      workspaceRoot: tmpRoot,
      activeInterpreter: path.join(tmpRoot, '.venv', process.platform === 'win32' ? 'Scripts' : 'bin', process.platform === 'win32' ? 'python.exe' : 'python'),
    });
    launchService = new LaunchService(registry);
    tool = new DapperCliTool(registry, launchService, extensionPackageManifest);
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

  it('returns help with CLI commands and underlying tool arguments', async () => {
    const payload = await invokeCli(tool, { command: 'help' });

    expect(payload.text).toContain('Dapper CLI works like pdb');
    expect(payload.text).toContain('dapper_launch (Dapper: Launch Python Debug Session):');
    expect(payload.text).toContain('  - waitForStop (optional): If true, wait for the new Python debug session to stop before returning and include an initial snapshot when available.');
    expect(payload.commands[0].summary).toBe('CLI help for Dapper agent tools');
    expect(payload.commands[0].result.commands.some((entry: { command: string }) => entry.command === 'help')).toBe(true);
    expect(payload.commands[0].result.tools.some((entry: { name: string; displayName: string }) => entry.name === 'dapper_execution' && entry.displayName === 'Dapper: Execute Debug Action')).toBe(true);
  });

  it('runs the active Python file and reports the stop location', async () => {
    const filePath = path.join(tmpRoot, 'app.py');
    fs.writeFileSync(filePath, 'print("hello")\n');
    harness.setActivePythonFile(filePath);

    const invokePromise = invokeCli(tool, { command: 'run' });

    await vi.waitFor(() => {
      expect(harness.session).toBeDefined();
    });

    const journal = registry.getOrCreate(harness.sessionForRegistry());
    vi.spyOn(journal, 'getSnapshot').mockResolvedValue({
      checkpoint: 1,
      timestamp: Date.now(),
      stopReason: 'entry',
      threadId: 1,
      location: `${filePath}:1 in <module>`,
      callStack: [{ name: '<module>', file: filePath, line: 1 }],
      locals: {},
      globals: {},
      stoppedThreads: [1],
      runningThreads: [],
    });

    setTimeout(() => {
      (journal as any)._onStopped({ reason: 'entry', threadId: 1 });
    }, 50);

    const payload = await invokePromise;
    expect(payload.sessionId).toBeTruthy();
    expect(payload.location).toMatchObject({ file: filePath, line: 1, function: '<module>' });
    expect(payload.commands[0].summary).toContain('Started and stopped at');
  });

  it('launches the active file through the new launch verb', async () => {
    const filePath = path.join(tmpRoot, 'launch_active.py');
    fs.writeFileSync(filePath, 'print("launch")\n');
    harness.setActivePythonFile(filePath);

    const payload = await invokeCli(tool, { command: 'launch --no-stop-on-entry --no-just-my-code --subprocess' });

    expect(payload.sessionId).toBeTruthy();
    expect(payload.commands[0].summary).toBe('Launched current file');
    expect(harness.lastStartDebuggingCall?.config.program).toBe(filePath);
    expect(harness.lastStartDebuggingCall?.config.stopOnEntry).toBe(false);
    expect(harness.lastStartDebuggingCall?.config.justMyCode).toBe(false);
    expect(harness.lastStartDebuggingCall?.config.subprocessAutoAttach).toBe(true);
  });

  it('launches a module target with sentinel args and repeated flags', async () => {
    const pythonPath = path.join(tmpRoot, 'custom-python');
    fs.writeFileSync(pythonPath, '');
    harness.onSessionStarted((session) => {
      const journal = registry.getOrCreate(session);
      setTimeout(() => {
        (journal as any)._onStopped({ reason: 'entry', threadId: 1 });
      }, 10);
    });

    const payload = await invokeCli(tool, {
      command: `launch module package.cli --cwd tools --env MODE=test --env DEBUG=1 --path src --path libs --python ${pythonPath} --wait -- --help --verbose`,
    });

    expect(payload.sessionId).toBeTruthy();
    expect(payload.commands[0].summary).toBe('Launched module package.cli');
    expect(harness.lastStartDebuggingCall?.config.module).toBe('package.cli');
    expect(harness.lastStartDebuggingCall?.config.args).toEqual(['--help', '--verbose']);
    expect(harness.lastStartDebuggingCall?.config.cwd).toBe('tools');
    expect(harness.lastStartDebuggingCall?.config.env).toEqual({ MODE: 'test', DEBUG: '1' });
    expect(harness.lastStartDebuggingCall?.config.moduleSearchPaths).toEqual(['src', 'libs']);
    expect(harness.lastStartDebuggingCall?.config.pythonPath).toBe(pythonPath);
    expect(payload.commands[0].result).toMatchObject({ waitedForStop: true, stopped: true });
  });

  it('launches a named configuration with a quoted config name', async () => {
    const program = path.join(tmpRoot, 'fixture.py');
    fs.writeFileSync(program, 'print("fixture")\n');
    harness.setLaunchConfigurations([
      {
        type: 'dapper',
        request: 'launch',
        name: 'Fixture Launch Config',
        program,
        cwd: tmpRoot,
      },
    ]);

    const payload = await invokeCli(tool, { command: 'launch config "Fixture Launch Config" --no-stop-on-entry' });

    expect(payload.sessionId).toBeTruthy();
    expect(payload.commands[0].summary).toBe('Launched config Fixture Launch Config');
    expect(harness.lastStartDebuggingCall?.config.name).toBe('Fixture Launch Config');
    expect(harness.lastStartDebuggingCall?.config.program).toBe(program);
    expect(harness.lastStartDebuggingCall?.config.stopOnEntry).toBe(false);
  });

  it('allows launch to start another session while one is already active', async () => {
    const existingSession = createStoppedSession('session-existing', tmpRoot);
    registry.getOrCreate(existingSession);
    vscode.debug.activeDebugSession = existingSession;

    const filePath = path.join(tmpRoot, 'launch_parallel.py');
    fs.writeFileSync(filePath, 'print("parallel")\n');
    harness.setActivePythonFile(filePath);

    const payload = await invokeCli(tool, { command: 'launch --no-stop-on-entry' });

    expect(payload.sessionId).toBeTruthy();
    expect(payload.sessionId).not.toBe(existingSession.id);
    expect(payload.commands[0].summary).toBe('Launched current file');
    expect(registry.journals.size).toBe(2);
    expect(harness.lastStartDebuggingCall?.config.program).toBe(filePath);
  });

  it('lists tracked sessions through the sessions verb', async () => {
    const sessionA = createStoppedSession('session-a', tmpRoot);
    const sessionB = createStoppedSession('session-b', tmpRoot);
    registry.getOrCreate(sessionA);
    registry.getOrCreate(sessionB);
    vscode.debug.activeDebugSession = sessionA;

    const payload = await invokeCli(tool, { command: 'sessions' });

    expect(payload.commands[0].summary).toBe('Found 2 Dapper session(s)');
    expect(payload.commands[0].result.sessions).toHaveLength(2);
  });

  it('shows metadata for the selected session through info', async () => {
    const session = createStoppedSession('session-info', tmpRoot);
    registry.getOrCreate(session);
    vscode.debug.activeDebugSession = session;

    const payload = await invokeCli(tool, { command: 'info' });

    expect(payload.sessionId).toBe('session-info');
    expect(payload.commands[0].summary).toBe('Session session-info is running');
    expect(payload.commands[0].result).toMatchObject({ id: 'session-info', type: 'dapper' });
  });

  it('inspects structured values with depth and max-items flags', async () => {
    const session = createStoppedSession('session-inspect', tmpRoot);
    registry.getOrCreate(session);
    vscode.debug.activeDebugSession = session;
    session.customRequest = vi.fn(async (command: string, args?: Record<string, unknown>) => {
      if (command === 'dapper/agentInspect') {
        expect(args).toMatchObject({ expression: 'session', depth: 3, maxItems: 10, frameIndex: 0 });
        return {
          root: {
            name: 'session',
            value: '<CheckoutSession>',
            children: [
              { name: 'total', value: '18.71' },
            ],
          },
        };
      }
      return undefined;
    });

    const payload = await invokeCli(tool, { command: 'inspect --depth 3 --max-items 10 session' });

    expect(payload.commands[0].summary).toBe('Inspected session: <CheckoutSession>');
    expect(payload.commands[0].result).toMatchObject({ name: 'session', value: '<CheckoutSession>' });
  });

  it('returns a state snapshot and updates the current location', async () => {
    const filePath = path.join(tmpRoot, 'snapshot.py');
    fs.writeFileSync(filePath, 'print("snapshot")\n');

    const session = createStoppedSession('session-state', tmpRoot);
    registry.getOrCreate(session);
    vscode.debug.activeDebugSession = session;
    session.customRequest = vi.fn(async (command: string) => {
      if (command === 'dapper/agentSnapshot') {
        return {
          stopReason: 'breakpoint',
          threadId: 6,
          location: `${filePath}:1 in <module>`,
          callStack: [{ name: '<module>', file: filePath, line: 1 }],
          locals: { status: "'ready'" },
          globals: {},
          stoppedThreads: [6],
          runningThreads: [],
        };
      }
      return undefined;
    });

    const payload = await invokeCli(tool, { command: 'state' });

    expect(payload.location).toMatchObject({ file: filePath, line: 1, function: '<module>' });
    expect(payload.commands[0].summary).toBe('Snapshot at snapshot.py:1 in <module>');
    expect(payload.commands[0].result).toMatchObject({ threadId: 6, stopReason: 'breakpoint' });
  });

  it('returns a diff since an explicit checkpoint', async () => {
    const session = createStoppedSession('session-diff', tmpRoot);
    const journal = registry.getOrCreate(session);
    vscode.debug.activeDebugSession = session;
    vi.spyOn(journal, 'getSnapshot').mockResolvedValue({
      checkpoint: 4,
      timestamp: Date.now(),
      stopReason: 'step',
      threadId: 9,
      location: `${tmpRoot}/diff.py:8 in work`,
      callStack: [{ name: 'work', file: `${tmpRoot}/diff.py`, line: 8 }],
      locals: { count: '2' },
      globals: {},
      stoppedThreads: [9],
      runningThreads: [],
    });
    vi.spyOn(journal, 'getDiffSince').mockReturnValue({
      fromCheckpoint: 2,
      toCheckpoint: 4,
      stopReason: 'step',
      locationChanged: 'old.py:1 -> diff.py:8',
      variableChanges: {
        added: { count: '2' },
        changed: {},
        removed: [],
      },
      newOutput: '',
      entries: [
        {
          checkpoint: 3,
          timestamp: Date.now(),
          type: 'stopped',
          summary: 'Thread 9 stopped',
        },
      ],
    });

    const payload = await invokeCli(tool, { command: 'diff 2' });

    expect(payload.commands[0].summary).toBe('Diff 2->4 with 1 journal entry');
    expect(payload.commands[0].result).toMatchObject({ fromCheckpoint: 2, toCheckpoint: 4 });
  });

  it('pauses the selected session', async () => {
    const session = createStoppedSession('session-pause', tmpRoot);
    registry.getOrCreate(session);
    vscode.debug.activeDebugSession = session;
    session.customRequest = vi.fn(async (command: string, args?: Record<string, unknown>) => {
      if (command === 'pause') {
        expect(args).toEqual({});
        return undefined;
      }
      return undefined;
    });

    const payload = await invokeCli(tool, { command: 'pause' });

    expect(payload.commands[0].summary).toBe('Pausing debug session');
    expect(payload.commands[0].result).toMatchObject({ action: 'pause', status: 'pausing' });
  });

  it('restarts the selected session', async () => {
    const session = createStoppedSession('session-restart', tmpRoot);
    registry.getOrCreate(session);
    vscode.debug.activeDebugSession = session;
    session.customRequest = vi.fn(async (command: string, args?: Record<string, unknown>) => {
      if (command === 'restart') {
        expect(args).toEqual({});
        return undefined;
      }
      return undefined;
    });

    const payload = await invokeCli(tool, { command: 'restart' });

    expect(payload.commands[0].summary).toBe('Restarting debug session');
    expect(payload.commands[0].result).toMatchObject({ action: 'restart', status: 'restarting' });
  });

  it('steps with alias syntax and reports the new stop location', async () => {
    const session = createStoppedSession('session-step', tmpRoot);
    const journal = registry.getOrCreate(session);
    vscode.debug.activeDebugSession = session;

    let stopCount = 0;
    session.customRequest = vi.fn(async (command: string, args?: Record<string, unknown>) => {
      if (command === 'next') {
        expect(args).toEqual({ threadId: 11 });
        setTimeout(() => {
          stopCount += 1;
          journal.onDidSendMessage({
            type: 'event',
            event: 'stopped',
            body: { reason: 'step', threadId: 11 },
          });
        }, 25);
        return undefined;
      }
      if (command === 'dapper/agentSnapshot') {
        return {
          stopReason: 'step',
          threadId: 11,
          location: `${tmpRoot}/worker.py:${40 + stopCount} in work`,
          callStack: [{ name: 'work', file: `${tmpRoot}/worker.py`, line: 40 + stopCount }],
          locals: { counter: String(stopCount) },
          globals: {},
          stoppedThreads: [11],
          runningThreads: [],
        };
      }
      return undefined;
    });

    const payload = await invokeCli(tool, { command: 'n', threadId: 11 });

    expect(payload.threadId).toBe(11);
    expect(payload.location).toMatchObject({ file: `${tmpRoot}/worker.py`, line: 41, function: 'work' });
    expect(payload.commands[0].summary).toContain('Stopped at');
  });

  it('supports semicolon chaining for repeated stepping', async () => {
    const session = createStoppedSession('session-chain', tmpRoot);
    const journal = registry.getOrCreate(session);
    vscode.debug.activeDebugSession = session;

    let stopCount = 0;
    session.customRequest = vi.fn(async (command: string, args?: Record<string, unknown>) => {
      if (command === 'next') {
        expect(args).toEqual({ threadId: 7 });
        setTimeout(() => {
          stopCount += 1;
          journal.onDidSendMessage({
            type: 'event',
            event: 'stopped',
            body: { reason: 'step', threadId: 7 },
          });
        }, 20);
        return undefined;
      }
      if (command === 'dapper/agentSnapshot') {
        return {
          stopReason: 'step',
          threadId: 7,
          location: `${tmpRoot}/loop.py:${100 + stopCount} in loop`,
          callStack: [{ name: 'loop', file: `${tmpRoot}/loop.py`, line: 100 + stopCount }],
          locals: { iteration: String(stopCount) },
          globals: {},
          stoppedThreads: [7],
          runningThreads: [],
        };
      }
      return undefined;
    });

    const payload = await invokeCli(tool, { command: 'n; n', threadId: 7 });

    expect(payload.commands).toHaveLength(2);
    expect(payload.commands[0].status).toBe('ok');
    expect(payload.commands[1].status).toBe('ok');
    expect(payload.location).toMatchObject({ file: `${tmpRoot}/loop.py`, line: 102, function: 'loop' });
  });

  it('evaluates print expressions and preserves the expression text', async () => {
    const session = createStoppedSession('session-print', tmpRoot);
    registry.getOrCreate(session);
    vscode.debug.activeDebugSession = session;
    session.customRequest = vi.fn(async (command: string, args?: Record<string, unknown>) => {
      if (command === 'dapper/agentEval') {
        expect(args).toMatchObject({ expressions: ['threshold + 2'], frameIndex: 0 });
        return {
          results: [
            { expression: 'threshold + 2', result: '17', type: 'int' },
          ],
        };
      }
      return undefined;
    });

    const payload = await invokeCli(tool, { command: 'p threshold + 2' });

    expect(payload.commands[0].summary).toBe('threshold + 2 = 17');
    expect(payload.commands[0].result).toEqual({
      expression: 'threshold + 2',
      type: 'int',
      value: '17',
    });
  });

  it('navigates frames and keeps print aligned with the selected frame', async () => {
    const session = createStoppedSession('session-frames', tmpRoot);
    registry.getOrCreate(session);
    vscode.debug.activeDebugSession = session;
    session.customRequest = vi.fn(async (command: string, args?: Record<string, unknown>) => {
      if (command === 'dapper/agentSnapshot') {
        return {
          stopReason: 'breakpoint',
          threadId: 5,
          location: `${tmpRoot}/app.py:20 in leaf`,
          callStack: [
            { name: 'leaf', file: `${tmpRoot}/app.py`, line: 20 },
            { name: 'caller', file: `${tmpRoot}/app.py`, line: 12 },
          ],
          locals: { leaf_value: '21' },
          globals: { shared: '1' },
          stoppedThreads: [5],
          runningThreads: [],
        };
      }
      if (command === 'dapper/agentEval') {
        if (args?.frameIndex === 1) {
          return { results: [{ expression: 'caller_value', result: '13', type: 'int' }] };
        }
        return { results: [{ expression: 'leaf_value', result: '21', type: 'int' }] };
      }
      return undefined;
    });

    const payload = await invokeCli(tool, { command: 'frame 1; p caller_value; down; p leaf_value' });

    expect(payload.frameIndex).toBe(0);
    expect(payload.location).toMatchObject({ file: `${tmpRoot}/app.py`, line: 20, function: 'leaf' });
    expect(payload.commands.map((command: { summary: string }) => command.summary)).toEqual([
      'Selected frame #1: caller',
      'caller_value = 13',
      'Selected frame #0: leaf',
      'leaf_value = 21',
    ]);
    expect(session.customRequest).toHaveBeenCalledWith('dapper/agentEval', {
      expressions: ['caller_value'],
      frameIndex: 1,
    });
    expect(session.customRequest).toHaveBeenCalledWith('dapper/agentEval', {
      expressions: ['leaf_value'],
      frameIndex: 0,
    });
  });

  it('returns globals and source listing for the selected frame', async () => {
    const filePath = path.join(tmpRoot, 'stack.py');
    fs.writeFileSync(filePath, ['one', 'two', 'three', 'four', 'five'].join('\n'));

    const session = createStoppedSession('session-scope-list', tmpRoot);
    registry.getOrCreate(session);
    vscode.debug.activeDebugSession = session;
    session.customRequest = vi.fn(async (command: string, args?: Record<string, unknown>) => {
      if (command === 'dapper/agentSnapshot') {
        return {
          stopReason: 'breakpoint',
          threadId: 3,
          location: `${filePath}:4 in inner`,
          callStack: [
            { name: 'inner', file: filePath, line: 4 },
            { name: 'outer', file: filePath, line: 2 },
          ],
          locals: { inner_value: '4' },
          globals: { top_level: 'yes' },
          stoppedThreads: [3],
          runningThreads: [],
        };
      }
      if (command === 'dapper/agentInspect') {
        expect(args).toMatchObject({ expression: 'globals()', frameIndex: 1 });
        return {
          root: {
            name: 'globals()',
            value: '<dict>',
            children: [
              { name: 'module_name', value: "'stack'" },
              { name: 'shared_flag', value: 'True' },
            ],
          },
        };
      }
      return undefined;
    });

    const payload = await invokeCli(tool, { command: 'frame 1; globals; list 2,4' });

    expect(payload.frameIndex).toBe(1);
    expect(payload.location).toMatchObject({ file: filePath, line: 2, function: 'outer' });
    expect(payload.commands[1].result).toEqual({
      module_name: "'stack'",
      shared_flag: 'True',
    });
    expect(payload.commands[2].result.lines).toEqual([
      { line: 2, text: 'two', current: true },
      { line: 3, text: 'three', current: false },
      { line: 4, text: 'four', current: false },
    ]);
  });

  it('sets a workspace-relative breakpoint target', async () => {
    const filePath = path.join(tmpRoot, 'pkg', 'app.py');
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    fs.writeFileSync(filePath, 'print("bp")\n');

    const payload = await invokeCli(tool, { command: 'break pkg/app.py:12' });

    expect(payload.location).toEqual({ file: filePath, line: 12 });
    expect(payload.commands[0].summary).toContain('Breakpoint set at');
    expect(vscode.debug.breakpoints).toHaveLength(1);
  });

  it('resolves a breakpoint target from a unique Python filename stem', async () => {
    const filePath = path.join(tmpRoot, 'src', 'main.py');
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    fs.writeFileSync(filePath, 'print("stem")\n');

    const payload = await invokeCli(tool, { command: 'break main:23' });

    expect(payload.location).toEqual({ file: filePath, line: 23 });
    expect(normalizePathSeparators(payload.commands[0].summary)).toBe('Breakpoint set at src/main.py:23');
  });

  it('resolves a breakpoint target from a function name in the active call stack', async () => {
    const filePath = path.join(tmpRoot, 'pkg', 'worker.py');
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    fs.writeFileSync(filePath, 'print("worker")\n');

    const session = createStoppedSession('session-break-function', tmpRoot);
    registry.getOrCreate(session);
    vscode.debug.activeDebugSession = session;
    session.customRequest = vi.fn(async (command: string, args?: Record<string, unknown>) => {
      if (command === 'dapper/agentSnapshot') {
        return {
          stopReason: 'breakpoint',
          threadId: 4,
          location: `${filePath}:11 in helper`,
          callStack: [
            { name: 'helper', file: filePath, line: 11 },
            { name: 'main', file: filePath, line: 5 },
          ],
          locals: {},
          globals: {},
          stoppedThreads: [4],
          runningThreads: [],
        };
      }
      if (command === 'setBreakpoints') {
        return {
          breakpoints: Array.isArray(args?.breakpoints)
            ? (args?.breakpoints as Array<{ line: number }>).map(bp => ({ verified: true, line: bp.line }))
            : [],
        };
      }
      return undefined;
    });

    const payload = await invokeCli(tool, { command: 'break main:41', sessionId: session.id });

    expect(payload.location).toEqual({ file: filePath, line: 41 });
    expect(normalizePathSeparators(payload.commands[0].summary)).toBe('Breakpoint set at pkg/worker.py:41');
  });

  it('supports disabling, enabling, and clearing breakpoints', async () => {
    const filePath = path.join(tmpRoot, 'pkg', 'toggle.py');
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    fs.writeFileSync(filePath, 'print("toggle")\n');

    const session = createStoppedSession('session-bp-toggle', tmpRoot);
    registry.getOrCreate(session);
    vscode.debug.activeDebugSession = session;
    session.customRequest = vi.fn(async (command: string, args?: Record<string, unknown>) => {
      if (command === 'setBreakpoints') {
        return {
          breakpoints: Array.isArray(args?.breakpoints)
            ? (args?.breakpoints as Array<{ line: number }>).map(bp => ({ verified: true, line: bp.line }))
            : [],
        };
      }
      return undefined;
    });

    await invokeCli(tool, { command: `break pkg/toggle.py:8` });
    expect(vscode.debug.breakpoints[0]).toMatchObject({ enabled: true });

    await invokeCli(tool, { command: `disable pkg/toggle.py:8`, sessionId: session.id });
    expect(vscode.debug.breakpoints[0]).toMatchObject({ enabled: false });

    await invokeCli(tool, { command: `enable pkg/toggle.py:8`, sessionId: session.id });
    expect(vscode.debug.breakpoints[0]).toMatchObject({ enabled: true });

    await invokeCli(tool, { command: `clear pkg/toggle.py:8`, sessionId: session.id });
    expect(vscode.debug.breakpoints).toHaveLength(0);
  });

  it('lists breakpoints and supports file-line filtering through breaks', async () => {
    const filePath = path.join(tmpRoot, 'pkg', 'listing.py');
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    fs.writeFileSync(filePath, 'print("listing")\n');

    await invokeCli(tool, { command: 'break pkg/listing.py:8' });
    await invokeCli(tool, { command: 'break pkg/listing.py:9' });

    const payload = await invokeCli(tool, { command: 'breaks pkg/listing.py:9' });

    expect(payload.commands[0].summary).toBe('Found 1 breakpoint at pkg/listing.py:9');
    expect(payload.commands[0].result).toMatchObject({
      count: 1,
      breakpoints: [
        {
          file: 'pkg/listing.py',
          line: 9,
          enabled: true,
        },
      ],
    });
  });

  it('adds a conditional breakpoint through break if', async () => {
    const filePath = path.join(tmpRoot, 'pkg', 'conditions.py');
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    fs.writeFileSync(filePath, 'print("conditions")\n');

    const payload = await invokeCli(tool, { command: 'break pkg/conditions.py:14 if total > 100' });

    expect(payload.commands[0].summary).toBe('Conditional breakpoint set at pkg/conditions.py:14');
    expect(payload.commands[0].result).toMatchObject({
      condition: 'total > 100',
      logMessage: null,
    });
    expect(vscode.debug.breakpoints[0]).toMatchObject({
      condition: 'total > 100',
      logMessage: undefined,
    });
  });

  it('adds a logpoint through break log', async () => {
    const filePath = path.join(tmpRoot, 'pkg', 'logpoints.py');
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    fs.writeFileSync(filePath, 'print("logpoints")\n');

    const payload = await invokeCli(tool, { command: 'break pkg/logpoints.py:18 log total={total}' });

    expect(payload.commands[0].summary).toBe('Logpoint set at pkg/logpoints.py:18');
    expect(payload.commands[0].result).toMatchObject({
      condition: null,
      logMessage: 'total={total}',
    });
    expect(vscode.debug.breakpoints[0]).toMatchObject({
      condition: undefined,
      logMessage: 'total={total}',
    });
  });

  it('supports break then continue in one chained request', async () => {
    const filePath = path.join(tmpRoot, 'pkg', 'resume.py');
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    fs.writeFileSync(filePath, 'print("resume")\n');

    const session = createStoppedSession('session-break-continue', tmpRoot);
    const journal = registry.getOrCreate(session);
    vscode.debug.activeDebugSession = session;

    session.customRequest = vi.fn(async (command: string, args?: Record<string, unknown>) => {
      if (command === 'setBreakpoints') {
        return {
          breakpoints: Array.isArray(args?.breakpoints)
            ? (args?.breakpoints as Array<{ line: number }>).map(bp => ({ verified: true, line: bp.line }))
            : [],
        };
      }
      if (command === 'continue') {
        expect(args).toEqual({ threadId: 17 });
        setTimeout(() => {
          journal.onDidSendMessage({
            type: 'event',
            event: 'stopped',
            body: { reason: 'breakpoint', threadId: 17 },
          });
        }, 20);
        return undefined;
      }
      if (command === 'dapper/agentSnapshot') {
        return {
          stopReason: 'breakpoint',
          threadId: 17,
          location: `${filePath}:8 in main`,
          callStack: [{ name: 'main', file: filePath, line: 8 }],
          locals: {},
          globals: {},
          stoppedThreads: [17],
          runningThreads: [],
        };
      }
      return undefined;
    });

    const payload = await invokeCli(tool, { command: 'break pkg/resume.py:8; c', sessionId: session.id, threadId: 17 });

    expect(payload.commands).toHaveLength(2);
    expect(payload.commands[0].summary).toContain('Breakpoint set at');
    expect(normalizePathSeparators(payload.commands[1].summary)).toBe('Stopped at pkg/resume.py:8 in main');
  });

  it('executes the full fixture file flow in one chained request', async () => {
    copyFixtureWorkspace(tmpRoot);
    const appFile = path.join(tmpRoot, 'app.py');
    const breakpointLine = findMarkerLine(appFile, 'BREAKPOINT: main-after-summary');
    const moduleLine = findLastLineContaining(appFile, 'main()');
    harness.setActivePythonFile(appFile);

    harness.onSessionStarted((session) => {
      const journal = registry.getOrCreate(session);
      const entrySnapshot = {
        checkpoint: 1,
        timestamp: Date.now(),
        stopReason: 'entry',
        threadId: 1,
        location: `${appFile}:1 in <module>`,
        callStack: [{ name: '<module>', file: appFile, line: 1 }],
        locals: {},
        globals: {
          LOYALTY_DISCOUNT_THRESHOLD: '100',
          REVIEW_TOTAL_THRESHOLD: '20',
        },
        stoppedThreads: [1],
        runningThreads: [],
      };
      const breakpointSnapshot = {
        checkpoint: 2,
        timestamp: Date.now(),
        stopReason: 'breakpoint',
        threadId: 1,
        location: `${appFile}:${breakpointLine} in main`,
        callStack: [
          { name: 'main', file: appFile, line: breakpointLine },
          { name: '<module>', file: appFile, line: moduleLine },
        ],
        locals: {
          threshold: '15',
          needs_follow_up: 'True',
          summary: "{'customer': 'Ada', 'subtotal': 19.25, 'discount_rate': 0.1, 'discounted_subtotal': 17.32, 'tax': 1.39, 'total': 18.71, 'status': 'clear', 'item_count': 3}",
        },
        globals: {
          LOYALTY_DISCOUNT_THRESHOLD: '100',
          REVIEW_TOTAL_THRESHOLD: '20',
        },
        stoppedThreads: [1],
        runningThreads: [],
      };

      let snapshotCallCount = 0;
      vi.spyOn(journal, 'getSnapshot').mockImplementation(async () => {
        snapshotCallCount += 1;
        return snapshotCallCount <= 2 ? entrySnapshot : breakpointSnapshot;
      });

      session.customRequest = vi.fn(async (command: string, args?: Record<string, unknown>) => {
        if (command === 'continue') {
          setTimeout(() => {
            journal.onDidSendMessage({
              type: 'event',
              event: 'stopped',
              body: { reason: 'breakpoint', threadId: 1 },
            });
          }, 20);
          return undefined;
        }
        if (command === 'dapper/agentEval') {
          expect(args).toMatchObject({ expressions: ['threshold'], frameIndex: 0 });
          return {
            results: [{ expression: 'threshold', result: '15', type: 'int' }],
          };
        }
        return undefined;
      });

      setTimeout(() => {
        (journal as any)._onStopped({ reason: 'entry', threadId: 1 });
      }, 10);
    });

    const payload = await invokeCli(tool, { command: `break app:${breakpointLine}; run; c; p threshold; globals` });

    expect(payload.location).toEqual({ file: appFile, line: breakpointLine, function: 'main' });
    expect(payload.commands.map((command: { summary: string }) => normalizePathSeparators(command.summary))).toEqual([
      `Breakpoint set at app.py:${breakpointLine}`,
      'Started and stopped at app.py:1 in <module>',
      `Stopped at app.py:${breakpointLine} in main`,
      'threshold = 15',
      'Globals: 2 name(s)',
    ]);
    expect(payload.commands[4].result).toEqual({
      LOYALTY_DISCOUNT_THRESHOLD: '100',
      REVIEW_TOTAL_THRESHOLD: '20',
    });
    expect(vscode.debug.breakpoints).toHaveLength(1);
    expect(vscode.debug.breakpoints[0]).toMatchObject({ enabled: true });
  });

  it('executes the fixture stack-review flow with frame navigation and caller locals', async () => {
    copyFixtureWorkspace(tmpRoot);
    const appFile = path.join(tmpRoot, 'app.py');
    const breakpointLine = findMarkerLine(appFile, 'BREAKPOINT: order-summary');
    const callerLine = findLineContaining(appFile, 'summary = session.summary()');
    const moduleLine = findLastLineContaining(appFile, 'main()');
    harness.setActivePythonFile(appFile);

    harness.onSessionStarted((session) => {
      const journal = registry.getOrCreate(session);
      const entrySnapshot = {
        checkpoint: 1,
        timestamp: Date.now(),
        stopReason: 'entry',
        threadId: 1,
        location: `${appFile}:1 in <module>`,
        callStack: [{ name: '<module>', file: appFile, line: 1 }],
        locals: {},
        globals: {},
        stoppedThreads: [1],
        runningThreads: [],
      };
      const breakpointSnapshot = {
        checkpoint: 2,
        timestamp: Date.now(),
        stopReason: 'breakpoint',
        threadId: 1,
        location: `${appFile}:${breakpointLine} in summary`,
        callStack: [
          { name: 'summary', file: appFile, line: breakpointLine },
          { name: 'main', file: appFile, line: callerLine },
          { name: '<module>', file: appFile, line: moduleLine },
        ],
        locals: {
          subtotal: '19.25',
          discount_rate: '0.1',
          discounted_subtotal: '17.32',
          tax: '1.39',
          total: '18.71',
          status: "'clear'",
        },
        globals: {},
        stoppedThreads: [1],
        runningThreads: [],
      };

      let snapshotCallCount = 0;
      vi.spyOn(journal, 'getSnapshot').mockImplementation(async () => {
        snapshotCallCount += 1;
        return snapshotCallCount <= 2 ? entrySnapshot : breakpointSnapshot;
      });

      session.customRequest = vi.fn(async (command: string, args?: Record<string, unknown>) => {
        if (command === 'continue') {
          setTimeout(() => {
            journal.onDidSendMessage({
              type: 'event',
              event: 'stopped',
              body: { reason: 'breakpoint', threadId: 1 },
            });
          }, 20);
          return undefined;
        }
        if (command === 'dapper/agentInspect') {
          expect(args).toMatchObject({ expression: 'locals()', frameIndex: 1 });
          return {
            root: {
              name: 'locals()',
              value: '<dict>',
              children: [
                { name: 'session', value: "CheckoutSession(customer='Ada', loyalty_points=120, lines=[...])" },
              ],
            },
          };
        }
        return undefined;
      });

      setTimeout(() => {
        (journal as any)._onStopped({ reason: 'entry', threadId: 1 });
      }, 10);
    });

    const payload = await invokeCli(tool, { command: `break app:${breakpointLine}; run; c; where; up; locals` });

    expect(payload.frameIndex).toBe(1);
    expect(payload.location).toEqual({ file: appFile, line: callerLine, function: 'main' });
    expect(payload.commands[3].summary).toBe('Call stack has 3 frame(s); selected frame is #0 summary');
    expect(payload.commands[3].result.selectedFrameIndex).toBe(0);
    expect(payload.commands[4].summary).toBe('Selected frame #1: main');
    expect(payload.commands[5]).toMatchObject({
      summary: 'Locals: 1 name(s)',
      result: {
        session: "CheckoutSession(customer='Ada', loyalty_points=120, lines=[...])",
      },
    });
  });

  it('reports invalid breakpoint syntax clearly', async () => {
    const raw = await invokeCliRaw(tool, { command: 'break pkg/app.py:not-a-line' });

    expect(raw).toContain("Error: Breakpoint target 'pkg/app.py:not-a-line' is invalid. Expected file:line or function:line.");
  });

  it('reports invalid launch options clearly', async () => {
    const raw = await invokeCliRaw(tool, { command: 'launch module package.cli --bogus' });

    expect(raw).toContain("Error: Unknown launch option '--bogus'.");
  });

  it('reports invalid inspect options clearly', async () => {
    const raw = await invokeCliRaw(tool, { command: 'inspect --depth nope value' });

    expect(raw).toContain("Error: 'inspect --depth' requires a positive integer.");
  });

  it('surfaces print failures when there is no stopped frame', async () => {
    const session = createStoppedSession('session-print-error', tmpRoot);
    registry.getOrCreate(session);
    vscode.debug.activeDebugSession = session;
    session.customRequest = vi.fn(async (command: string) => {
      if (command === 'dapper/agentEval') {
        return {
          results: [
            { expression: 'value', error: 'No stopped frame available' },
          ],
        };
      }
      return undefined;
    });

    const raw = await invokeCliRaw(tool, { command: 'p value' });

    expect(raw).toContain('Error: No stopped frame available');
  });

  it('returns partial results when commands continue after quit', async () => {
    const session = createStoppedSession('session-quit-chain', tmpRoot);
    registry.getOrCreate(session);
    vscode.debug.activeDebugSession = session;
    session.customRequest = vi.fn(async (command: string) => {
      if (command === 'terminate') {
        return { action: 'terminate', status: 'terminating' };
      }
      return undefined;
    });

    const payload = await invokeCli(tool, { command: 'q; n', sessionId: session.id });

    expect(payload.commands).toHaveLength(2);
    expect(payload.commands[0]).toMatchObject({
      command: 'q',
      status: 'ok',
      summary: 'Terminating debug session',
    });
    expect(payload.commands[1]).toMatchObject({
      command: 'n',
      status: 'error',
      error: "No active session. The previous 'quit' command terminated the selected session.",
    });
  });

  it('returns a clear error when multiple sessions exist without a sessionId', async () => {
    registry.getOrCreate(createStoppedSession('session-a', tmpRoot));
    registry.getOrCreate(createStoppedSession('session-b', tmpRoot));

    const raw = await invokeCliRaw(tool, { command: 'locals' });

    expect(raw).toContain('Error: Multiple active Dapper sessions found. Specify sessionId.');
  });

  it('returns partial results when a later chained command fails', async () => {
    const payload = await invokeCli(tool, { command: 'help; until' });

    expect(payload.commands).toHaveLength(2);
    expect(payload.commands[0].status).toBe('ok');
    expect(payload.commands[1]).toMatchObject({
      command: 'until',
      status: 'error',
      error: "Command 'until' is not supported in this version.",
    });
    expect(payload.text).toContain('CLI help for Dapper agent tools');
    expect(payload.text).toContain("Command 'until' is not supported in this version.");
  });
});

function createStoppedSession(sessionId: string, root: string): vscode.DebugSession {
  return {
    id: sessionId,
    type: 'dapper',
    name: sessionId,
    configuration: { program: path.join(root, 'app.py') },
    customRequest: vi.fn(async () => undefined),
  } as unknown as vscode.DebugSession;
}

async function invokeCli(tool: DapperCliTool, input: Record<string, unknown>): Promise<any> {
  const raw = await invokeCliRaw(tool, input);
  return JSON.parse(raw);
}

async function invokeCliRaw(tool: DapperCliTool, input: Record<string, unknown>): Promise<string> {
  const result = await tool.invoke({ input } as any, { isCancellationRequested: false } as any);
  const parts = Array.isArray((result as any).content) ? (result as any).content : [];
  return parts.map((part: { value?: string }) => part.value ?? '').join('');
}

function copyFixtureWorkspace(destinationRoot: string): void {
  const fixtureRoot = path.join(process.cwd(), 'test', 'fixtures', 'agent_debug_workspace');
  for (const entry of fs.readdirSync(fixtureRoot, { withFileTypes: true })) {
    const sourcePath = path.join(fixtureRoot, entry.name);
    const destinationPath = path.join(destinationRoot, entry.name);
    fs.cpSync(sourcePath, destinationPath, { recursive: true, force: true });
  }
}

function findMarkerLine(filePath: string, marker: string): number {
  const lines = fs.readFileSync(filePath, 'utf8').split(/\r?\n/);
  const index = lines.findIndex(line => line.includes(marker));
  if (index < 0) {
    throw new Error(`Marker '${marker}' was not found in ${filePath}`);
  }
  return index + 1;
}

function findLineContaining(filePath: string, content: string): number {
  const lines = fs.readFileSync(filePath, 'utf8').split(/\r?\n/);
  const index = lines.findIndex(line => line.includes(content));
  if (index < 0) {
    throw new Error(`Content '${content}' was not found in ${filePath}`);
  }
  return index + 1;
}

function findLastLineContaining(filePath: string, content: string): number {
  const lines = fs.readFileSync(filePath, 'utf8').split(/\r?\n/);
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    if (lines[index].includes(content)) {
      return index + 1;
    }
  }
  throw new Error(`Content '${content}' was not found in ${filePath}`);
}