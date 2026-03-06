import { describe, expect, it, vi } from 'vitest';
import { StateTool } from '../src/agent/tools/state.js';
import type { DebugSnapshot } from '../src/agent/stateJournal.js';

describe('StateTool', () => {
  it('normalizes the returned snapshot threadId to the requested thread', async () => {
    const session = {
      id: 'session-1',
      type: 'dapper',
      customRequest: vi.fn(),
    } as any;

    const journal = {
      getSnapshot: vi.fn(async () => ({
        checkpoint: 2,
        timestamp: Date.now(),
        stopReason: 'exception',
        threadId: 101,
        location: '/workspace/app.py:41 in worker',
        callStack: [{ name: 'worker', file: '/workspace/app.py', line: 41 }],
        locals: {},
        globals: {},
        stoppedThreads: [101, 202],
        runningThreads: [],
      } satisfies DebugSnapshot)),
      lastError: undefined,
      getDiffSince: vi.fn(),
    };

    const registry = {
      resolve: vi.fn(() => journal),
    } as any;

    const vscode = await import('vscode');
    vscode.debug.activeDebugSession = session;

    const tool = new StateTool(registry);
    const result = await tool.invoke({
      input: {
        mode: 'snapshot',
        threadId: 202,
      },
    } as any, { isCancellationRequested: false } as any);

    const text = ((result as any).content ?? []).map((part: { value?: string }) => part.value ?? '').join('');
    const payload = JSON.parse(text);

    expect(payload.threadId).toBe(202);
    expect(journal.getSnapshot).toHaveBeenCalledWith(202);
  });
});