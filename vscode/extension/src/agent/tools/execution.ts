/**
 * dapper_execution — Control execution, optionally waiting for the next stop.
 */

import * as vscode from 'vscode';
import type { JournalRegistry, DebugSnapshot, VariableSnapshot } from '../stateJournal.js';
import { resolveSession, jsonResult, errorResult } from '../toolUtils.js';

interface ExecutionToolInput {
  sessionId?: string;
  action: 'next' | 'stepIn' | 'stepOut' | 'continue' | 'pause' | 'restart' | 'terminate';
  threadId?: number;
  report?: boolean;
}

type ReportableAction = 'next' | 'stepIn' | 'stepOut' | 'continue';

const STOP_TIMEOUT_MS = 15_000;
const REPORTABLE_ACTIONS = new Set<ReportableAction>(['next', 'stepIn', 'stepOut', 'continue']);

function isReportableAction(action: ExecutionToolInput['action']): action is ReportableAction {
  return REPORTABLE_ACTIONS.has(action as ReportableAction);
}

export class ExecutionTool implements vscode.LanguageModelTool<ExecutionToolInput> {
  constructor(private registry: JournalRegistry) {}

  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<ExecutionToolInput>,
    token: vscode.CancellationToken,
  ): Promise<vscode.LanguageModelToolResult> {
    const { sessionId, action, threadId, report } = options.input;
    const resolved = resolveSession(this.registry, sessionId);
    if (!resolved) {
      return errorResult('No active Dapper debug session');
    }

    if (report) {
      if (!isReportableAction(action)) {
        return errorResult(`Action '${action}' does not support report=true`);
      }
      return this._executeAndReport(resolved, action, threadId, token);
    }
    return this._executeOnly(resolved.session, action, threadId);
  }

  private async _executeOnly(
    session: vscode.DebugSession,
    action: ExecutionToolInput['action'],
    threadId?: number,
  ): Promise<vscode.LanguageModelToolResult> {
    const args: Record<string, unknown> = {};
    if (threadId !== undefined && (action === 'next' || action === 'stepIn' || action === 'stepOut' || action === 'continue' || action === 'pause')) {
      args['threadId'] = threadId;
    }

    try {
      await session.customRequest(action, args);
    } catch (err) {
      return errorResult(`${action} failed: ${err}`);
    }

    const statusByAction: Record<ExecutionToolInput['action'], string> = {
      next: 'stepping',
      stepIn: 'stepping',
      stepOut: 'stepping',
      continue: 'running',
      pause: 'pausing',
      restart: 'restarting',
      terminate: 'terminating',
    };

    return jsonResult({ action, status: statusByAction[action] });
  }

  private async _executeAndReport(
    resolved: NonNullable<ReturnType<typeof resolveSession>>,
    action: ReportableAction,
    threadId: number | undefined,
    token: vscode.CancellationToken,
  ): Promise<vscode.LanguageModelToolResult> {
    const { session, journal } = resolved;
    const checkpointBefore = journal.checkpoint;
    const beforeSnapshot = await journal.getSnapshot(threadId);

    const args: Record<string, unknown> = {};
    if (threadId !== undefined) {
      args['threadId'] = threadId;
    }

    try {
      await session.customRequest(action, args);
    } catch (err) {
      return errorResult(`Action '${action}' failed: ${err}`);
    }

    const stopped = await this._waitForStop(journal, checkpointBefore, token);
    const afterSnapshot = stopped ? await journal.getSnapshot(threadId) : undefined;
    const diff = this._computeDiff(beforeSnapshot, afterSnapshot, journal, checkpointBefore);

    return jsonResult({
      action,
      report: true,
      stopped,
      checkpointBefore,
      checkpointAfter: journal.checkpoint,
      snapshot: afterSnapshot ?? null,
      diff,
    });
  }

  private _computeDiff(
    before: DebugSnapshot | undefined,
    after: DebugSnapshot | undefined,
    journal: { getRecentHistory: (n: number) => Array<{ type: string; summary: string; checkpoint: number }> },
    sinceCheckpoint: number,
  ): {
    locationChanged?: string;
    variableChanges: {
      added: VariableSnapshot;
      changed: Record<string, { old: string; new: string }>;
      removed: string[];
    };
    newOutput: string;
  } {
    const diff: ReturnType<ExecutionTool['_computeDiff']> = {
      variableChanges: { added: {}, changed: {}, removed: [] },
      newOutput: '',
    };

    const newEntries = journal.getRecentHistory(50).filter(e => e.checkpoint > sinceCheckpoint);
    diff.newOutput = newEntries
      .filter(e => e.type === 'output')
      .map(e => e.summary)
      .join('');

    if (!before || !after) return diff;

    if (before.location !== after.location) {
      diff.locationChanged = `${before.location} -> ${after.location}`;
    }

    const prevLocals = before.locals;
    const currLocals = after.locals;
    for (const [name, value] of Object.entries(currLocals)) {
      if (!(name in prevLocals)) {
        diff.variableChanges.added[name] = value;
      } else if (prevLocals[name] !== value) {
        diff.variableChanges.changed[name] = { old: prevLocals[name], new: value };
      }
    }
    for (const name of Object.keys(prevLocals)) {
      if (!(name in currLocals)) {
        diff.variableChanges.removed.push(name);
      }
    }

    return diff;
  }

  private _waitForStop(
    journal: { checkpoint: number; getRecentHistory: (n: number) => Array<{ type: string; checkpoint: number }> },
    sinceCheckpoint: number,
    token: vscode.CancellationToken,
  ): Promise<boolean> {
    return new Promise<boolean>((resolve) => {
      const startTime = Date.now();

      const check = () => {
        if (token.isCancellationRequested) {
          resolve(false);
          return;
        }

        const recent = journal.getRecentHistory(20);
        const hasNewStopped = recent.some(
          e => e.type === 'stopped' && e.checkpoint > sinceCheckpoint,
        );
        if (hasNewStopped) {
          resolve(true);
          return;
        }

        const hasTerminated = recent.some(
          e => e.type === 'terminated' && e.checkpoint > sinceCheckpoint,
        );
        if (hasTerminated) {
          resolve(false);
          return;
        }

        if (Date.now() - startTime > STOP_TIMEOUT_MS) {
          resolve(false);
          return;
        }

        setTimeout(check, 100);
      };

      setTimeout(check, 50);
    });
  }
}
