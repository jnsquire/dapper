/**
 * dapper_evaluate — Batch-evaluate expressions with prepareInvocation confirmation.
 */

import * as vscode from 'vscode';
import type { JournalRegistry } from '../stateJournal.js';
import { resolveSession, jsonResult, errorResult } from '../toolUtils.js';

interface EvaluateInput {
  sessionId?: string;
  expression?: string;
  expressions?: string[];
  frameIndex?: number;
}

export class EvaluateTool implements vscode.LanguageModelTool<EvaluateInput> {
  constructor(private registry: JournalRegistry) {}

  /**
   * Show a confirmation dialog before allowing code evaluation in the debuggee.
   * This is a security measure since expressions execute in the target process.
   */
  async prepareInvocation(
    options: vscode.LanguageModelToolInvocationPrepareOptions<EvaluateInput>,
    _token: vscode.CancellationToken,
  ): Promise<vscode.PreparedToolInvocation> {
    const { expression, expressions: rawExpressions } = options.input;
    const expressions = rawExpressions ?? (expression ? [expression] : []);
    const exprList = expressions.map(e => `  • ${e}`).join('\n');
    return {
      invocationMessage: `Evaluate ${expressions.length} expression(s) in the debuggee process`,
      confirmationMessages: {
        title: 'Dapper: Evaluate in Debuggee',
        message: new vscode.MarkdownString(
          `The following expressions will be **executed** in the debuggee Python process:\n\n${exprList}\n\nThis may have side effects. Continue?`,
        ),
      },
    };
  }

  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<EvaluateInput>,
    _token: vscode.CancellationToken,
  ): Promise<vscode.LanguageModelToolResult> {
    const { sessionId, expression, expressions: rawExpressions, frameIndex } = options.input;
    const expressions = rawExpressions ?? (expression ? [expression] : []);
    const resolved = resolveSession(this.registry, sessionId);
    if (!resolved) {
      return errorResult('No active Dapper debug session');
    }

    if (!expressions || expressions.length === 0) {
      return errorResult('No expressions provided. Pass "expression" (string) or "expressions" (array).');
    }

    if (expressions.length > 50) {
      return errorResult('Too many expressions (max 50)');
    }

    const { session } = resolved;

    try {
      const result = await session.customRequest('dapper/agentEval', {
        expressions,
        frameIndex: frameIndex ?? 0,
      });
      return jsonResult(result?.results ?? []);
    } catch (err) {
      return errorResult(`Evaluation failed: ${err}`);
    }
  }
}
