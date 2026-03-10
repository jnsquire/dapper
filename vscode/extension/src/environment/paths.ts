import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';

import type { PrepareEnvironmentOptions } from './types.js';

function normalizeSearchPath(value: string): string {
  return process.platform === 'win32' ? value.toLowerCase() : value;
}

export function collectEnvironmentSearchRoots(
  searchRootPath?: string,
  workspaceFolder?: vscode.WorkspaceFolder,
): string[] {
  const roots: string[] = [];
  const seen = new Set<string>();
  const addRoot = (candidate: string | undefined) => {
    if (!candidate) {
      return;
    }
    const resolved = path.resolve(candidate);
    const key = normalizeSearchPath(resolved);
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    roots.push(resolved);
  };

  const workspaceRoots = vscode.workspace.workspaceFolders?.map(folder => folder.uri.fsPath) ?? [];
  const resolvedSearchRoot = searchRootPath ? path.resolve(searchRootPath) : undefined;
  const containingWorkspaceRoot = resolvedSearchRoot
    ? workspaceRoots.find(folder => {
      const resolvedFolder = path.resolve(folder);
      const normalizedFolder = normalizeSearchPath(resolvedFolder);
      const normalizedRoot = normalizeSearchPath(resolvedSearchRoot);
      return normalizedRoot === normalizedFolder || normalizedRoot.startsWith(`${normalizedFolder}${path.sep}`);
    })
    : undefined;
  const primaryWorkspaceRoot = workspaceFolder?.uri.fsPath ?? containingWorkspaceRoot;

  if (resolvedSearchRoot) {
    let current = resolvedSearchRoot;
    const stopAt = primaryWorkspaceRoot ? path.resolve(primaryWorkspaceRoot) : undefined;
    while (true) {
      addRoot(current);
      if (!stopAt || normalizeSearchPath(current) === normalizeSearchPath(stopAt)) {
        break;
      }
      const parent = path.dirname(current);
      if (parent === current) {
        break;
      }
      current = parent;
    }
  }

  addRoot(primaryWorkspaceRoot);
  for (const workspaceRoot of workspaceRoots) {
    addRoot(workspaceRoot);
  }

  return roots;
}

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
