import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { JournalRegistry } from '../src/agent/stateJournal.js';
import { BreakpointsTool } from '../src/agent/tools/breakpoints.js';

const vscode = await import('vscode');
const vscodeMock = await import('./__mocks__/vscode.mjs');

describe('BreakpointsTool', () => {
  let registry: JournalRegistry;
  let tool: BreakpointsTool;
  const workspaceRoot = '/workspace/project';
  const sourceFile = `${workspaceRoot}/app.py`;

  beforeEach(() => {
    registry = new JournalRegistry();
    tool = new BreakpointsTool(registry);

    Object.defineProperty(vscode.workspace, 'workspaceFolders', {
      configurable: true,
      value: [{ index: 0, name: 'project', uri: vscode.Uri.file(workspaceRoot) }],
    });
  });

  afterEach(() => {
    registry.dispose();
    vscodeMock.resetDebugListeners();
    vi.restoreAllMocks();
  });

  it('uses cached pending verification from the add response when listing breakpoints', async () => {
    const session = {
      id: 'session-1',
      type: 'dapper',
      name: 'Dapper Test',
      configuration: {},
      customRequest: vi.fn(async (command: string) => {
        expect(command).toBe('setBreakpoints');
        return {
          breakpoints: [
            { verified: false, line: 10 },
          ],
        };
      }),
    } as any;
    vscode.debug.activeDebugSession = session;
    registry.getOrCreate(session);

    await invokeBreakpointsTool(tool, { action: 'add', file: sourceFile, lines: [10] });

    const raw = await invokeBreakpointsTool(tool, { action: 'list', file: sourceFile });
    const result = JSON.parse(raw);

    expect(result.breakpoints).toHaveLength(1);
    expect(result.breakpoints[0].verified).toBeUndefined();
    expect(result.breakpoints[0].verificationState).toBe('pending');
    expect(session.customRequest).toHaveBeenCalledTimes(1);
  });

  it('updates cached verification from breakpoint events and preserves explicit rejections', async () => {
    const session = {
      id: 'session-2',
      type: 'dapper',
      name: 'Dapper Test',
      configuration: {},
      customRequest: vi.fn(async () => ({
        breakpoints: [{ verified: false, message: 'No executable code at line 15', line: 15 }],
      })),
    } as any;
    vscode.debug.activeDebugSession = session;
    const journal = registry.getOrCreate(session);

    await invokeBreakpointsTool(tool, { action: 'add', file: sourceFile, lines: [15] });

    let raw = await invokeBreakpointsTool(tool, { action: 'list', file: sourceFile });
    let result = JSON.parse(raw);

    expect(result.breakpoints[0].verified).toBe(false);
    expect(result.breakpoints[0].verificationState).toBe('rejected');
    expect(result.breakpoints[0].verificationMessage).toContain('No executable code');

    journal.onDidSendMessage({
      type: 'event',
      event: 'breakpoint',
      body: {
        reason: 'changed',
        breakpoint: {
          verified: true,
          line: 15,
          source: { path: sourceFile },
        },
      },
    });

    raw = await invokeBreakpointsTool(tool, { action: 'list', file: sourceFile });
    result = JSON.parse(raw);

    expect(result.breakpoints[0].verified).toBe(true);
    expect(result.breakpoints[0].verificationState).toBe('verified');
  });

  it('removes cached verification entries when breakpoints are cleared', async () => {
    const session = {
      id: 'session-3',
      type: 'dapper',
      name: 'Dapper Test',
      configuration: {},
      customRequest: vi.fn(async () => ({
        breakpoints: [{ verified: true, line: 21 }],
      })),
    } as any;
    vscode.debug.activeDebugSession = session;
    registry.getOrCreate(session);

    await invokeBreakpointsTool(tool, { action: 'add', file: sourceFile, lines: [21] });

    let raw = await invokeBreakpointsTool(tool, { action: 'list', file: sourceFile });
    let result = JSON.parse(raw);
    expect(result.breakpoints[0].verificationState).toBe('verified');

    await invokeBreakpointsTool(tool, { action: 'clear', file: sourceFile });

    raw = await invokeBreakpointsTool(tool, { action: 'list', file: sourceFile });
    result = JSON.parse(raw);
    expect(result.breakpoints).toEqual([]);
  });

  it('supports line filtering for list through the public tool API', async () => {
    await invokeBreakpointsTool(tool, { action: 'add', file: sourceFile, lines: [11, 12] });

    const raw = await invokeBreakpointsTool(tool, { action: 'list', file: sourceFile, lines: [12] });
    const result = JSON.parse(raw);

    expect(result).toMatchObject({
      action: 'list',
      count: 1,
      breakpoints: [
        {
          file: 'app.py',
          line: 12,
          enabled: true,
        },
      ],
    });
  });

  it('disables and re-enables breakpoints while keeping the adapter in sync', async () => {
    const session = {
      id: 'session-4',
      type: 'dapper',
      name: 'Dapper Test',
      configuration: {},
      customRequest: vi.fn(async (_command: string, args?: Record<string, unknown>) => ({
        breakpoints: Array.isArray(args?.breakpoints)
          ? (args?.breakpoints as Array<{ line: number }>).map(bp => ({ verified: true, line: bp.line }))
          : [],
      })),
    } as any;
    vscode.debug.activeDebugSession = session;
    registry.getOrCreate(session);

    await invokeBreakpointsTool(tool, { action: 'add', file: sourceFile, lines: [30] });
    expect(vscode.debug.breakpoints[0]).toMatchObject({ enabled: true });

    await invokeBreakpointsTool(tool, { action: 'disable', file: sourceFile, lines: [30] });
    expect(vscode.debug.breakpoints[0]).toMatchObject({ enabled: false });
    expect(session.customRequest).toHaveBeenLastCalledWith('setBreakpoints', {
      source: { path: sourceFile },
      breakpoints: [],
    });

    await invokeBreakpointsTool(tool, { action: 'enable', file: sourceFile, lines: [30] });
    expect(vscode.debug.breakpoints[0]).toMatchObject({ enabled: true });
    expect(session.customRequest).toHaveBeenLastCalledWith('setBreakpoints', {
      source: { path: sourceFile },
      breakpoints: [{ line: 30, condition: undefined, hitCondition: undefined, logMessage: undefined }],
    });
  });
});

async function invokeBreakpointsTool(tool: BreakpointsTool, input: Record<string, unknown>): Promise<string> {
  const result = await tool.invoke({ input } as any, { isCancellationRequested: false } as any);
  const parts = Array.isArray((result as any).content) ? (result as any).content : [];
  return parts.map((part: { value?: string }) => part.value ?? '').join('');
}
