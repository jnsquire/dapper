import * as path from 'path';
import * as vscode from 'vscode';

import type { PythonFormatOptions, PythonFormatService } from '../../python/format.js';
import { jsonResult } from '../toolUtils.js';

interface PythonFormatToolInput {
  searchRootPath?: string;
  files?: string[];
  apply?: boolean;
}

export class PythonFormatTool implements vscode.LanguageModelTool<PythonFormatToolInput> {
  constructor(private readonly formatService: Pick<PythonFormatService, 'run'>) {}

  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<PythonFormatToolInput>,
    _token: vscode.CancellationToken,
  ): Promise<vscode.LanguageModelToolResult> {
    const formatOptions = this._normalizeInput(options.input);
    const result = await this.formatService.run(formatOptions);
    return jsonResult(result);
  }

  private _normalizeInput(input: PythonFormatToolInput | undefined): PythonFormatOptions {
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