import * as fs from 'fs';
import * as path from 'path';

import * as vscode from 'vscode';

import { collectEnvironmentSearchRoots } from '../environment/paths.js';
import { runLoggedProcessResult } from '../environment/processRunner.js';
import { PythonEnvironmentManager } from './environment.js';

type PythonEnvironmentSource = 'activeInterpreter' | 'workspaceVenv' | 'none';
type ToolResolutionKind = 'python-module' | 'venv-executable' | 'path-command' | 'none';
type TyConfigKind = 'pyproject' | 'ty.toml' | '.ty.toml';
type RuffConfigKind = 'pyproject' | 'ruff.toml' | '.ruff.toml';

export interface EnvironmentSnapshotOptions {
  workspaceFolder?: vscode.WorkspaceFolder;
  searchRootPath?: string;
}

export interface TyConfigFileSnapshot {
  kind: TyConfigKind;
  path: string;
  hasTySection?: boolean;
}

export interface RuffConfigFileSnapshot {
  kind: RuffConfigKind;
  path: string;
  hasRuffSection?: boolean;
}

interface ToolAvailabilitySnapshot {
  available: boolean;
  resolution: ToolResolutionKind;
  command?: string;
  args: string[];
  version?: string;
  error?: string;
}

export interface PythonToolingEnvironmentSnapshot {
  generatedAt: string;
  workspaceFolder?: string;
  searchRootPath?: string;
  searchRoots: string[];
  python: {
    available: boolean;
    source: PythonEnvironmentSource;
    pythonPath?: string;
    version?: string;
    venvPath?: string;
    error?: string;
  };
  ty: {
    available: boolean;
    resolution: ToolResolutionKind;
    command?: string;
    args: string[];
    version?: string;
    error?: string;
  };
  ruff: {
    available: boolean;
    resolution: ToolResolutionKind;
    command?: string;
    args: string[];
    version?: string;
    error?: string;
  };
  tyConfig: {
    configured: boolean;
    files: TyConfigFileSnapshot[];
  };
  ruffConfig: {
    configured: boolean;
    files: RuffConfigFileSnapshot[];
  };
}

interface ResolvedPythonEnvironment {
  available: boolean;
  source: PythonEnvironmentSource;
  pythonPath?: string;
  version?: string;
  venvPath?: string;
  error?: string;
}

const WORKSPACE_VENV_DIRS = ['.venv', 'venv', 'env', '.env'];

export class EnvironmentSnapshotService {
  constructor(private readonly output: vscode.LogOutputChannel) {}

  async getSnapshot(options: EnvironmentSnapshotOptions = {}): Promise<PythonToolingEnvironmentSnapshot> {
    const searchRoots = collectEnvironmentSearchRoots(options.searchRootPath, options.workspaceFolder);
    const python = await this._resolvePythonEnvironment(options.workspaceFolder, searchRoots);
    const ty = await this._resolveTy(python);
    const ruff = await this._resolveRuff(python);
    const tyConfig = this._detectTyConfig(searchRoots);
    const ruffConfig = this._detectRuffConfig(searchRoots);

    return {
      generatedAt: new Date().toISOString(),
      workspaceFolder: options.workspaceFolder?.uri.fsPath,
      searchRootPath: options.searchRootPath,
      searchRoots,
      python,
      ty,
      ruff,
      tyConfig,
      ruffConfig,
    };
  }

  private async _resolvePythonEnvironment(
    workspaceFolder: vscode.WorkspaceFolder | undefined,
    searchRoots: string[],
  ): Promise<ResolvedPythonEnvironment> {
    try {
      const environment = await PythonEnvironmentManager.getPythonEnvironment(workspaceFolder);
      return {
        available: true,
        source: 'activeInterpreter',
        pythonPath: environment.pythonPath,
        version: environment.version,
        venvPath: this._getVenvPathFromInterpreter(environment.pythonPath),
      };
    } catch (error) {
      const fallback = this._findWorkspaceVenv(searchRoots);
      if (fallback) {
        return {
          available: true,
          source: 'workspaceVenv',
          pythonPath: fallback.pythonPath,
          venvPath: fallback.venvPath,
        };
      }

      return {
        available: false,
        source: 'none',
        error: error instanceof Error ? error.message : String(error),
      };
    }
  }

  private async _resolveTy(python: ResolvedPythonEnvironment): Promise<PythonToolingEnvironmentSnapshot['ty']> {
    return this._resolveTool(
      python,
      'ty',
      'probe ty via python -m ty',
      'probe ty via venv executable',
      'probe ty via PATH',
      'Ty was not found in the selected Python environment or on PATH.',
    );
  }

  private async _resolveRuff(python: ResolvedPythonEnvironment): Promise<PythonToolingEnvironmentSnapshot['ruff']> {
    return this._resolveTool(
      python,
      'ruff',
      'probe ruff via python -m ruff',
      'probe ruff via venv executable',
      'probe ruff via PATH',
      'Ruff was not found in the selected Python environment or on PATH.',
    );
  }

