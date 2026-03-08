import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as Net from 'net';
import * as vscode from 'vscode';
import { EventEmitter, once } from 'events';

const { spawnMock } = vi.hoisted(() => ({
  spawnMock: vi.fn(),
}));

vi.mock('child_process', async () => {
  const actual = await vi.importActual<typeof import('child_process')>('child_process');
  return {
    ...actual,
    spawn: spawnMock,
  };
});

import { DapperDebugAdapterDescriptorFactory } from '../src/debugAdapter/dapperDebugAdapter.js';
import { fireDebugEvent, resetDebugListeners } from './__mocks__/vscode.mjs';

vi.mock('@vscode/debugadapter', () => {
  class MockLoggingDebugSession {
    protected sendResponse(_response: unknown) {}
    protected sendEvent(_event: unknown) {}
    public setDebuggerLinesStartAt1(_value: boolean) {}
    public setDebuggerColumnsStartAt1(_value: boolean) {}
    public setRunAsServer(_value: boolean) {}
    public start(_inStream: unknown, _outStream: unknown) {}
  }

  return {
    LoggingDebugSession: MockLoggingDebugSession,
    InitializedEvent: class {},
    TerminatedEvent: class {},
    StoppedEvent: class { constructor(public reason: string, public threadId?: number, public text?: string) {} },
    OutputEvent: class { constructor(public output: string, public category?: string) {} },
    ContinuedEvent: class { constructor(public threadId?: number, public allThreadsContinued?: boolean) {} },
    ThreadEvent: class { constructor(public reason: string, public threadId?: number) {} },
    BreakpointEvent: class { constructor(public reason: string, public breakpoint?: unknown) {} },
    LoadedSourceEvent: class { constructor(public reason: string, public source?: unknown) {} },
    ModuleEvent: class { constructor(public reason: string, public module?: unknown) {} },
    ExitedEvent: class { constructor(public exitCode?: number) {} },
    Event: class { constructor(public event: string, public body?: unknown) {} },
  };
});

async function allocatePort(): Promise<number> {
  const server = Net.createServer();
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const address = server.address();
  if (!address || typeof address === 'string') {
    server.close();
    throw new Error('Failed to allocate an ephemeral TCP port');
  }
  const port = address.port;
  server.close();
  await once(server, 'close');
  return port;
}

