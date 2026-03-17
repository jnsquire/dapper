import * as path from 'path';
import * as vscode from 'vscode';

import type { PythonAutofixOptions, PythonAutofixService } from '../../python/autofix.js';
import { jsonResult } from '../toolUtils.js';

interface PythonAutofixToolInput {
  searchRootPath?: string;
  files?: string[];
  apply?: boolean;
}

export class PythonAutofixTool implements vscode.LanguageModelTool<PythonAutofixToolInput> {
  constructor(private readonly autofixService: Pick<PythonAutofixService, 'run'>) {}

  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<PythonAutofixToolInput>,
    _token: vscode.CancellationToken,
  ): Promise<vscode.LanguageModelToolResult> {
    const autofixOptions = this._normalizeInput(options.input);
    const result = await this.autofixService.run(autofixOptions);
    return jsonResult(result);
  }

  private _normalizeInput(input: PythonAutofixToolInput | undefined): PythonAutofixOptions {
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
      apply: input.apply !== false,
    };
  }

  private _normalizePath(value: string): string {
    return process.platform === 'win32' ? value.toLowerCase() : value;
  }
}