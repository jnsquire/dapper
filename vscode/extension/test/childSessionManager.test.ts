import { EventEmitter } from 'events';
import * as Net from 'net';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type * as vscode from 'vscode';
import * as vscodeModule from 'vscode';
import { ChildSessionManager } from '../src/debugAdapter/childSessionManager.js';
import { writeIpcMessage } from '../src/debugAdapter/ipcMessageFraming.js';

function makeOutputChannel(): vscode.LogOutputChannel {
  return {
    trace: vi.fn(),
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    show: vi.fn(),
    hide: vi.fn(),
    dispose: vi.fn(),
    append: vi.fn(),
    appendLine: vi.fn(),
    clear: vi.fn(),
    replace: vi.fn(),
    name: 'Dapper',
  } as unknown as vscode.LogOutputChannel;
}

function makeParentSession(): vscode.DebugSession {
  return {
    id: 'parent-session',
    type: 'dapper',
    name: 'Parent',
    configuration: { type: 'dapper', request: 'launch', program: 'parent.py' },
    workspaceFolder: { name: 'workspace', uri: { fsPath: '/workspace' } },
  } as unknown as vscode.DebugSession;
}

async function listenOnLoopback(server: Net.Server, port: number): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, '127.0.0.1', () => resolve());
  });
}

async function closeServer(server: Net.Server): Promise<void> {
  await new Promise<void>((resolve) => {
    server.close(() => resolve());
  });
}


async function connectToLoopback(port: number): Promise<Net.Socket> {
  return await new Promise<Net.Socket>((resolve, reject) => {
    const socket = Net.createConnection({ host: '127.0.0.1', port }, () => resolve(socket));
    socket.once('error', reject);
  });
}

function writeSessionHello(socket: Net.Socket, sessionId: string): void {
  writeIpcMessage(socket, {
    event: 'dapper/sessionHello',
    body: { sessionId },
  });
}

describe('ChildSessionManager', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('ignores child events that do not advertise the shared listener port', async () => {
    const manager = new ChildSessionManager(() => makeOutputChannel());
    const sharedPort = await manager.ensureSharedListenerPort();

    await manager.handleChildProcessEvent(makeParentSession(), {
      sessionId: 'child-launcher-session',
      pid: 4242,
      ipcPort: sharedPort + 1,
      name: 'subprocess_child.py',
    });

    expect(manager.hasPendingChildSession('child-launcher-session')).toBe(false);
    expect(manager.getPendingChildSessionIdForPid(4242)).toBeUndefined();
  });

  it('reuses one shared listener across multiple child sessions', async () => {
    let serverCreationCount = 0;
    const createServer: typeof Net.createServer = ((
      optionsOrListener?: Net.ServerOpts | ((socket: Net.Socket) => void),
      maybeListener?: (socket: Net.Socket) => void,
    ) => {
      serverCreationCount += 1;
      return typeof optionsOrListener === 'function'
        ? Net.createServer(optionsOrListener)
        : Net.createServer(optionsOrListener, maybeListener);
    }) as typeof Net.createServer;

    const manager = new ChildSessionManager(() => makeOutputChannel(), createServer);
    const sharedPort = await manager.ensureSharedListenerPort();
    const parentSession = makeParentSession();

    await manager.handleChildProcessEvent(parentSession, {
      sessionId: 'child-launcher-session',
      pid: 4242,
      ipcPort: sharedPort,
      name: 'subprocess_child.py',
    });
    await manager.handleChildProcessEvent(parentSession, {
      sessionId: 'child-launcher-session-2',
      pid: 4343,
      ipcPort: sharedPort,
      name: 'subprocess_child_2.py',
    });

    expect(serverCreationCount).toBe(1);
    expect(manager.hasPendingChildSession('child-launcher-session')).toBe(true);
    expect(manager.hasPendingChildSession('child-launcher-session-2')).toBe(true);
  });

  it('cleans up pending state when adapter-server startup fails', async () => {
    const outputChannel = makeOutputChannel();
    const fakeServer = new EventEmitter() as Net.Server & EventEmitter;
    fakeServer.listen = vi.fn((_port: number, _host: string) => {
      queueMicrotask(() => {
        fakeServer.emit('error', new Error('adapter bind failed'));
      });
      return fakeServer;
    }) as unknown as Net.Server['listen'];
    fakeServer.close = vi.fn();
    fakeServer.address = vi.fn(() => ({ port: 0, address: '127.0.0.1', family: 'IPv4' }));

    let serverCreationCount = 0;
    const createServer: typeof Net.createServer = ((
      optionsOrListener?: Net.ServerOpts | ((socket: Net.Socket) => void),
      maybeListener?: (socket: Net.Socket) => void,
    ) => {
      serverCreationCount += 1;
      if (serverCreationCount === 1) {
        return typeof optionsOrListener === 'function'
          ? Net.createServer(optionsOrListener)
          : Net.createServer(optionsOrListener, maybeListener);
      }
      return fakeServer as unknown as Net.Server;
    }) as typeof Net.createServer;

    const manager = new ChildSessionManager(() => outputChannel, createServer);
    const startDebugging = vi.spyOn(vscodeModule.debug, 'startDebugging').mockResolvedValue(true);
    const sharedPort = await manager.ensureSharedListenerPort();

    await manager.handleChildProcessEvent(makeParentSession(), {
      sessionId: 'child-launcher-session',
      pid: 4242,
      ipcPort: sharedPort,
      name: 'subprocess_child.py',
    });

    const socket = await connectToLoopback(sharedPort);
    writeSessionHello(socket, 'child-launcher-session');
    await vi.waitFor(() => {
      expect(startDebugging).toHaveBeenCalled();
    });

    await expect(manager.createChildDebugAdapterDescriptor({
      id: 'child-vscode-session',
      type: 'dapper',
      name: 'Child',
      configuration: {
        type: 'dapper',
        request: 'launch',
        name: 'Child',
        __dapperIsChildSession: true,
        __dapperChildSessionId: 'child-launcher-session',
        __dapperChildPid: 4242,
        __dapperChildName: 'subprocess_child.py',
        __dapperParentDebugSessionId: 'parent-session',
        __dapperChildIpcPort: sharedPort,
      },
    } as unknown as vscode.DebugSession, {
      type: 'dapper',
      request: 'launch',
      name: 'Child',
      __dapperIsChildSession: true,
      __dapperChildSessionId: 'child-launcher-session',
      __dapperChildPid: 4242,
      __dapperChildName: 'subprocess_child.py',
      __dapperParentDebugSessionId: 'parent-session',
      __dapperChildIpcPort: sharedPort,
    })).rejects.toThrow(/adapter bind failed/i);

    socket.destroy();

    expect(manager.hasPendingChildSession('child-launcher-session')).toBe(false);
    expect(manager.getPendingChildSessionIdForPid(4242)).toBeUndefined();
    expect(outputChannel.debug).toHaveBeenCalled();
  });
});