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
});