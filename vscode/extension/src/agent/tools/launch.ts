/**
 * dapper_launch — Start a new Dapper Python debug session.
 */

import * as path from 'path';
import * as vscode from 'vscode';
import type { JournalRegistry } from '../stateJournal.js';
import { jsonResult, errorResult } from '../toolUtils.js';
import type { LaunchService, LaunchOptions } from '../../debugAdapter/launchService.js';

type LaunchToolInput = LaunchOptions;

interface LaunchTargetDescriptor {
  kind: 'program' | 'module' | 'unknown';
  value?: string;
}

function normalizeLaunchTarget(configuration: vscode.DebugConfiguration | undefined): LaunchTargetDescriptor {
  if (!configuration) {
    return { kind: 'unknown' };
  }

  if (typeof configuration.program === 'string' && configuration.program.trim()) {
    return { kind: 'program', value: path.resolve(configuration.program) };
  }
  if (typeof configuration.module === 'string' && configuration.module.trim()) {
    return { kind: 'module', value: configuration.module.trim() };
  }
  return { kind: 'unknown' };
}

function countMatchingTrackedTargets(
  trackedSessions: readonly vscode.DebugSession[],
  launchedTarget: LaunchTargetDescriptor,
): number {
  if (launchedTarget.kind === 'unknown' || !launchedTarget.value) {
    return 0;
  }

  return trackedSessions.filter((session) => {
    const trackedTarget = normalizeLaunchTarget(session.configuration);
    return trackedTarget.kind === launchedTarget.kind && trackedTarget.value === launchedTarget.value;
  }).length;
}

function buildLaunchWarnings(
  trackedSessionsBeforeLaunch: readonly vscode.DebugSession[],
  trackedSessionsAfterLaunch: number,
  configuration: vscode.DebugConfiguration,
): string[] {
  if (trackedSessionsBeforeLaunch.length <= 0) {
    return [];
  }

  const warnings: string[] = [];
  const priorLabel = trackedSessionsBeforeLaunch.length === 1 ? 'session was' : 'sessions were';
  const totalLabel = trackedSessionsAfterLaunch === 1 ? 'session is' : 'sessions are';
  warnings.push(
    `${trackedSessionsBeforeLaunch.length} tracked Dapper ${priorLabel} already active before this launch. ${trackedSessionsAfterLaunch} tracked Dapper ${totalLabel} now active in this workspace. Use dapper_session_info to inspect them and dapper_execution with action='terminate' to clean up sessions you no longer need.`,
  );

  const launchedTarget = normalizeLaunchTarget(configuration);
  const sameTargetCount = countMatchingTrackedTargets(trackedSessionsBeforeLaunch, launchedTarget);
  if (sameTargetCount > 0 && launchedTarget.value) {
    const sessionLabel = sameTargetCount === 1 ? 'session was' : 'sessions were';
    const targetLabel = launchedTarget.kind === 'program' ? 'program' : 'module';
    warnings.push(
      `${sameTargetCount} tracked Dapper ${sessionLabel} already targeting the same ${targetLabel} (${launchedTarget.value}) before this launch. Clean up stale sessions first if you want an isolated repro.`,
    );
  }

  return warnings;
}

export class LaunchTool implements vscode.LanguageModelTool<LaunchToolInput> {
  constructor(
    private readonly registry: JournalRegistry,
    private readonly launchService: LaunchService,
  ) {}

  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<LaunchToolInput>,
    token: vscode.CancellationToken,
  ): Promise<vscode.LanguageModelToolResult> {
    try {
      const trackedSessionsBeforeLaunch = [...this.registry.journals.values()].map((journal) => journal.session);
      const result = await this.launchService.launch(options.input, token);
      const session = result.session;
      if (!session) {
        throw new Error('Dapper launch did not create a debug session. Use dapper.api.runLaunch for no-debug process launches.');
      }
      const existingJournal = this.registry.resolve(session.id);
      const journal = existingJournal
        ?? (result.waitedForStop && !result.stopped
          ? undefined
          : await this.launchService.waitForJournal(session.id, token, 5_000));
      const effectiveStopped = result.stopped
        || Boolean(result.waitedForStop && journal?.lastSnapshot?.stoppedThreads?.length);
      const snapshot = effectiveStopped && journal ? await journal.getSnapshot() : undefined;
      const readiness = journal?.readinessInfo ?? null;
      const trackedSessions = this.registry.journals.size;
      const warnings = buildLaunchWarnings(trackedSessionsBeforeLaunch, trackedSessions, result.configuration);

      return jsonResult({
        sessionId: session.id,
        sessionName: session.name,
        started: result.started,
        waitedForStop: result.waitedForStop,
        stopped: effectiveStopped,
        pythonPath: result.pythonPath,
        venvPath: result.venvPath,
        resolvedTarget: result.resolvedTarget,
        checkpoint: journal?.checkpoint ?? 0,
        readiness,
        readyToContinue: readiness
          ? readiness.breakpointRegistrationComplete
            && readiness.lastError === undefined
            && readiness.lifecycleState !== 'error'
          : false,
        snapshot: snapshot ?? null,
        configuration: {
          request: result.configuration.request,
          program: result.configuration.program,
          module: result.configuration.module,
          args: result.configuration.args,
          cwd: result.configuration.cwd,
          moduleSearchPaths: result.configuration.moduleSearchPaths,
          stopOnEntry: result.configuration.stopOnEntry,
          justMyCode: result.configuration.justMyCode,
          subprocessAutoAttach: result.configuration.subprocessAutoAttach,
        },
        trackedSessionsBeforeLaunch: trackedSessionsBeforeLaunch.length,
        trackedSessions,
        warnings,
      });
    } catch (err) {
      return errorResult(err instanceof Error ? err.message : String(err));
    }
  }
}