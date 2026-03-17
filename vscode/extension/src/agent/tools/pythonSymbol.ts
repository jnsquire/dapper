import * as path from 'path';
import * as vscode from 'vscode';

import type { PythonSymbolAction, PythonSymbolOptions, PythonSymbolService } from '../../python/symbols.js';
import { jsonResult } from '../toolUtils.js';

interface PythonSymbolToolInput {
  action: PythonSymbolAction;
  file: string;
  line: number;
  column?: number;
  searchRootPath?: string;
}

export class PythonSymbolTool implements vscode.LanguageModelTool<PythonSymbolToolInput> {
  constructor(private readonly symbolService: Pick<PythonSymbolService, 'resolve'>) {}

  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<PythonSymbolToolInput>,
    _token: vscode.CancellationToken,
  ): Promise<vscode.LanguageModelToolResult> {
    const symbolOptions = this._normalizeInput(options.input);
    const result = await this.symbolService.resolve(symbolOptions);
    return jsonResult(result);
  }

  private _normalizeInput(input: PythonSymbolToolInput | undefined): PythonSymbolOptions {
    if (!input || typeof input !== 'object') {
      throw new Error('dapper_python_symbol expects an input object.');
    }
    if (typeof input.action !== 'string') {
      throw new Error('dapper_python_symbol requires an action.');
    }
    if (typeof input.file !== 'string') {
      throw new Error('dapper_python_symbol requires a file path.');
    }
    if (typeof input.line !== 'number' || !Number.isFinite(input.line) || input.line < 1) {
      throw new Error('dapper_python_symbol requires a 1-based line number.');
    }

    const searchRootPath = typeof input.searchRootPath === 'string' ? input.searchRootPath : undefined;
    const workspaceFolder = searchRootPath
      ? vscode.workspace.getWorkspaceFolder(vscode.Uri.file(path.resolve(searchRootPath)))
      : undefined;

    return {
      action: input.action,
      file: input.file,
      line: Math.floor(input.line),
      column: typeof input.column === 'number' && Number.isFinite(input.column) && input.column >= 1
        ? Math.floor(input.column)
        : undefined,
      workspaceFolder,
      searchRootPath,
    };
  }

  private _normalizePath(value: string): string {
    return process.platform === 'win32' ? value.toLowerCase() : value;
  }
}