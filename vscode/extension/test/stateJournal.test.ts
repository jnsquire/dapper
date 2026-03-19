import * as vscode from 'vscode';
import { describe, expect, it, vi } from 'vitest';
import { StateJournal } from '../src/agent/stateJournal.js';

describe('StateJournal', () => {
  it('starts in initializing state with incomplete breakpoint registration', () => {
    const session = {
      id: 'session-initial',
      customRequest: vi.fn(),
    } as any;

    const journal = new StateJournal(session);

    expect(journal.readinessInfo).toMatchObject({
      lifecycleState: 'initializing',
      breakpointRegistrationComplete: false,
      lastTransition: {
        state: 'initializing',
        reason: 'Debug session created',
      },
    });
  });

  it('tracks breakpoint registration completion from pending to verified', () => {
    const session = {
      id: 'session-breakpoints',
      customRequest: vi.fn(),
    } as any;

    const journal = new StateJournal(session);

    journal.updateBreakpointVerification('/workspace/app.py', 10, {
      verificationState: 'pending',
    });

    expect(journal.readinessInfo).toMatchObject({
      lifecycleState: 'waiting-for-breakpoints',
      breakpointRegistrationComplete: false,
    });

    journal.updateBreakpointVerification('/workspace/app.py', 10, {
      verificationState: 'verified',
      verified: true,
    });

    expect(journal.readinessInfo).toMatchObject({
      lifecycleState: 'ready',
      breakpointRegistrationComplete: true,
      lastTransition: {
        state: 'ready',
        reason: 'Breakpoint verification updated for /workspace/app.py:10',
      },
    });
  });

  it('records snapshot failures as errors and clears them after recovery', async () => {
    const session = {
      id: 'session-error-recovery',
      customRequest: vi.fn()
        .mockRejectedValueOnce(new Error('adapter offline'))
        .mockResolvedValueOnce({
          stopReason: 'pause',
          threadId: 7,
          location: '/workspace/app.py:17 in worker',
          callStack: [{ name: 'worker', file: '/workspace/app.py', line: 17 }],
          locals: { value: '42' },
          globals: {},
          stoppedThreads: [7],
          runningThreads: [],
        }),
    } as any;

    const journal = new StateJournal(session);

    const failedSnapshot = await journal.getSnapshot(7);
    expect(failedSnapshot).toBeUndefined();
    expect(journal.readinessInfo).toMatchObject({
      lifecycleState: 'error',
      lastError: 'adapter offline',
      lastTransition: {
        state: 'error',
        reason: 'Failed to retrieve debug snapshot',
      },
    });

    journal.onDidSendMessage({
      type: 'event',
      event: 'stopped',
      body: { threadId: 7, reason: 'pause' },
    });

    await vi.waitFor(() => {
      expect(journal.readinessInfo).toMatchObject({
        lifecycleState: 'stopped',
        lastError: undefined,
      });
    });
  });

  it('reports aggregate breakpoint status counts', () => {
    const session = {
      id: 'session-counts',
      customRequest: vi.fn(),
    } as any;

    const journal = new StateJournal(session);
    journal.updateBreakpointVerification('/workspace/app.py', 3, {
      verificationState: 'verified',
      verified: true,
    });
    journal.updateBreakpointVerification('/workspace/app.py', 4, {
      verificationState: 'pending',
    });
    journal.updateBreakpointVerification('/workspace/app.py', 5, {
      verificationState: 'rejected',
      verified: false,
      verificationMessage: 'No executable code at line 5',
    });

    expect(journal.getBreakpointStatusCounts()).toEqual({
      verified: 1,
      pending: 1,
      rejected: 1,
    });
  });

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