  private async _resolveTool(
    python: ResolvedPythonEnvironment,
    moduleName: 'ty' | 'ruff',
    pythonModuleLabel: string,
    venvExecutableLabel: string,
    pathLabel: string,
    missingMessage: string,
  ): Promise<ToolAvailabilitySnapshot> {
    if (python.pythonPath) {
      const moduleResult = await runLoggedProcessResult(
        this.output,
        python.pythonPath,
        ['-m', moduleName, '--version'],
        { label: pythonModuleLabel },
      );
      if (moduleResult.ok) {
        return {
          available: true,
          resolution: 'python-module',
          command: python.pythonPath,
          args: ['-m', moduleName],
          version: this._extractVersion(moduleResult.stdout),
        };
      }
    }

    if (python.venvPath) {
      const candidate = this._getToolExecutablePath(python.venvPath, moduleName);
      if (fs.existsSync(candidate)) {
        const executableResult = await runLoggedProcessResult(
          this.output,
          candidate,
          ['--version'],
          { label: venvExecutableLabel },
        );
        if (executableResult.ok) {
          return {
            available: true,
            resolution: 'venv-executable',
            command: candidate,
            args: [],
            version: this._extractVersion(executableResult.stdout),
          };
        }
      }
    }

    const pathCommand = process.platform === 'win32' ? `${moduleName}.exe` : moduleName;
    const pathResult = await runLoggedProcessResult(
      this.output,
      pathCommand,
      ['--version'],
      { label: pathLabel },
    );
    if (pathResult.ok) {
      return {
        available: true,
        resolution: 'path-command',
        command: pathCommand,
        args: [],
        version: this._extractVersion(pathResult.stdout),
      };
    }

    return {
      available: false,
      resolution: 'none',
      args: [],
      error: pathResult.error?.message ?? (pathResult.stderr || pathResult.output || missingMessage),
    };
  }

  private _detectTyConfig(searchRoots: string[]): PythonToolingEnvironmentSnapshot['tyConfig'] {
    const files: TyConfigFileSnapshot[] = [];
    const seen = new Set<string>();

    for (const root of searchRoots) {
      const pyprojectPath = path.join(root, 'pyproject.toml');
      if (fs.existsSync(pyprojectPath) && !seen.has(pyprojectPath)) {
        seen.add(pyprojectPath);
        const content = this._readFile(pyprojectPath);
        const hasTySection = /\[tool\.ty(?:\.|\])/.test(content);
        if (hasTySection) {
          files.push({ kind: 'pyproject', path: pyprojectPath, hasTySection });
        }
      }

      for (const filename of ['ty.toml', '.ty.toml'] as const) {
        const configPath = path.join(root, filename);
        if (!fs.existsSync(configPath) || seen.has(configPath)) {
          continue;
        }
        seen.add(configPath);
        files.push({ kind: filename === 'ty.toml' ? 'ty.toml' : '.ty.toml', path: configPath });
      }
    }

    return {
      configured: files.length > 0,
      files,
    };
  }

  private _detectRuffConfig(searchRoots: string[]): PythonToolingEnvironmentSnapshot['ruffConfig'] {
    const files: RuffConfigFileSnapshot[] = [];
    const seen = new Set<string>();

    for (const root of searchRoots) {
      const pyprojectPath = path.join(root, 'pyproject.toml');
      if (fs.existsSync(pyprojectPath) && !seen.has(pyprojectPath)) {
        seen.add(pyprojectPath);
        const content = this._readFile(pyprojectPath);
        const hasRuffSection = /\[tool\.ruff(?:\.|\])/.test(content);
        if (hasRuffSection) {
          files.push({ kind: 'pyproject', path: pyprojectPath, hasRuffSection });
        }
      }

      for (const filename of ['ruff.toml', '.ruff.toml'] as const) {
        const configPath = path.join(root, filename);
        if (!fs.existsSync(configPath) || seen.has(configPath)) {
          continue;
        }
        seen.add(configPath);
        files.push({ kind: filename === 'ruff.toml' ? 'ruff.toml' : '.ruff.toml', path: configPath });
      }
    }

    return {
      configured: files.length > 0,
      files,
    };
  }

  private _findWorkspaceVenv(searchRoots: string[]): { pythonPath: string; venvPath: string } | undefined {
    for (const root of searchRoots) {
      for (const dirname of WORKSPACE_VENV_DIRS) {
        const venvPath = path.join(root, dirname);
        const pythonPath = this._getPythonPath(venvPath);
        if (fs.existsSync(pythonPath)) {
          return { pythonPath, venvPath };
        }
      }
    }
    return undefined;
  }

  private _getVenvPathFromInterpreter(pythonPath: string): string | undefined {
    const interpreterDir = path.dirname(pythonPath);
    const parentDir = path.dirname(interpreterDir);
    const interpreterFolder = path.basename(interpreterDir);
    if (interpreterFolder !== 'bin' && interpreterFolder !== 'Scripts') {
      return undefined;
    }
    return parentDir;
  }

  private _getPythonPath(venvPath: string): string {
    return process.platform === 'win32'
      ? path.join(venvPath, 'Scripts', 'python.exe')
      : path.join(venvPath, 'bin', 'python');
  }

  private _getToolExecutablePath(venvPath: string, executableName: 'ty' | 'ruff'): string {
    return process.platform === 'win32'
      ? path.join(venvPath, 'Scripts', `${executableName}.exe`)
      : path.join(venvPath, 'bin', executableName);
  }

  private _extractVersion(output: string): string | undefined {
    const match = output.match(/(\d+\.\d+\.\d+(?:[-+._a-zA-Z0-9]*)?)/);
    return match?.[1];
  }

  private _readFile(filePath: string): string {
    try {
      return fs.readFileSync(filePath, 'utf8');
    } catch {
      return '';
    }
  }
}