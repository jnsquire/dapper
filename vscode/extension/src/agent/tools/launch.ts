/**
 * dapper_launch — Start a new Dapper Python debug session.
 */

import * as vscode from 'vscode';
import type { JournalRegistry } from '../stateJournal.js';
import { jsonResult, errorResult } from '../toolUtils.js';
import type { LaunchService, LaunchOptions } from '../../debugAdapter/launchService.js';

type LaunchToolInput = LaunchOptions;

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
      const result = await this.launchService.launch(options.input, token);
      const journal = await this.launchService.waitForJournal(result.session.id, token, 5_000);
      const effectiveStopped = result.stopped
        || Boolean(result.waitedForStop && journal?.lastSnapshot?.stoppedThreads?.length);
      const snapshot = effectiveStopped && journal ? await journal.getSnapshot() : undefined;

      return jsonResult({
        sessionId: result.session.id,
        sessionName: result.session.name,
        started: result.started,
        waitedForStop: result.waitedForStop,
        stopped: effectiveStopped,
        pythonPath: result.pythonPath,
        venvPath: result.venvPath,
        resolvedTarget: result.resolvedTarget,
        checkpoint: journal?.checkpoint ?? 0,
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
        trackedSessions: this.registry.journals.size,
      });
    } catch (err) {
      return errorResult(err instanceof Error ? err.message : String(err));
    }
  }
}