describe('DapperDebugAdapterDescriptorFactory child attach flow', () => {
  let factory: DapperDebugAdapterDescriptorFactory;

  beforeEach(() => {
    resetDebugListeners();
    vi.restoreAllMocks();
    spawnMock.mockReset();
    factory = new DapperDebugAdapterDescriptorFactory({
      extension: { packageJSON: { version: '0.9.1' } },
      globalStorageUri: { fsPath: '/tmp/dapper-tests' },
    } as unknown as vscode.ExtensionContext);
  });

  afterEach(() => {
    vi.useRealTimers();
    factory.dispose();
    resetDebugListeners();
  });

  it('starts an internal child debug session after correlating the child socket', async () => {
    const startDebugging = vi.fn(async () => true);
    (vscode.debug.startDebugging as unknown) = startDebugging;

    const port = await allocatePort();
    const parentSession = {
      id: 'parent-session',
      type: 'dapper',
      name: 'Parent',
      configuration: { type: 'dapper', request: 'launch', program: 'parent.py' },
      workspaceFolder: { name: 'workspace', uri: { fsPath: '/workspace' } },
    } as unknown as vscode.DebugSession;

    fireDebugEvent('onDidReceiveDebugSessionCustomEvent', {
      session: parentSession,
      event: 'dapper/childProcess',
      body: {
        sessionId: 'child-launcher-session',
        pid: 4242,
        ipcPort: port,
        name: 'subprocess_child.py',
        cwd: '/workspace/examples/sample_programs',
        command: ['/usr/bin/python3', 'subprocess_child.py'],
      },
    });

    await vi.waitFor(() => {
      expect((factory as any).childSessionManager.childSessions.get('child-launcher-session')?.listener).toBeDefined();
    });

    const childSocket = Net.createConnection({ host: '127.0.0.1', port });
    await once(childSocket, 'connect');

    await vi.waitFor(() => {
      expect(startDebugging).toHaveBeenCalledTimes(1);
    });

    const firstStartCall = startDebugging.mock.calls[0];
    expect(firstStartCall).toBeDefined();

    const [workspaceFolder, config, options] = firstStartCall as unknown as [
      vscode.WorkspaceFolder | undefined,
      vscode.DebugConfiguration,
      vscode.DebugSessionOptions | undefined,
    ];
    expect(workspaceFolder).toEqual(parentSession.workspaceFolder);
    expect(config).toMatchObject({
      type: 'dapper',
      request: 'launch',
      name: 'Dapper Child: subprocess_child.py (4242)',
      __dapperIsChildSession: true,
      __dapperChildSessionId: 'child-launcher-session',
      __dapperChildPid: 4242,
      __dapperParentDebugSessionId: 'parent-session',
      cwd: '/workspace/examples/sample_programs',
    });
    expect(options).toMatchObject({
      parentSession,
      compact: false,
      lifecycleManagedByParent: false,
      consoleMode: vscode.DebugConsoleMode.MergeWithParent,
    });

    const descriptor = await factory.createDebugAdapterDescriptor({
      id: 'child-vscode-session',
      type: 'dapper',
      name: 'Child',
      configuration: config,
      workspaceFolder: parentSession.workspaceFolder,
    } as unknown as vscode.DebugSession, undefined);

    expect((descriptor as vscode.DebugAdapterServer).port).toBeGreaterThan(0);
    expect((factory as any).childSessionManager.childSessions.get('child-launcher-session')?.vscodeSessionId).toBe('child-vscode-session');

    childSocket.destroy();
  });

  it('cleans up a pending child session when a child exits before VS Code attaches', async () => {
    const port = await allocatePort();
    const parentSession = {
      id: 'parent-session',
      type: 'dapper',
      name: 'Parent',
      configuration: { type: 'dapper', request: 'launch', program: 'parent.py' },
      workspaceFolder: { name: 'workspace', uri: { fsPath: '/workspace' } },
    } as unknown as vscode.DebugSession;

    fireDebugEvent('onDidReceiveDebugSessionCustomEvent', {
      session: parentSession,
      event: 'dapper/childProcess',
      body: {
        sessionId: 'child-launcher-session',
        pid: 4242,
        ipcPort: port,
        name: 'subprocess_child.py',
      },
    });

    await vi.waitFor(() => {
      expect((factory as any).childSessionManager.childSessions.has('child-launcher-session')).toBe(true);
    });

    fireDebugEvent('onDidReceiveDebugSessionCustomEvent', {
      session: parentSession,
      event: 'dapper/childProcessExited',
      body: {
        sessionId: 'child-launcher-session',
        pid: 4242,
        name: 'subprocess_child.py',
      },
    });

    await vi.waitFor(() => {
      expect((factory as any).childSessionManager.childSessions.has('child-launcher-session')).toBe(false);
      expect((factory as any).childSessionManager.childSessionIdsByPid.has(4242)).toBe(false);
    });
  });

  it('spawns the attach-by-pid helper for attach sessions with processId', async () => {
    const outputChannel = {
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
      debug: vi.fn(),
      trace: vi.fn(),
      show: vi.fn(),
    };
    (factory as any).envManager.prepareEnvironment = vi.fn(async () => ({
      pythonPath: '/usr/bin/python3.14',
      needsInstall: false,
    }));
    (factory as any).envManager.getOutputChannel = () => outputChannel;
    (factory as any).envManager.showOutputChannel = vi.fn();

    const child = new EventEmitter() as EventEmitter & {
      stdout: EventEmitter;
      stderr: EventEmitter;
    };
    child.stdout = new EventEmitter();
    child.stderr = new EventEmitter();
    let helperSocket: Net.Socket | undefined;
    spawnMock.mockImplementation((_pythonPath: string, args: string[]) => {
      const portIndex = args.indexOf('--ipc-port');
      const port = Number(args[portIndex + 1]);
      queueMicrotask(() => {
        helperSocket = Net.createConnection({ host: '127.0.0.1', port });
      });
      queueMicrotask(() => child.emit('close', 0));
      return child;
    });

    const createTerminalSpy = vi.spyOn(vscode.window, 'createTerminal');

    const descriptor = await factory.createDebugAdapterDescriptor({
      id: 'attach-session',
      type: 'dapper',
      name: 'Attach',
      configuration: {
        type: 'dapper',
        request: 'attach',
        name: 'Attach',
        processId: 4321,
        justMyCode: false,
      },
      workspaceFolder: { name: 'workspace', uri: { fsPath: '/workspace' } },
    } as unknown as vscode.DebugSession, undefined);

    expect((descriptor as vscode.DebugAdapterServer).port).toBeGreaterThan(0);
    expect(spawnMock).toHaveBeenCalledTimes(1);
    const [pythonPath, args, options] = spawnMock.mock.calls[0] as [string, string[], { cwd: string; env: Record<string, string> }];
    expect(pythonPath).toBe('/usr/bin/python3.14');
    expect(args).toContain('dapper.launcher.attach_by_pid');
    expect(args).toContain('--pid');
    expect(args).toContain('4321');
    expect(args).toContain('--no-just-my-code');
    expect(args).toContain('--ipc-port');
    expect(options.cwd).toBe('/workspace');
    expect(createTerminalSpy).not.toHaveBeenCalled();

    helperSocket?.destroy();
  });

  it('returns a direct server descriptor for attach sessions with host and port', async () => {
    const descriptor = await factory.createDebugAdapterDescriptor({
      id: 'attach-session',
      type: 'dapper',
      name: 'Attach Host Port',
      configuration: {
        type: 'dapper',
        request: 'attach',
        name: 'Attach Host Port',
        host: '127.0.0.1',
        port: 9000,
      },
      workspaceFolder: { name: 'workspace', uri: { fsPath: '/workspace' } },
    } as unknown as vscode.DebugSession, undefined);

    expect(descriptor).toMatchObject({ host: '127.0.0.1', port: 9000 });
    expect(spawnMock).not.toHaveBeenCalled();
  });

  it('reuses the main-session bootstrap across concurrent descriptor requests and accepts multiple VS Code clients', async () => {
    const outputChannel = {
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
      debug: vi.fn(),
      trace: vi.fn(),
      show: vi.fn(),
    };
    let resolvePrepare: ((value: { pythonPath: string; needsInstall: boolean }) => void) | undefined;
    (factory as any).envManager.prepareEnvironment = vi.fn(() => new Promise((resolve) => {
      resolvePrepare = resolve;
    }));
    (factory as any).envManager.getOutputChannel = () => outputChannel;
    (factory as any).envManager.showOutputChannel = vi.fn();
    const createTerminalSpy = vi.spyOn(vscode.window, 'createTerminal');

    const firstDescriptorPromise = factory.createDebugAdapterDescriptor({
      id: 'launch-session-1',
      type: 'dapper',
      name: 'Launch One',
      configuration: {
        type: 'dapper',
        request: 'launch',
        name: 'Launch One',
        program: 'main.py',
      },
      workspaceFolder: { name: 'workspace', uri: { fsPath: '/workspace' } },
    } as unknown as vscode.DebugSession, undefined);

    const secondDescriptorPromise = factory.createDebugAdapterDescriptor({
      id: 'launch-session-2',
      type: 'dapper',
      name: 'Launch Two',
      configuration: {
        type: 'dapper',
        request: 'launch',
        name: 'Launch Two',
        program: 'other.py',
      },
      workspaceFolder: { name: 'workspace', uri: { fsPath: '/workspace' } },
    } as unknown as vscode.DebugSession, undefined);

    resolvePrepare?.({
      pythonPath: '/usr/bin/python3.14',
      needsInstall: false,
    });

    const [firstDescriptor, secondDescriptor] = await Promise.all([firstDescriptorPromise, secondDescriptorPromise]);
    expect((factory as any).envManager.prepareEnvironment).toHaveBeenCalledTimes(1);
    expect(createTerminalSpy).toHaveBeenCalledTimes(1);
    expect((firstDescriptor as vscode.DebugAdapterServer).port).toBe((secondDescriptor as vscode.DebugAdapterServer).port);

    const firstSocket = Net.createConnection({
      host: '127.0.0.1',
      port: (firstDescriptor as vscode.DebugAdapterServer).port,
    });
    await once(firstSocket, 'connect');

    const secondSocket = Net.createConnection({
      host: '127.0.0.1',
      port: (secondDescriptor as vscode.DebugAdapterServer).port,
    });
    await once(secondSocket, 'connect');

    firstSocket.destroy();
    secondSocket.destroy();
  });

  it('rejects attach sessions that mix host/port with a launch target', async () => {
    await expect(factory.createDebugAdapterDescriptor({
      id: 'attach-session',
      type: 'dapper',
      name: 'Attach Mixed Target',
      configuration: {
        type: 'dapper',
        request: 'attach',
        name: 'Attach Mixed Target',
        host: '127.0.0.1',
        port: 9000,
        program: 'main.py',
      },
      workspaceFolder: { name: 'workspace', uri: { fsPath: '/workspace' } },
    } as unknown as vscode.DebugSession, undefined)).rejects.toThrow(/exactly one target/i);
  });

  it('surfaces structured helper diagnostics for processId attach failures', async () => {
    const outputChannel = {
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
      debug: vi.fn(),
      trace: vi.fn(),
      show: vi.fn(),
    };
    (factory as any).envManager.prepareEnvironment = vi.fn(async () => ({
      pythonPath: '/usr/bin/python3.14',
      needsInstall: false,
    }));
    (factory as any).envManager.getOutputChannel = () => outputChannel;
    (factory as any).envManager.showOutputChannel = vi.fn();

    const child = new EventEmitter() as EventEmitter & {
      stdout: EventEmitter;
      stderr: EventEmitter;
    };
    child.stdout = new EventEmitter();
    child.stderr = new EventEmitter();
    spawnMock.mockImplementation(() => {
      queueMicrotask(() => {
        child.stderr.emit(
          'data',
          Buffer.from(
            'DAPPER_ATTACH_BY_PID_DIAGNOSTIC {"code":"remote_debugging_disabled","message":"The target interpreter has CPython remote debugging disabled.","hint":"Restart the target without PYTHON_DISABLE_REMOTE_DEBUG=1."}\n',
            'utf8',
          ),
        );
        child.emit('close', 1);
      });
      return child;
    });

    const showErrorSpy = vi.spyOn(vscode.window, 'showErrorMessage');

    await expect(factory.createDebugAdapterDescriptor({
      id: 'attach-session',
      type: 'dapper',
      name: 'Attach',
      configuration: {
        type: 'dapper',
        request: 'attach',
        name: 'Attach',
        processId: 4321,
      },
      workspaceFolder: { name: 'workspace', uri: { fsPath: '/workspace' } },
    } as unknown as vscode.DebugSession, undefined)).rejects.toThrow(/remote debugging disabled/i);

    expect(showErrorSpy).toHaveBeenCalledWith(expect.stringMatching(/remote debugging disabled/i));
  });

  it('fails processId attach with a bootstrap timeout when the target never connects back', async () => {
    vi.useFakeTimers();

    const outputChannel = {
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
      debug: vi.fn(),
      trace: vi.fn(),
      show: vi.fn(),
    };
    (factory as any).envManager.prepareEnvironment = vi.fn(async () => ({
      pythonPath: '/usr/bin/python3.14',
      needsInstall: false,
    }));
    (factory as any).envManager.getOutputChannel = () => outputChannel;
    (factory as any).envManager.showOutputChannel = vi.fn();

    const child = new EventEmitter() as EventEmitter & {
      stdout: EventEmitter;
      stderr: EventEmitter;
    };
    child.stdout = new EventEmitter();
    child.stderr = new EventEmitter();
    spawnMock.mockImplementation(() => {
      queueMicrotask(() => child.emit('close', 0));
      return child;
    });

    const showErrorSpy = vi.spyOn(vscode.window, 'showErrorMessage');
    const descriptorPromise = factory.createDebugAdapterDescriptor({
      id: 'attach-session',
      type: 'dapper',
      name: 'Attach',
      configuration: {
        type: 'dapper',
        request: 'attach',
        name: 'Attach',
        processId: 4321,
      },
      workspaceFolder: { name: 'workspace', uri: { fsPath: '/workspace' } },
    } as unknown as vscode.DebugSession, undefined);
    const descriptorExpectation = expect(descriptorPromise).rejects.toThrow(/timed out waiting for process 4321/i);

    await vi.runAllTimersAsync();

    await descriptorExpectation;
    expect(showErrorSpy).toHaveBeenCalledWith(expect.stringMatching(/timed out waiting for process 4321/i));
  });
});