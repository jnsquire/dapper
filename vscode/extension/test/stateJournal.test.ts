import * as vscode from 'vscode';
import { describe, expect, it, vi } from 'vitest';
import { StateJournal } from '../src/agent/stateJournal.js';

describe('StateJournal', () => {
  it('uses the selected thread id returned by agentSnapshot', async () => {
    const session = {
      id: 'session-1',
      customRequest: vi.fn(async () => ({
        stopReason: 'pause',
        threadId: 22,
        location: '/workspace/app.py:17 in worker',
        callStack: [{ name: 'worker', file: '/workspace/app.py', line: 17 }],
        locals: { value: '42' },
        globals: {},
        stoppedThreads: [11, 22],
        runningThreads: [],
      })),
    } as any;

    const journal = new StateJournal(session);
    const snapshot = await journal.getSnapshot(22);

    expect(snapshot?.threadId).toBe(22);
    expect(session.customRequest).toHaveBeenCalledWith('dapper/agentSnapshot', { threadId: 22 });
  });

  it('falls back to the requested thread id when older adapters omit it', async () => {
    const session = {
      id: 'session-2',
      customRequest: vi.fn(async () => ({
        stopReason: 'pause',
        location: '/workspace/app.py:17 in worker',
        callStack: [{ name: 'worker', file: '/workspace/app.py', line: 17 }],
        locals: {},
        globals: {},
        stoppedThreads: [11, 22],
        runningThreads: [],
      })),
    } as any;

    const journal = new StateJournal(session);
    const snapshot = await journal.getSnapshot(22);

    expect(snapshot?.threadId).toBe(22);
  });

  it('captures a real snapshot for stopped events in journal history', async () => {
    const session = {
      id: 'session-3',
      customRequest: vi.fn(async () => ({
        stopReason: 'breakpoint',
        threadId: 11,
        location: '/workspace/app.py:23 in worker',
        callStack: [{ name: 'worker', file: '/workspace/app.py', line: 23 }],
        locals: { counter: '3' },
        globals: { DEBUG: 'True' },
        stoppedThreads: [11],
        runningThreads: [9],
      })),
    } as any;

    const journal = new StateJournal(session);
    journal.onDidSendMessage({
      type: 'event',
      event: 'stopped',
      body: { threadId: 11, reason: 'breakpoint' },
    });

    await vi.waitFor(() => {
      expect(journal.lastSnapshot?.callStack).toEqual([
        { name: 'worker', file: '/workspace/app.py', line: 23 },
      ]);
    });

    const history = journal.getRecentHistory(1);
    expect(history).toHaveLength(1);
    expect(history[0].snapshot).toMatchObject({
      checkpoint: 1,
      stopReason: 'breakpoint',
      threadId: 11,
      location: '/workspace/app.py:23 in worker',
      locals: { counter: '3' },
      globals: { DEBUG: 'True' },
      stoppedThreads: [11],
      runningThreads: [9],
    });
    expect(session.customRequest).toHaveBeenCalledWith('dapper/agentSnapshot', { threadId: 11 });
  });

  it('does not let an older stop snapshot overwrite a newer one', async () => {
    let resolveFirst: ((value: unknown) => void) | undefined;
    let resolveSecond: ((value: unknown) => void) | undefined;
    const session = {
      id: 'session-4',
      customRequest: vi.fn((_: string, args: { threadId?: number }) => new Promise((resolve) => {
        if (args.threadId === 11) {
          resolveFirst = resolve;
          return;
        }
        resolveSecond = resolve;
      })),
    } as any;

    const journal = new StateJournal(session);
    journal.onDidSendMessage({
      type: 'event',
      event: 'stopped',
      body: { threadId: 11, reason: 'breakpoint' },
    });
    journal.onDidSendMessage({
      type: 'event',
      event: 'stopped',
      body: { threadId: 22, reason: 'step' },
    });

    resolveSecond?.({
      stopReason: 'step',
      threadId: 22,
      location: '/workspace/app.py:40 in worker_two',
      callStack: [{ name: 'worker_two', file: '/workspace/app.py', line: 40 }],
      locals: { value: '2' },
      globals: {},
      stoppedThreads: [22],
      runningThreads: [],
    });

    await vi.waitFor(() => {
      expect(journal.lastSnapshot?.threadId).toBe(22);
      expect(journal.lastSnapshot?.checkpoint).toBe(2);
    });

    resolveFirst?.({
      stopReason: 'breakpoint',
      threadId: 11,
      location: '/workspace/app.py:12 in worker_one',
      callStack: [{ name: 'worker_one', file: '/workspace/app.py', line: 12 }],
      locals: { value: '1' },
      globals: {},
      stoppedThreads: [11],
      runningThreads: [],
    });

    await vi.waitFor(() => {
      const history = journal.getRecentHistory(2);
      expect(history[0].snapshot).toMatchObject({ checkpoint: 1, threadId: 11 });
      expect(history[1].snapshot).toMatchObject({ checkpoint: 2, threadId: 22 });
    });

    expect(journal.lastSnapshot).toMatchObject({
      checkpoint: 2,
      threadId: 22,
      location: '/workspace/app.py:40 in worker_two',
    });
  });

  it('uses the configured execution history size for the ring buffer', () => {
    const configSpy = vi.spyOn(vscode.workspace, 'getConfiguration').mockReturnValue({
      get: vi.fn((key: string, defaultValue: unknown) => (
        key === 'agent.executionHistorySize' ? 10 : defaultValue
      )),
    } as any);

    try {
      const session = {
        id: 'session-5',
        customRequest: vi.fn(),
      } as any;

      const journal = new StateJournal(session);
      for (let index = 0; index < 10; index++) {
        journal.onDidSendMessage({
          type: 'event',
          event: 'thread',
          body: { threadId: index + 1, reason: 'started' },
        });
      }
      journal.onDidSendMessage({ type: 'event', event: 'terminated', body: {} });

      const history = journal.getRecentHistory(20);
      expect(history).toHaveLength(10);
      expect(history[0].summary).toBe('Thread 2 started');
      expect(history.at(-1)?.type).toBe('terminated');
      expect(history.map(entry => entry.type)).toEqual([
        'thread',
        'thread',
        'thread',
        'thread',
        'thread',
        'thread',
        'thread',
        'thread',
        'thread',
        'terminated',
      ]);
    } finally {
      configSpy.mockRestore();
    }
  });
});