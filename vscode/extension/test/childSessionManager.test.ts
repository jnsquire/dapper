import { EventEmitter } from 'events';
import * as Net from 'net';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type * as vscode from 'vscode';
import { ChildSessionManager } from '../src/debugAdapter/childSessionManager.js';

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

describe('ChildSessionManager', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('cleans up pending state when the child listener cannot bind', async () => {
    const blocker = Net.createServer();
    await listenOnLoopback(blocker, 0);
    const address = blocker.address();
    if (!address || typeof address === 'string') {
      throw new Error('failed to bind blocker server');
    }

    const manager = new ChildSessionManager(() => makeOutputChannel());

    await expect(manager.handleChildProcessEvent(makeParentSession(), {
      sessionId: 'child-launcher-session',
      pid: 4242,
      ipcPort: address.port,
      name: 'subprocess_child.py',
    })).rejects.toThrow();

    expect(manager.childSessions.has('child-launcher-session')).toBe(false);
    expect(manager.childSessionIdsByPid.has(4242)).toBe(false);

    await new Promise<void>((resolve) => blocker.close(() => resolve()));
  });

  it('drops a child session that exits while its listener is still binding', async () => {
    const fakeServer = new EventEmitter() as Net.Server & EventEmitter;
    fakeServer.listen = vi.fn((_port: number, _host: string) => {
      queueMicrotask(() => {
        fakeServer.emit('listening');
      });
      return fakeServer;
    }) as unknown as Net.Server['listen'];
    fakeServer.close = vi.fn();
    fakeServer.address = vi.fn(() => ({ port: 9001, address: '127.0.0.1', family: 'IPv4' }));

    const manager = new ChildSessionManager(() => makeOutputChannel(), () => fakeServer);
    const parentSession = makeParentSession();
    const promise = manager.handleChildProcessEvent(parentSession, {
      sessionId: 'child-launcher-session',
      pid: 4242,
      ipcPort: 9001,
      name: 'subprocess_child.py',
    });

    manager.handleChildProcessExitedEvent({
      sessionId: 'child-launcher-session',
      pid: 4242,
    });

    await promise;

    expect(manager.childSessions.has('child-launcher-session')).toBe(false);
    expect(manager.childSessionIdsByPid.has(4242)).toBe(false);
    expect(fakeServer.close).toHaveBeenCalled();
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

    const manager = new ChildSessionManager(() => outputChannel, () => fakeServer);

    manager.childSessions.set('child-launcher-session', {
      launcherSessionId: 'child-launcher-session',
      pid: 4242,
      name: 'subprocess_child.py',
      ipcPort: 9001,
      parentDebugSessionId: 'parent-session',
      parentSession: makeParentSession(),
      socket: { destroy: vi.fn(), destroyed: false } as unknown as Net.Socket,
    });
    manager.childSessionIdsByPid.set(4242, 'child-launcher-session');

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
        __dapperChildIpcPort: 9001,
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
      __dapperChildIpcPort: 9001,
    })).rejects.toThrow(/adapter bind failed/i);

    expect(manager.childSessions.has('child-launcher-session')).toBe(false);
    expect(manager.childSessionIdsByPid.has(4242)).toBe(false);
    expect(outputChannel.debug).toHaveBeenCalled();
  });
});