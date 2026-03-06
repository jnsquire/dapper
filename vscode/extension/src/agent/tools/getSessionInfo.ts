/**
 * dapper_session_info — Get metadata about active debug sessions.
 */

import * as vscode from 'vscode';
import type { JournalRegistry } from '../stateJournal.js';
import { jsonResult, errorResult } from '../toolUtils.js';

interface GetSessionInfoInput {
  sessionId?: string;
}

interface SessionInfo {
  id: string;
  name: string;
  type: string;
  state: 'running' | 'stopped' | 'unknown';
  program?: string;
  checkpoint: number;
  breakpointCount: number;
  configuration: Record<string, unknown>;
}

export class GetSessionInfoTool implements vscode.LanguageModelTool<GetSessionInfoInput> {
  constructor(private registry: JournalRegistry) {}

  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<GetSessionInfoInput>,
    _token: vscode.CancellationToken,
  ): Promise<vscode.LanguageModelToolResult> {
    const { sessionId } = options.input;

    // Count breakpoints for any session
    const bpCount = vscode.debug.breakpoints.length;

    if (sessionId) {
      // Info for a specific session
      const journal = this.registry.resolve(sessionId);
      const session = vscode.debug.activeDebugSession?.id === sessionId
        ? vscode.debug.activeDebugSession
        : undefined;

      if (!session) {
        return errorResult(`Session not found: ${sessionId}`);
      }

      const info = this._buildSessionInfo(session, journal?.checkpoint ?? 0, bpCount);
      return jsonResult(info);
    }

    // List all tracked sessions
    const sessions: SessionInfo[] = [];
    for (const [id, journal] of this.registry.journals) {
      const active = vscode.debug.activeDebugSession;
      if (active?.id === id) {
        sessions.push(this._buildSessionInfo(active, journal.checkpoint, bpCount));
      } else {
        sessions.push({
          id,
          name: `Dapper session ${id.slice(0, 8)}`,
          type: 'dapper',
          state: 'unknown',
          checkpoint: journal.checkpoint,
          breakpointCount: bpCount,
          configuration: {},
        });
      }
    }

    if (sessions.length === 0) {
      // Check if there's an active session not yet tracked
      const active = vscode.debug.activeDebugSession;
      if (active?.type === 'dapper') {
        sessions.push(this._buildSessionInfo(active, 0, bpCount));
      } else {
        return errorResult('No active Dapper debug sessions');
      }
    }

    return jsonResult({ sessions });
  }

  private _buildSessionInfo(
    session: vscode.DebugSession,
    checkpoint: number,
    breakpointCount: number,
  ): SessionInfo {
    const config = session.configuration;
    const lastSnapshot = this.registry.resolve(session.id)?.lastSnapshot;

    return {
      id: session.id,
      name: session.name,
      type: session.type,
      state: lastSnapshot?.stoppedThreads?.length
        ? 'stopped'
        : 'running',
      program: config?.program ?? config?.module,
      checkpoint,
      breakpointCount,
      configuration: {
        request: config?.request,
        program: config?.program,
        module: config?.module,
        cwd: config?.cwd,
        stopOnEntry: config?.stopOnEntry,
        justMyCode: config?.justMyCode,
      },
    };
  }
}
