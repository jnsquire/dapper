import * as path from 'path';

import * as vscode from 'vscode';

import type { EnvironmentSnapshotOptions } from './environmentSnapshot.js';

export interface PythonDocumentOptions extends EnvironmentSnapshotOptions {
  file: string;
}

export function resolvePythonBasePath(options: EnvironmentSnapshotOptions): string {
  return options.searchRootPath
    ?? options.workspaceFolder?.uri.fsPath
    ?? vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
    ?? process.cwd();
}

export function resolvePythonDocumentUri(options: PythonDocumentOptions): vscode.Uri {
  const inputPath = path.resolve(resolvePythonBasePath(options), options.file);
  return vscode.Uri.file(inputPath);
}