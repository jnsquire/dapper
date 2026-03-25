import * as path from 'path';
import * as vscode from 'vscode';

import type { PythonTypecheckOptions, PythonTypecheckService } from '../../python/typecheck.js';
import { jsonResult } from '../toolUtils.js';

interface PythonTypecheckToolInput {
  searchRootPath?: string;
  files?: string[];
  limit?: number;
  offset?: number;
  pathFilter?: 'source' | 'tests' | 'all';
}

export class PythonTypecheckTool implements vscode.LanguageModelTool<PythonTypecheckToolInput> {
  constructor(private readonly typecheckService: Pick<PythonTypecheckService, 'getTypecheck'>) {}

  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<PythonTypecheckToolInput>,
    _token: vscode.CancellationToken,
  ): Promise<vscode.LanguageModelToolResult> {
    const typecheckOptions = this._normalizeInput(options.input);
    const result = await this.typecheckService.getTypecheck(typecheckOptions);
    return jsonResult(result);
  }

  private _normalizeInput(input: PythonTypecheckToolInput | undefined): PythonTypecheckOptions {
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
      offset: typeof input.offset === 'number' ? input.offset : undefined,
      pathFilter: input.pathFilter === 'source' || input.pathFilter === 'tests' ? input.pathFilter : undefined,
    };
  }

  private _normalizePath(value: string): string {
    return process.platform === 'win32' ? value.toLowerCase() : value;
  }
}