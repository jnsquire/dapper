/**
 * dapper_state — Return either a snapshot or a diff for the active debug state.
 */

import * as vscode from 'vscode';
import type { JournalRegistry } from '../stateJournal.js';
import { resolveSession, jsonResult, errorResult } from '../toolUtils.js';

interface StateToolInput {
  sessionId?: string;
  mode: 'snapshot' | 'diff';
  threadId?: number;
  depth?: number;
  sinceCheckpoint?: number;
}

export class StateTool implements vscode.LanguageModelTool<StateToolInput> {
  constructor(private registry: JournalRegistry) {}

  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<StateToolInput>,
    _token: vscode.CancellationToken,
  ): Promise<vscode.LanguageModelToolResult> {
    const { sessionId, mode, threadId, depth, sinceCheckpoint } = options.input;
    const resolved = resolveSession(this.registry, sessionId);
    if (!resolved) {
      return errorResult('No active Dapper debug session');
    }

    switch (mode) {
      case 'snapshot':
        return this._getSnapshot(resolved, threadId, depth);
      case 'diff':
        return this._getDiff(resolved, threadId, sinceCheckpoint);
      default:
        return errorResult(`Unknown mode: ${mode}`);
    }
  }

  private async _getSnapshot(
    resolved: NonNullable<ReturnType<typeof resolveSession>>,
    threadId?: number,
    depth?: number,
  ): Promise<vscode.LanguageModelToolResult> {
    const { journal, session } = resolved;
    const snapshot = await journal.getSnapshot(threadId);
    if (!snapshot) {
      const errDetail = journal.lastError ? ` Adapter error: ${journal.lastError}` : '';
      return errorResult(`Could not retrieve debug snapshot. Is the debuggee stopped?${errDetail}`);
    }

    if (snapshot.callStack.length === 0) {
      try {
        const args: Record<string, unknown> = { depth: depth ?? 5 };
        if (threadId !== undefined) args['threadId'] = threadId;
        const result = await session.customRequest('dapper/agentSnapshot', args);
        if (result && Array.isArray(result.callStack) && result.callStack.length > 0) {
          return jsonResult(result);
        }
      } catch {
        // Fall through to cached snapshot.
      }
      if (journal.lastError) {
        return jsonResult({ ...snapshot, _adapterError: journal.lastError });
      }
    }

    return jsonResult(snapshot);
  }

  private async _getDiff(
    resolved: NonNullable<ReturnType<typeof resolveSession>>,
    threadId?: number,
    sinceCheckpoint?: number,
  ): Promise<vscode.LanguageModelToolResult> {
    const { journal } = resolved;
    await journal.getSnapshot(threadId);
    return jsonResult(journal.getDiffSince(sinceCheckpoint ?? 0));
  }
}
