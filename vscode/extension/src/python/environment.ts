import * as fs from 'fs';
import * as path from 'path';

import * as vscode from 'vscode';

import { collectEnvironmentSearchRoots } from '../environment/paths.js';

export interface PythonEnvironment {
  path: string;
  version: string;
  env: NodeJS.ProcessEnv;
  pythonPath: string;
}

export interface PythonEnvironmentSelection {
  pythonPath: string;
  version?: string;
  source: 'activeInterpreter' | 'workspaceVenv';
  venvPath?: string;
}

type PythonEnvironmentQuickPickItem = PythonEnvironmentSelection & vscode.QuickPickItem;

export class PythonEnvironmentManager {
  private static readonly workspaceVenvDirs = ['.venv', 'venv', 'env', '.env'];

  private static async getPythonExtension() {
    const pythonExtension = vscode.extensions.getExtension('ms-python.python');
    if (!pythonExtension) {
      throw new Error('Python extension is not installed');
    }
    if (!pythonExtension.isActive) {
      await pythonExtension.activate();
    }
    return pythonExtension;
  }

  public static async getPythonEnvironment(workspaceFolder?: vscode.WorkspaceFolder): Promise<PythonEnvironment> {
    const pythonExtension = await this.getPythonExtension();
    const api = pythonExtension.exports;

    // Get the Python interpreter details
    const interpreter = await api.environments.resolveEnvironment(
      workspaceFolder ? workspaceFolder.uri : undefined
    );

    if (!interpreter) {
      throw new Error('No Python interpreter found');
    }

    // Get environment variables for the interpreter
    const env = await interpreter.envVars;

    return {
      path: interpreter.path,
      version: interpreter.version?.major + '.' + interpreter.version?.minor,
      env: env || {},
      pythonPath: interpreter.path
    };
  }

  public static async pickPythonEnvironment(
    workspaceFolder?: vscode.WorkspaceFolder,
    searchRootPath?: string,
  ): Promise<PythonEnvironmentSelection | undefined> {
    const items = await this.getEnvironmentQuickPickItems(workspaceFolder, searchRootPath);
    if (items.length === 0) {
      throw new Error('No Python environments were available to select.');
    }

    return vscode.window.showQuickPick(items, {
      title: 'Select Python Environment',
      placeHolder: 'Choose the interpreter for this Dapper launch.',
      matchOnDescription: true,
      matchOnDetail: true,
    });
  }

  private static async getEnvironmentQuickPickItems(
    workspaceFolder?: vscode.WorkspaceFolder,
    searchRootPath?: string,
  ): Promise<PythonEnvironmentQuickPickItem[]> {
    const items = new Map<string, PythonEnvironmentQuickPickItem>();

    try {
      const activeEnvironment = await this.getPythonEnvironment(workspaceFolder);
      const normalizedPath = this.normalizePath(activeEnvironment.pythonPath);
      items.set(normalizedPath, {
        label: 'Active Python interpreter',
        description: activeEnvironment.version ? `Python ${activeEnvironment.version}` : undefined,
        detail: activeEnvironment.pythonPath,
        pythonPath: activeEnvironment.pythonPath,
        version: activeEnvironment.version,
        source: 'activeInterpreter',
        venvPath: this.getVenvPathFromInterpreter(activeEnvironment.pythonPath),
      });
    } catch {
      // Ignore Python extension resolution failures and fall back to workspace venv discovery.
    }

    for (const folderPath of collectEnvironmentSearchRoots(searchRootPath, workspaceFolder)) {
      for (const venvDir of this.workspaceVenvDirs) {
        const venvPath = path.join(folderPath, venvDir);
        const pythonPath = this.getVenvPythonPath(venvPath);
        if (!fs.existsSync(pythonPath)) {
          continue;
        }

        const normalizedPath = this.normalizePath(pythonPath);
        if (items.has(normalizedPath)) {
          continue;
        }

        const relativeVenvPath = vscode.workspace.asRelativePath(vscode.Uri.file(venvPath), false);
        items.set(normalizedPath, {
          label: `Workspace venv: ${relativeVenvPath || venvDir}`,
          description: path.basename(folderPath),
          detail: pythonPath,
          pythonPath,
          source: 'workspaceVenv',
          venvPath,
        });
      }
    }

    return [...items.values()];
  }

  private static getVenvPathFromInterpreter(pythonPath: string): string | undefined {
    const interpreterDir = path.dirname(pythonPath);
    const parentDir = path.dirname(interpreterDir);
    const interpreterFolder = path.basename(interpreterDir);
    if (interpreterFolder !== 'bin' && interpreterFolder !== 'Scripts') {
      return undefined;
    }
    return parentDir;
  }

  private static getVenvPythonPath(venvPath: string): string {
    const binDir = process.platform === 'win32' ? 'Scripts' : 'bin';
    const pyExe = process.platform === 'win32' ? 'python.exe' : 'python';
    return path.join(venvPath, binDir, pyExe);
  }

  private static normalizePath(value: string): string {
    return process.platform === 'win32' ? value.toLowerCase() : value;
  }

  public static async getDebugLaunchConfig(
    program: string,
    args: string[] = [],
    env: NodeJS.ProcessEnv = {},
    workspaceFolder?: vscode.WorkspaceFolder
  ): Promise<vscode.DebugConfiguration> {
    const pythonEnv = await this.getPythonEnvironment(workspaceFolder);
    
    return {
      name: 'Python: Dapper Debug',
      type: 'python',
      request: 'launch',
      program,
      args,
      console: 'integratedTerminal',
      justMyCode: true,
      env: {
        ...pythonEnv.env,
        ...env,
        PYTHONPATH: [
          '${workspaceFolder}',
          pythonEnv.env.PYTHONPATH || ''
        ].filter(Boolean).join(':')
      },
      python: pythonEnv.pythonPath,
      pythonPath: pythonEnv.pythonPath
    };
  }

  public static async getDebugAdapterProcessArgs(
    program: string,
    args: string[] = [],
    env: NodeJS.ProcessEnv = {},
    workspaceFolder?: vscode.WorkspaceFolder
  ): Promise<{ command: string; args: string[]; options: { env: NodeJS.ProcessEnv; cwd?: string } }> {
    const pythonEnv = await this.getPythonEnvironment(workspaceFolder);
    
    // Prepare the command and arguments for the debug adapter
    const debugArgs = [
      '-m', 'debugpy', '--listen', '0',
      '--wait-for-client',
      program,
      ...args
    ];

    return {
      command: pythonEnv.pythonPath,
      args: debugArgs,
      options: {
        env: {
          ...process.env,
          ...pythonEnv.env,
          ...env,
          PYTHONPATH: [
            '${workspaceFolder}',
            pythonEnv.env.PYTHONPATH || ''
          ].filter(Boolean).join(':')
        },
        cwd: workspaceFolder?.uri.fsPath
      }
    };
  }
}
