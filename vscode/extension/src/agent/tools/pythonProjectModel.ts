import * as path from 'path';
import * as vscode from 'vscode';

import type { PythonProjectModelOptions, PythonProjectModelService } from '../../python/projectModel.js';
import { jsonResult } from '../toolUtils.js';

interface PythonProjectModelToolInput {
  searchRootPath?: string;
}

export class PythonProjectModelTool implements vscode.LanguageModelTool<PythonProjectModelToolInput> {
  constructor(private readonly projectModelService: Pick<PythonProjectModelService, 'getProjectModel'>) {}

  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<PythonProjectModelToolInput>,
    _token: vscode.CancellationToken,
  ): Promise<vscode.LanguageModelToolResult> {
    const projectModelOptions = this._normalizeInput(options.input);
    const result = await this.projectModelService.getProjectModel(projectModelOptions);
    return jsonResult(result);
  }

  private _normalizeInput(input: PythonProjectModelToolInput | undefined): PythonProjectModelOptions {
    if (!input) {
      return {};
    }

    const searchRootPath = typeof input.searchRootPath === 'string' ? input.searchRootPath : undefined;
    const workspaceFolder = searchRootPath
      ? vscode.workspace.getWorkspaceFolder(vscode.Uri.file(path.resolve(searchRootPath)))
      : undefined;

    return { workspaceFolder, searchRootPath };
  }

  private _normalizePath(value: string): string {
    return process.platform === 'win32' ? value.toLowerCase() : value;
  }
}