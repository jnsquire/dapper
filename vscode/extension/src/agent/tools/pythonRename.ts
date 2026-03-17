import * as path from 'path';
import * as vscode from 'vscode';

import type { PythonRenameOptions, PythonRenameService } from '../../python/rename.js';
import { jsonResult } from '../toolUtils.js';

interface PythonRenameToolInput {
  file: string;
  line: number;
  column?: number;
  newName: string;
  apply?: boolean;
  searchRootPath?: string;
}

export class PythonRenameTool implements vscode.LanguageModelTool<PythonRenameToolInput> {
  constructor(private readonly renameService: Pick<PythonRenameService, 'rename'>) {}

  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<PythonRenameToolInput>,
    _token: vscode.CancellationToken,
  ): Promise<vscode.LanguageModelToolResult> {
    const renameOptions = this._normalizeInput(options.input);
    const result = await this.renameService.rename(renameOptions);
    return jsonResult(result);
  }

  private _normalizeInput(input: PythonRenameToolInput | undefined): PythonRenameOptions {
    if (!input || typeof input !== 'object') {
      throw new Error('dapper_python_rename expects an input object.');
    }
    if (typeof input.file !== 'string') {
      throw new Error('dapper_python_rename requires a file path.');
    }
    if (typeof input.newName !== 'string' || input.newName.length === 0) {
      throw new Error('dapper_python_rename requires a non-empty newName.');
    }
    if (typeof input.line !== 'number' || !Number.isFinite(input.line) || input.line < 1) {
      throw new Error('dapper_python_rename requires a 1-based line number.');
    }

    const searchRootPath = typeof input.searchRootPath === 'string' ? input.searchRootPath : undefined;
    const workspaceFolder = searchRootPath
      ? vscode.workspace.getWorkspaceFolder(vscode.Uri.file(path.resolve(searchRootPath)))
      : undefined;

    return {
      file: input.file,
      line: Math.floor(input.line),
      column: typeof input.column === 'number' && Number.isFinite(input.column) && input.column >= 1
        ? Math.floor(input.column)
        : undefined,
      newName: input.newName,
      apply: input.apply !== false,
      workspaceFolder,
      searchRootPath,
    };
  }

  private _normalizePath(value: string): string {
    return process.platform === 'win32' ? value.toLowerCase() : value;
  }
}