/**
 * dapper_python_environment — Report Python environment and tool resolution.
 */

import * as path from 'path';
import * as vscode from 'vscode';

import type { EnvironmentSnapshotOptions, EnvironmentSnapshotService } from '../../python/environmentSnapshot.js';
import { jsonResult } from '../toolUtils.js';

interface PythonEnvironmentToolInput {
  searchRootPath?: string;
}

export class PythonEnvironmentTool implements vscode.LanguageModelTool<PythonEnvironmentToolInput> {
  constructor(private readonly environmentSnapshotService: Pick<EnvironmentSnapshotService, 'getSnapshot'>) {}

  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<PythonEnvironmentToolInput>,
    _token: vscode.CancellationToken,
  ): Promise<vscode.LanguageModelToolResult> {
    const snapshotOptions = this._normalizeInput(options.input);
    const snapshot = await this.environmentSnapshotService.getSnapshot(snapshotOptions);
    return jsonResult(snapshot);
  }

  private _normalizeInput(input: PythonEnvironmentToolInput | undefined): EnvironmentSnapshotOptions {
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