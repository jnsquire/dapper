/**
 * Agent tools registration index.
 *
 * Registers all Dapper LM tools with the VS Code language model tools API.
 */

import * as vscode from 'vscode';
import type { JournalRegistry } from '../stateJournal.js';
import type { LaunchService } from '../../debugAdapter/launchService.js';
import { EvaluateTool } from './evaluate.js';
import { StateTool } from './state.js';
import { ExecutionTool } from './execution.js';
import { BreakpointsTool } from './breakpoints.js';
import { InspectVariableTool } from './inspectVariable.js';
import { GetSessionInfoTool } from './getSessionInfo.js';
import { LaunchTool } from './launch.js';
import { DapperCliTool } from './cli.js';
import { PythonAutofixTool } from './pythonAutofix.js';
import { PythonDiagnosticsTool } from './pythonDiagnostics.js';
import { PythonEnvironmentTool } from './pythonEnvironment.js';
import { PythonFormatTool } from './pythonFormat.js';
import { PythonImportsTool } from './pythonImports.js';
import { PythonProjectModelTool } from './pythonProjectModel.js';
import { PythonRenameTool } from './pythonRename.js';
import { PythonSymbolTool } from './pythonSymbol.js';
import { PythonTypecheckTool } from './pythonTypecheck.js';
import type { PythonAutofixService } from '../../python/autofix.js';
import type { PythonDiagnosticsService } from '../../python/diagnostics.js';
import type { EnvironmentSnapshotService } from '../../python/environmentSnapshot.js';
import type { PythonFormatService } from '../../python/format.js';
import type { PythonImportsService } from '../../python/imports.js';
import type { PythonProjectModelService } from '../../python/projectModel.js';
import type { PythonRenameService } from '../../python/rename.js';
import type { PythonSymbolService } from '../../python/symbols.js';
import type { PythonTypecheckService } from '../../python/typecheck.js';

/**
 * Register all agent tools and return an array of disposables.
 */
export function registerAgentTools(
  registry: JournalRegistry,
  launchService: LaunchService,
  packageManifest: unknown,
  pythonAutofixService: PythonAutofixService,
  environmentSnapshotService: EnvironmentSnapshotService,
  pythonDiagnosticsService: PythonDiagnosticsService,
  pythonFormatService: PythonFormatService,
  pythonImportsService: PythonImportsService,
  pythonProjectModelService: PythonProjectModelService,
  pythonRenameService: PythonRenameService,
  pythonSymbolService: PythonSymbolService,
  pythonTypecheckService: PythonTypecheckService,
): vscode.Disposable[] {
  const disposables: vscode.Disposable[] = [];

  disposables.push(
    vscode.lm.registerTool('dapper_cli', new DapperCliTool(registry, launchService, packageManifest as { contributes?: { languageModelTools?: unknown[] } })),
  );
  disposables.push(
    vscode.lm.registerTool('dapper_launch', new LaunchTool(registry, launchService)),
  );
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
  disposables.push(
    vscode.lm.registerTool('dapper_python_environment', new PythonEnvironmentTool(environmentSnapshotService)),
  );
  disposables.push(
    vscode.lm.registerTool('dapper_python_autofix', new PythonAutofixTool(pythonAutofixService)),
  );
  disposables.push(
    vscode.lm.registerTool('dapper_python_diagnostics', new PythonDiagnosticsTool(pythonDiagnosticsService)),
  );
  disposables.push(
    vscode.lm.registerTool('dapper_python_format', new PythonFormatTool(pythonFormatService)),
  );
  disposables.push(
    vscode.lm.registerTool('dapper_python_imports', new PythonImportsTool(pythonImportsService)),
  );
  disposables.push(
    vscode.lm.registerTool('dapper_python_project_model', new PythonProjectModelTool(pythonProjectModelService)),
  );
  disposables.push(
    vscode.lm.registerTool('dapper_python_rename', new PythonRenameTool(pythonRenameService)),
  );
  disposables.push(
    vscode.lm.registerTool('dapper_python_symbol', new PythonSymbolTool(pythonSymbolService)),
  );
  disposables.push(
    vscode.lm.registerTool('dapper_python_typecheck', new PythonTypecheckTool(pythonTypecheckService)),
  );

  return disposables;
}
