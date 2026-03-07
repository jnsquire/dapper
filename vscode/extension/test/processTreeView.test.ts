import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import * as vscode from 'vscode';
import { DapperProcessTreeProvider } from '../src/views/DapperProcessTreeView.js';
import { fireDebugEvent, resetDebugListeners } from './__mocks__/vscode.mjs';

function createMemento(initial: Record<string, unknown> = {}): vscode.Memento {
  const store = new Map<string, unknown>(Object.entries(initial));
  return {
    get<T>(key: string, defaultValue?: T): T | undefined {
      return store.has(key) ? (store.get(key) as T | undefined) : defaultValue;
    },
    async update(key: string, value: unknown): Promise<void> {
      store.set(key, value);
    },
    keys(): readonly string[] {
      return [...store.keys()];
    },
  } as unknown as vscode.Memento;
}

describe('DapperProcessTreeProvider', () => {
  let provider: DapperProcessTreeProvider;

  beforeEach(() => {
    resetDebugListeners();
    provider = new DapperProcessTreeProvider();
  });

  afterEach(() => {
    provider.dispose();
    resetDebugListeners();
  });

  it('groups child sessions under their parent and updates process metadata', () => {
    const parentSession = {
      id: 'parent-session',
      type: 'dapper',
      name: 'Parent Launch',
      configuration: { type: 'dapper', request: 'launch', program: 'parent.py' },
    } as unknown as vscode.DebugSession;
    const childSession = {
      id: 'child-session',
      type: 'dapper',
      name: 'Dapper Child: subprocess_child.py (4242)',
      configuration: {
        type: 'dapper',
        request: 'launch',
        __dapperParentDebugSessionId: 'parent-session',
      },
      parentSession,
    } as unknown as vscode.DebugSession;

    fireDebugEvent('onDidStartDebugSession', parentSession);
    fireDebugEvent('onDidStartDebugSession', childSession);
    fireDebugEvent('onDidReceiveDebugSessionCustomEvent', {
      session: childSession,
      event: 'process',
      body: {
        name: 'subprocess_child.py',
        systemProcessId: 4242,
        startMethod: 'launch',
      },
    });

    const roots = provider.getChildren();
    expect(roots).toHaveLength(1);
    expect(roots[0]).toMatchObject({ kind: 'session', sessionId: 'parent-session' });

    const children = provider.getChildren(roots[0]);
    expect(children).toHaveLength(1);
    expect(children[0]).toMatchObject({ kind: 'session', sessionId: 'child-session' });

    const childItem = provider.getTreeItem(children[0]);
    expect(childItem.label).toBe('subprocess_child.py');
    expect(childItem.description).toContain('pid 4242');
    expect(childItem.tooltip).toContain('Parent session: parent-session');
  });

  it('promotes children to the root when the parent session terminates', () => {
    const parentSession = {
      id: 'parent-session',
      type: 'dapper',
      name: 'Parent Launch',
      configuration: { type: 'dapper', request: 'launch', program: 'parent.py' },
    } as unknown as vscode.DebugSession;
    const childSession = {
      id: 'child-session',
      type: 'dapper',
      name: 'Child Launch',
      configuration: {
        type: 'dapper',
        request: 'launch',
        __dapperParentDebugSessionId: 'parent-session',
      },
      parentSession,
    } as unknown as vscode.DebugSession;

    fireDebugEvent('onDidStartDebugSession', parentSession);
    fireDebugEvent('onDidStartDebugSession', childSession);
    fireDebugEvent('onDidTerminateDebugSession', parentSession);

    const roots = provider.getChildren();
    expect(roots).toHaveLength(1);
    expect(roots[0]).toMatchObject({ kind: 'session', sessionId: 'child-session' });
  });

  it('persists tracked pids and renders them as standalone tree items', async () => {
    const state = createMemento({ 'dapper.processTree.trackedPids': [4321] });
    const trackedProvider = new DapperProcessTreeProvider(state);

    expect(trackedProvider.getChildren()).toContainEqual({ kind: 'trackedPid', pid: 4321 });

    const added = await trackedProvider.addTrackedPid(1234);
    expect(added).toBe(true);
    expect(trackedProvider.getChildren()).toContainEqual({ kind: 'trackedPid', pid: 1234 });

    const trackedItem = trackedProvider.getTreeItem({ kind: 'trackedPid', pid: 1234 });
    expect(trackedItem.label).toBe('Tracked PID 1234');
    expect(trackedItem.description).toBe('manual target');

    const removed = await trackedProvider.removeTrackedPid(1234);
    expect(removed).toBe(true);
    expect(trackedProvider.getChildren()).not.toContainEqual({ kind: 'trackedPid', pid: 1234 });

    trackedProvider.dispose();
  });

  it('marks tracked pids as attached when a matching session is present', async () => {
    const state = createMemento();
    const trackedProvider = new DapperProcessTreeProvider(state);
    await trackedProvider.addTrackedPid(4242);

    const session = {
      id: 'child-session',
      type: 'dapper',
      name: 'Child Launch',
      configuration: { type: 'dapper', request: 'launch' },
    } as unknown as vscode.DebugSession;

    fireDebugEvent('onDidStartDebugSession', session);
    fireDebugEvent('onDidReceiveDebugSessionCustomEvent', {
      session,
      event: 'process',
      body: { name: 'subprocess_child.py', systemProcessId: 4242, startMethod: 'launch' },
    });

    const trackedItem = trackedProvider.getTreeItem({ kind: 'trackedPid', pid: 4242 });
    expect(trackedItem.description).toContain('attached');

    trackedProvider.dispose();
  });
});