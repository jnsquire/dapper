import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as Net from 'net';
import * as vscode from 'vscode';
import { once } from 'events';
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
    factory = new DapperDebugAdapterDescriptorFactory({
      extension: { packageJSON: { version: '0.9.0' } },
      globalStorageUri: { fsPath: '/tmp/dapper-tests' },
    } as unknown as vscode.ExtensionContext);
  });

  afterEach(() => {
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
      expect((factory as any)._childSessions.get('child-launcher-session')?.listener).toBeDefined();
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
    expect((factory as any)._childSessions.get('child-launcher-session')?.vscodeSessionId).toBe('child-vscode-session');

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
      expect((factory as any)._childSessions.has('child-launcher-session')).toBe(true);
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
      expect((factory as any)._childSessions.has('child-launcher-session')).toBe(false);
      expect((factory as any)._childSessionIdsByPid.has(4242)).toBe(false);
    });
  });
});