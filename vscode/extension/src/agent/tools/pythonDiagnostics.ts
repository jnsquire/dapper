import * as path from 'path';
import * as vscode from 'vscode';

import type { PythonDiagnosticsOptions, PythonDiagnosticsService } from '../../python/diagnostics.js';
import { jsonResult } from '../toolUtils.js';

interface PythonDiagnosticsToolInput {
  searchRootPath?: string;
  files?: string[];
  limit?: number;
  pathFilter?: 'source' | 'tests' | 'all';
}

export class PythonDiagnosticsTool implements vscode.LanguageModelTool<PythonDiagnosticsToolInput> {
  constructor(private readonly diagnosticsService: Pick<PythonDiagnosticsService, 'getDiagnostics'>) {}

  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<PythonDiagnosticsToolInput>,
    _token: vscode.CancellationToken,
  ): Promise<vscode.LanguageModelToolResult> {
    const diagnosticsOptions = this._normalizeInput(options.input);
    const diagnostics = await this.diagnosticsService.getDiagnostics(diagnosticsOptions);
    return jsonResult(diagnostics);
  }

  private _normalizeInput(input: PythonDiagnosticsToolInput | undefined): PythonDiagnosticsOptions {
    if (!input) {
      return {};
    }

    const searchRootPath = typeof input.searchRootPath === 'string' ? input.searchRootPath : undefined;
    const workspaceFolder = searchRootPath
      ? vscode.workspace.getWorkspaceFolder(vscode.Uri.file(path.resolve(searchRootPath)))
      : undefined;

    return {
      workspaceFolder,
      searchRootPath,
      files: Array.isArray(input.files) ? input.files.filter((item): item is string => typeof item === 'string') : undefined,
      limit: typeof input.limit === 'number' ? input.limit : undefined,
      pathFilter: input.pathFilter === 'source' || input.pathFilter === 'tests' ? input.pathFilter : undefined,
    };
  }

  private _normalizePath(value: string): string {
    return process.platform === 'win32' ? value.toLowerCase() : value;
  }
}