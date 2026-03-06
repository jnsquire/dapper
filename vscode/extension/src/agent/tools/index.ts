/**
 * Agent tools registration index.
 *
 * Registers all Dapper LM tools with the VS Code language model tools API.
 */

import * as vscode from 'vscode';
import type { JournalRegistry } from '../stateJournal.js';
import { EvaluateTool } from './evaluate.js';
import { StateTool } from './state.js';
import { ExecutionTool } from './execution.js';
import { BreakpointsTool } from './breakpoints.js';
import { InspectVariableTool } from './inspectVariable.js';
import { GetSessionInfoTool } from './getSessionInfo.js';

/**
 * Register all agent tools and return an array of disposables.
 */
export function registerAgentTools(registry: JournalRegistry): vscode.Disposable[] {
  const disposables: vscode.Disposable[] = [];

  disposables.push(
    vscode.lm.registerTool('dapper_state', new StateTool(registry)),
  );
  disposables.push(
    vscode.lm.registerTool('dapper_execution', new ExecutionTool(registry)),
  );
  disposables.push(
    vscode.lm.registerTool('dapper_evaluate', new EvaluateTool(registry)),
  );
  disposables.push(
    vscode.lm.registerTool('dapper_breakpoints', new BreakpointsTool(registry)),
  );
  disposables.push(
    vscode.lm.registerTool('dapper_variable', new InspectVariableTool(registry)),
  );
  disposables.push(
    vscode.lm.registerTool('dapper_session_info', new GetSessionInfoTool(registry)),
  );

  return disposables;
}
