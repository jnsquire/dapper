import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { JournalRegistry } from '../src/agent/stateJournal.js';
import { GetSessionInfoTool, buildSessionStatus } from '../src/agent/tools/getSessionInfo.js';

const vscode = await import('vscode');
const vscodeMock = await import('./__mocks__/vscode.mjs');

describe('GetSessionInfoTool', () => {
  let registry: JournalRegistry;
  let tool: GetSessionInfoTool;

  beforeEach(() => {
    registry = new JournalRegistry();
    tool = new GetSessionInfoTool(registry);
  });

  afterEach(() => {
    registry.dispose();
    vscodeMock.resetDebugListeners();
    vi.restoreAllMocks();
  });

  it('includes readiness information for the active session', async () => {
    const session = {
      id: 'session-info',
      type: 'dapper',
      name: 'Info Session',
      configuration: {
        request: 'launch',
        program: '/workspace/project/app.py',
      },
      customRequest: vi.fn(),
    } as any;
    vscode.debug.activeDebugSession = session;

    const journal = registry.getOrCreate(session);
    journal.updateBreakpointVerification('/workspace/project/app.py', 10, {
      verificationState: 'verified',
      verified: true,
    });

    const payload = await invokeTool(tool, {});

    expect(payload.sessions).toHaveLength(1);
    expect(payload.sessions[0]).toMatchObject({
      id: 'session-info',
      lifecycleState: 'ready',
      breakpointRegistrationComplete: true,
      readyToContinue: true,
    });
  });

  it('returns structured readiness and breakpoint status for a specific session', async () => {
    const session = {
      id: 'session-1',
      type: 'dapper',
      name: 'Dapper Test',
      configuration: {
        request: 'launch',
        program: '/workspace/project/app.py',
        cwd: '/workspace/project',
        stopOnEntry: true,
      },
      customRequest: vi.fn(),
    } as any;
    vscode.debug.activeDebugSession = session;

    const journal = registry.getOrCreate(session);
    journal.updateBreakpointVerification('/workspace/project/app.py', 10, {
      verificationState: 'verified',
      verified: true,
    });
    journal.updateBreakpointVerification('/workspace/project/app.py', 12, {
      verificationState: 'pending',
    });

    const payload = await invokeTool(tool, { sessionId: 'session-1' });

    expect(payload).toMatchObject({
      id: 'session-1',
      lifecycleState: 'waiting-for-breakpoints',
      breakpointRegistrationComplete: false,
      readyToContinue: false,
      breakpoints: {
        accepted: 1,
        pending: 1,
        rejected: 0,
      },
    });
    expect(payload.breakpoints.details.accepted).toHaveLength(1);
    expect(payload.breakpoints.details.pending).toHaveLength(1);
  });

  it('reports an error when there is no active dapper session', async () => {
    const result = await tool.invoke({ input: {} } as any, {} as any);
    const text = ((result as any).content ?? []).map((part: { value?: string }) => part.value ?? '').join('');

    expect(text).toBe('Error: No active Dapper debug sessions');
  });

  it('marks the session ready when breakpoints are complete and no error exists', () => {
    const session = {
      id: 'session-2',
      type: 'dapper',
      name: 'Ready Session',
      configuration: {
        request: 'attach',
        module: 'pkg.app',
      },
      customRequest: vi.fn(),
    } as any;

    const journal = registry.getOrCreate(session);
    journal.updateBreakpointVerification('/workspace/project/app.py', 14, {
      verificationState: 'verified',
      verified: true,
    });

    const payload = buildSessionStatus(session, journal);

    expect(payload).toMatchObject({
      lifecycleState: 'ready',
      breakpointRegistrationComplete: true,
      readyToContinue: true,
      breakpoints: {
        accepted: 1,
        pending: 0,
        rejected: 0,
      },
      program: 'pkg.app',
    });
  });
});

async function invokeTool(tool: GetSessionInfoTool, input: Record<string, unknown>): Promise<any> {
  const result = await tool.invoke({ input } as any, {} as any);
  const text = ((result as any).content ?? []).map((part: { value?: string }) => part.value ?? '').join('');
  return JSON.parse(text);
}