import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';

import type { PrepareEnvironmentOptions } from './types.js';

export function getVenvPythonPath(venvPath: string): string {
  return process.platform === 'win32'
    ? path.join(venvPath, 'Scripts', 'python.exe')
    : path.join(venvPath, 'bin', 'python');
}

export function resolveBaseInterpreter(setting?: string): string {
  if (setting && fs.existsSync(setting)) {
    return setting;
  }
  return process.platform !== 'win32' ? 'python3' : 'python';
}

export function resolveWorkspacePython(
  setting?: string,
  preferredPythonPath?: string,
  preferredVenvPath?: string,
): string {
  if (preferredPythonPath && fs.existsSync(preferredPythonPath)) {
    return preferredPythonPath;
  }
  if (preferredVenvPath) {
    const candidate = getVenvPythonPath(preferredVenvPath);
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  if (setting && fs.existsSync(setting)) {
    return setting;
  }
  return process.platform !== 'win32' ? 'python3' : 'python';
}

export function normalizePrepareOptions(
  options?: vscode.WorkspaceFolder | PrepareEnvironmentOptions,
): PrepareEnvironmentOptions {
  if (!options) {
    return {};
  }
  if ('uri' in options) {
    return { workspaceFolder: options };
  }
  return options;
}
