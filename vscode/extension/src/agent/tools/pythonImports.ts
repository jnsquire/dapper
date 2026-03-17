import * as path from 'path';
import * as vscode from 'vscode';

import type { PythonImportsOptions, PythonImportsService } from '../../python/imports.js';
import { jsonResult } from '../toolUtils.js';

interface PythonImportsToolInput {
  mode?: 'cleanup' | 'organize' | 'all';
  searchRootPath?: string;
  files?: string[];
  apply?: boolean;
}

export class PythonImportsTool implements vscode.LanguageModelTool<PythonImportsToolInput> {
  constructor(private readonly importsService: Pick<PythonImportsService, 'run'>) {}

  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<PythonImportsToolInput>,
    _token: vscode.CancellationToken,
  ): Promise<vscode.LanguageModelToolResult> {
    const importsOptions = this._normalizeInput(options.input);
    const result = await this.importsService.run(importsOptions);
    return jsonResult(result);
  }

  private _normalizeInput(input: PythonImportsToolInput | undefined): PythonImportsOptions {
    if (!input) {
      return {};
    }

    const searchRootPath = typeof input.searchRootPath === 'string' ? input.searchRootPath : undefined;
    const workspaceFolder = searchRootPath
      ? vscode.workspace.getWorkspaceFolder(vscode.Uri.file(path.resolve(searchRootPath)))
      : undefined;

    const mode = input.mode === 'cleanup' || input.mode === 'organize' ? input.mode : 'all';

    return {
      mode,
      workspaceFolder,
      searchRootPath,
      files: Array.isArray(input.files) ? input.files.filter((item): item is string => typeof item === 'string') : undefined,
      apply: input.apply !== false,
    };
  }

  private _normalizePath(value: string): string {
    return process.platform === 'win32' ? value.toLowerCase() : value;
  }
}
