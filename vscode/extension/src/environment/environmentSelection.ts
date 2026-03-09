import * as fs from 'fs';
import * as path from 'path';

import * as vscode from 'vscode';

import type { PythonEnvInfo } from './types.js';

export interface EnvironmentSelectionDeps {
  output: vscode.LogOutputChannel;
  checkDapperImportable(pythonPath: string): Promise<boolean>;
  createVenv(baseInterpreter: string, venvPath: string): Promise<void>;
  ensureDapperLib(pythonPath: string, version: string, wheelDir: string, forceReinstall: boolean): Promise<string | undefined>;
  ensurePip(pythonPath: string): Promise<void>;
  getDapperVersion(pythonPath: string): Promise<string | undefined>;
  getVenvPythonPath(venvPath: string): string;
  installFromPyPI(pythonPath: string, version: string, force: boolean): Promise<void>;
  installWheel(pythonPath: string, wheelDir: string, version: string, force: boolean): Promise<void>;
  resolveWorkspacePython(setting?: string, preferredPythonPath?: string, preferredVenvPath?: string): string;
  upgradePip(pythonPath: string): Promise<void>;
}

export async function createWorkspaceVenvOrAbort(
  version: string,
  wheelDir: string | undefined,
  workspaceFolder: vscode.WorkspaceFolder | undefined,
  baseInterpreterSetting: string | undefined,
  preferredPythonPath: string | undefined,
  preferredVenvPath: string | undefined,
  forceReinstall: boolean,
  deps: EnvironmentSelectionDeps,
): Promise<PythonEnvInfo> {
  const targetWorkspaceFolder = workspaceFolder ?? vscode.workspace.workspaceFolders?.[0];
  if (!targetWorkspaceFolder) {
    throw new Error('Dapper could not find a workspace virtual environment, and there is no workspace folder available to create one.');
  }

  const createLabel = 'Create .venv';
  const choice = await vscode.window.showInformationMessage(
    `Dapper could not find a workspace virtual environment in ${targetWorkspaceFolder.uri.fsPath}. Create .venv and use it for debugging?`,
    { modal: true },
    createLabel,
  );
  if (choice !== createLabel) {
    throw new Error('Launch cancelled because Dapper requires a workspace virtual environment for this debug session.');
  }

  const venvPath = path.join(targetWorkspaceFolder.uri.fsPath, '.venv');
  const pythonPath = deps.getVenvPythonPath(venvPath);
  const baseInterpreter = preferredPythonPath ?? deps.resolveWorkspacePython(
    baseInterpreterSetting,
    preferredPythonPath,
    preferredVenvPath,
  );

  deps.output.info(`Creating workspace venv at ${venvPath} with base interpreter ${baseInterpreter}`);
  await deps.createVenv(baseInterpreter, venvPath);

  if (wheelDir) {
    const libPath = await deps.ensureDapperLib(pythonPath, version, wheelDir, forceReinstall);
    if (libPath) {
      deps.output.info(`Using newly created workspace venv with Dapper injected from ${libPath}`);
      return {
        pythonPath,
        venvPath,
        needsInstall: false,
        dapperLibPath: libPath,
      };
    }
    deps.output.warn('Failed to prepare injected Dapper library for the new workspace venv; installing directly into the venv instead.');
  }

  await deps.ensurePip(pythonPath);
  await deps.upgradePip(pythonPath);
  if (wheelDir) {
    await deps.installWheel(pythonPath, wheelDir, version, forceReinstall);
  } else {
    await deps.installFromPyPI(pythonPath, version, forceReinstall);
  }

  return {
    pythonPath,
    venvPath,
    dapperVersionInstalled: version,
    needsInstall: true,
  };
}

