/**
 * dapper_variable — Deeply inspect a variable/expression result.
 */

import * as vscode from 'vscode';
import type { JournalRegistry } from '../stateJournal.js';
import { resolveSession, jsonResult, errorResult } from '../toolUtils.js';

interface InspectVariableInput {
  sessionId?: string;
  expression: string;
  depth?: number;
  maxItems?: number;
  frameIndex?: number;
}

export class InspectVariableTool implements vscode.LanguageModelTool<InspectVariableInput> {
  constructor(private registry: JournalRegistry) {}

  /**
   * Show confirmation since evaluation executes in the debuggee.
   */
  async prepareInvocation(
    options: vscode.LanguageModelToolInvocationPrepareOptions<InspectVariableInput>,
    _token: vscode.CancellationToken,
  ): Promise<vscode.PreparedToolInvocation> {
    const { expression } = options.input;
    return {
      invocationMessage: `Inspect '${expression}' in the debuggee process`,
      confirmationMessages: {
        title: 'Dapper: Inspect Variable',
        message: new vscode.MarkdownString(
          `This will evaluate \`${expression}\` in the debuggee Python process and expand its children. Continue?`,
        ),
      },
    };
  }

  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<InspectVariableInput>,
    _token: vscode.CancellationToken,
  ): Promise<vscode.LanguageModelToolResult> {
    const { sessionId, expression, depth, maxItems, frameIndex } = options.input;
    const resolved = resolveSession(this.registry, sessionId);
    if (!resolved) {
      return errorResult('No active Dapper debug session');
    }

    const { session } = resolved;

    try {
      const result = await session.customRequest('dapper/agentInspect', {
        expression,
        depth: depth ?? 2,
        maxItems: maxItems ?? 20,
        frameIndex: frameIndex ?? 0,
      });
      return jsonResult(result?.root ?? { name: expression, value: '<no result>' });
    } catch (err) {
      return errorResult(`Inspect failed: ${err}`);
    }
  }
}
