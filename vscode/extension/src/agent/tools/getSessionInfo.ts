/**
 * dapper_session_info — Get metadata and readiness status for active debug sessions.
 */

import * as vscode from 'vscode';
import type {
  BreakpointVerificationSummary,
  JournalRegistry,
  SessionReadinessInfo,
  SessionTransitionRecord,
  StateJournal,
} from '../stateJournal.js';
import { jsonResult, errorResult } from '../toolUtils.js';

export interface GetSessionInfoInput {
  sessionId?: string;
}

export interface SessionStatusOutput {
  id: string;
  name: string;
  type: string;
  state: 'running' | 'stopped' | 'unknown';
  program?: string;
  checkpoint: number;
  lifecycleState: string;
  breakpointRegistrationComplete: boolean;
  lastTransition: SessionTransitionRecord;
  lastError?: string;
  readyToContinue: boolean;
  breakpoints: {
    accepted: number;
    pending: number;
    rejected: number;
    details: {
      accepted: BreakpointVerificationSummary[];
      pending: BreakpointVerificationSummary[];
      rejected: BreakpointVerificationSummary[];
    };
  };
  configuration: Record<string, unknown>;
}

interface SessionInfo extends SessionStatusOutput {
  breakpointCount: number;
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

      const info = this._buildSessionInfo(session, journal, bpCount);
      return jsonResult(info);
    }

    // List all tracked sessions
    const sessions: SessionInfo[] = [];
    for (const [id, journal] of this.registry.journals) {
      const active = vscode.debug.activeDebugSession;
      if (active?.id === id) {
        sessions.push(this._buildSessionInfo(active, journal, bpCount));
      } else {
        sessions.push({
          ...buildSessionStatus(journal.session, journal),
          breakpointCount: bpCount,
        });
      }
    }

    if (sessions.length === 0) {
      // Check if there's an active session not yet tracked
      const active = vscode.debug.activeDebugSession;
      if (active?.type === 'dapper') {
        sessions.push(this._buildSessionInfo(active, undefined, bpCount));
      } else {
        return errorResult('No active Dapper debug sessions');
      }
    }

    return jsonResult({ sessions });
  }

  private _buildSessionInfo(
    session: vscode.DebugSession,
    journal: ReturnType<JournalRegistry['resolve']> | undefined,
    breakpointCount: number,
  ): SessionInfo {
    return {
      ...buildSessionStatus(session, journal),
      breakpointCount,
    };
  }
}

export function buildSessionStatus(
  session: vscode.DebugSession,
  journal?: StateJournal,
): SessionStatusOutput {
  const readiness = journal?.readinessInfo ?? fallbackReadinessInfo();
  const breakpointDetails = groupBreakpointDetails(journal?.getBreakpointVerifications() ?? []);
  const counts = journal?.getBreakpointStatusCounts() ?? { verified: 0, pending: 0, rejected: 0 };
  const config = session.configuration;
  const lastSnapshot = journal?.lastSnapshot;

  return {
    id: session.id,
    name: session.name,
    type: session.type,
    state: lastSnapshot?.stoppedThreads?.length ? 'stopped' : 'running',
    program: config?.program ?? config?.module,
    checkpoint: journal?.checkpoint ?? 0,
    lifecycleState: readiness.lifecycleState,
    breakpointRegistrationComplete: readiness.breakpointRegistrationComplete,
    lastTransition: readiness.lastTransition,
    lastError: readiness.lastError,
    readyToContinue: readiness.breakpointRegistrationComplete
      && counts.rejected === 0
      && readiness.lastError === undefined
      && readiness.lifecycleState !== 'error',
    breakpoints: {
      accepted: counts.verified,
      pending: counts.pending,
      rejected: counts.rejected,
      details: breakpointDetails,
    },
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

function fallbackReadinessInfo(): SessionReadinessInfo {
  return {
    lifecycleState: 'unknown',
    breakpointRegistrationComplete: false,
    lastTransition: {
      state: 'unknown',
      reason: 'No readiness data available',
      timestamp: Date.now(),
    },
    lastError: undefined,
  };
}

function groupBreakpointDetails(details: BreakpointVerificationSummary[]): SessionStatusOutput['breakpoints']['details'] {
  return {
    accepted: details.filter((detail) => detail.verificationState === 'verified'),
    pending: details.filter((detail) => detail.verificationState === 'pending'),
    rejected: details.filter((detail) => detail.verificationState === 'rejected'),
  };
}