export async function tryWorkspaceVenv(
  version: string,
  wheelDir: string | undefined,
  workspaceFolder: vscode.WorkspaceFolder | undefined,
  forceReinstall: boolean,
  deps: EnvironmentSelectionDeps,
): Promise<PythonEnvInfo | undefined> {
  const binDir = process.platform === 'win32' ? 'Scripts' : 'bin';
  const pyExe = process.platform === 'win32' ? 'python.exe' : 'python';
  const venvDirs = ['.venv', 'venv', 'env', '.env'];

  const allWorkspaceFolders = (vscode.workspace.workspaceFolders ?? []).map(folder => folder.uri.fsPath);
  const sessionFolder = workspaceFolder?.uri.fsPath;
  const folders = sessionFolder && !allWorkspaceFolders.includes(sessionFolder)
    ? [sessionFolder, ...allWorkspaceFolders]
    : (sessionFolder ? [sessionFolder, ...allWorkspaceFolders.filter(folder => folder !== sessionFolder)] : allWorkspaceFolders);

  deps.output.info(`tryWorkspaceVenv: scanning folders [${folders.join(', ')}]`);

  for (const folder of folders) {
    for (const venvDir of venvDirs) {
      const candidate = path.join(folder, venvDir, binDir, pyExe);
      deps.output.debug(`tryWorkspaceVenv: checking ${candidate}`);
      if (!fs.existsSync(candidate)) {
        continue;
      }

      deps.output.info(`auto mode: found workspace venv at ${candidate}`);
      if (!forceReinstall && await deps.checkDapperImportable(candidate)) {
        const installedVersion = await deps.getDapperVersion(candidate);
        if (installedVersion === version) {
          deps.output.info(`auto mode: dapper already installed in workspace venv (version ${installedVersion}), using it.`);
          return { pythonPath: candidate, needsInstall: false };
        }
        deps.output.info(
          `auto mode: workspace venv has dapper ${installedVersion} but need ${version}; ` +
          'will use PYTHONPATH injection instead of modifying the venv.',
        );
      }

      if (wheelDir) {
        const libPath = await deps.ensureDapperLib(candidate, version, wheelDir, forceReinstall);
        if (libPath) {
          deps.output.info(`auto mode: dapper ${version} available via PYTHONPATH at ${libPath}`);
          return { pythonPath: candidate, needsInstall: false, dapperLibPath: libPath };
        }
        deps.output.warn('auto mode: failed to extract dapper for PYTHONPATH injection; falling back.');
      } else {
        deps.output.info('auto mode: workspace venv found but no bundled wheels for PYTHONPATH injection; falling back to managed venv.');
      }

      return undefined;
    }
  }

  return undefined;
}

export async function tryPreferredInterpreter(
  version: string,
  wheelDir: string | undefined,
  preferredPythonPath: string | undefined,
  preferredVenvPath: string | undefined,
  forceReinstall: boolean,
  deps: EnvironmentSelectionDeps,
): Promise<PythonEnvInfo | undefined> {
  const candidate = preferredPythonPath
    ?? (preferredVenvPath ? deps.getVenvPythonPath(preferredVenvPath) : undefined);
  if (!candidate) {
    return undefined;
  }
  if (!fs.existsSync(candidate)) {
    deps.output.warn(`Preferred interpreter does not exist: ${candidate}`);
    return undefined;
  }

  deps.output.info(`Using preferred interpreter candidate: ${candidate}`);
  const importable = await deps.checkDapperImportable(candidate);
  if (!forceReinstall && importable) {
    const installedVersion = await deps.getDapperVersion(candidate);
    if (installedVersion === version || !wheelDir) {
      deps.output.info(`Preferred interpreter already provides dapper${installedVersion ? ` ${installedVersion}` : ''}.`);
      return { pythonPath: candidate, venvPath: preferredVenvPath, needsInstall: false };
    }
  }

  if (wheelDir) {
    const libPath = await deps.ensureDapperLib(candidate, version, wheelDir, forceReinstall);
    if (libPath) {
      return {
        pythonPath: candidate,
        venvPath: preferredVenvPath,
        needsInstall: false,
        dapperLibPath: libPath,
      };
    }
  }

  if (importable) {
    deps.output.warn('Preferred interpreter has dapper available but the version may differ from the extension bundle. Reusing it anyway.');
    return { pythonPath: candidate, venvPath: preferredVenvPath, needsInstall: false };
  }

  return undefined;
}
