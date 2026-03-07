import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import type { JournalRegistry, StateJournal } from '../agent/stateJournal.js';
import type { LaunchRequestArguments } from './dapperDebugAdapter.js';
import { PythonEnvironmentManager } from '../python/environment.js';
import { logger } from '../utils/logger.js';

const START_TIMEOUT_MS = 10_000;
const STOP_TIMEOUT_MS = 15_000;

export interface LaunchTargetInput {
  currentFile?: boolean;
  file?: string;
  module?: string;
  configName?: string;
}

export interface LaunchOptions {
  sessionName?: string;
  target?: LaunchTargetInput;
  args?: string[];
  cwd?: string;
  env?: Record<string, string>;
  moduleSearchPaths?: string[];
  venvPath?: string;
  pythonPath?: string;
  stopOnEntry?: boolean;
  justMyCode?: boolean;
  subprocessAutoAttach?: boolean;
  waitForStop?: boolean;
}

export interface LaunchResult {
  session: vscode.DebugSession;
  started: boolean;
  waitedForStop: boolean;
  stopped: boolean;
  pythonPath?: string;
  venvPath?: string;
  resolvedTarget: { kind: 'file' | 'module' | 'config'; value: string };
  configuration: vscode.DebugConfiguration;
}

interface ResolvedLaunchRequest {
  workspaceFolder?: vscode.WorkspaceFolder;
  config: vscode.DebugConfiguration & LaunchRequestArguments;
  resolvedTarget: LaunchResult['resolvedTarget'];
}

interface LaunchConfigurationWithToken extends vscode.DebugConfiguration, LaunchRequestArguments {
  __dapperLaunchToken?: string;
}

interface StartedSessionWaiter {
  promise: Promise<vscode.DebugSession>;
  cancel(): void;
}

export class LaunchService {
  constructor(private readonly registry: JournalRegistry) {}

  async launch(options: LaunchOptions, token?: vscode.CancellationToken): Promise<LaunchResult> {
    const resolved = await this._resolveLaunchRequest(options);
    const launchToken = this._createLaunchToken();
    const config = resolved.config as LaunchConfigurationWithToken;
    config.__dapperLaunchToken = launchToken;
    const startedSessionWaiter = this._waitForStartedSession(launchToken, resolved.config.name, token);

    logger.debug('LaunchService.launch: starting debug session', {
      name: resolved.config.name,
      target: resolved.resolvedTarget,
      workspaceFolder: resolved.workspaceFolder?.uri.fsPath,
      pythonPath: resolved.config.pythonPath,
      venvPath: resolved.config.venvPath,
      launchToken,
    });

    let started: boolean;
    try {
      started = await vscode.debug.startDebugging(resolved.workspaceFolder, resolved.config);
    } catch (error) {
      startedSessionWaiter.cancel();
      throw error;
    }
    if (!started) {
      startedSessionWaiter.cancel();
      throw new Error('VS Code did not start a Dapper debug session');
    }

    const session = await startedSessionWaiter.promise;
    const waitForStop = options.waitForStop ?? false;
    let stopped = false;
    if (waitForStop) {
      stopped = await this._waitForStop(session, token);
    }

    return {
      session,
      started,
      waitedForStop: waitForStop,
      stopped,
      pythonPath: typeof resolved.config.pythonPath === 'string' ? resolved.config.pythonPath : undefined,
      venvPath: typeof resolved.config.venvPath === 'string' ? resolved.config.venvPath : undefined,
      resolvedTarget: resolved.resolvedTarget,
      configuration: resolved.config,
    };
  }

  async launchCurrentFile(token?: vscode.CancellationToken): Promise<LaunchResult> {
    return this.launch({ target: { currentFile: true } }, token);
  }

  async waitForJournal(sessionId: string, token?: vscode.CancellationToken, timeoutMs = START_TIMEOUT_MS): Promise<StateJournal | undefined> {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      if (token?.isCancellationRequested) {
        return undefined;
      }
      const journal = this.registry.resolve(sessionId);
      if (journal) {
        return journal;
      }
      await this._delay(100);
    }
    return undefined;
  }

  private async _resolveLaunchRequest(options: LaunchOptions): Promise<ResolvedLaunchRequest> {
    const target = options.target ?? { currentFile: true };
    const targetModes = [target.currentFile ? 'currentFile' : undefined, target.file ? 'file' : undefined, target.module ? 'module' : undefined, target.configName ? 'configName' : undefined].filter(Boolean);
    if (targetModes.length > 1) {
      throw new Error('Choose exactly one launch target: currentFile, file, module, or configName');
    }

    if (options.pythonPath && !fs.existsSync(options.pythonPath)) {
      throw new Error(`Python interpreter does not exist: ${options.pythonPath}`);
    }
    if (options.venvPath) {
      const venvPython = this._pythonPathFromVenv(options.venvPath);
      if (!fs.existsSync(venvPython)) {
        throw new Error(`Virtual environment does not contain a Python interpreter: ${venvPython}`);
      }
    }

    if (target.configName) {
      return this._resolveNamedConfiguration(target.configName, options);
    }

    if (target.module) {
      const workspaceFolder = this._resolveWorkspaceFolderFromPath(options.cwd);
      const config = this._buildConfig(options, workspaceFolder, { module: target.module });
      await this._applyPreferredInterpreter(config, workspaceFolder, options);
      return {
        workspaceFolder,
        config,
        resolvedTarget: { kind: 'module', value: target.module },
      };
    }

    const filePath = target.file
      ? this._resolveFilePath(target.file)
      : this._currentPythonFile();

    if (!filePath) {
      throw new Error('No active Python file. Provide target.file, target.module, or use an active Python editor.');
    }
    if (!fs.existsSync(filePath)) {
      throw new Error(`Python file does not exist: ${filePath}`);
    }

    const workspaceFolder = vscode.workspace.getWorkspaceFolder(vscode.Uri.file(filePath))
      ?? this._resolveWorkspaceFolderFromPath(options.cwd)
      ?? vscode.workspace.workspaceFolders?.[0];
    const config = this._buildConfig(options, workspaceFolder, { program: filePath });
    await this._applyPreferredInterpreter(config, workspaceFolder, options);

    return {
      workspaceFolder,
      config,
      resolvedTarget: { kind: 'file', value: filePath },
    };
  }

  private _buildConfig(
    options: LaunchOptions,
    workspaceFolder: vscode.WorkspaceFolder | undefined,
    target: { program?: string; module?: string },
  ): vscode.DebugConfiguration & LaunchRequestArguments {
    const config: vscode.DebugConfiguration & LaunchRequestArguments = {
      type: 'dapper',
      request: 'launch',
      name: options.sessionName || this._defaultSessionName(target),
      console: 'integratedTerminal',
      stopOnEntry: options.stopOnEntry ?? true,
      justMyCode: options.justMyCode ?? true,
      subprocessAutoAttach: options.subprocessAutoAttach ?? false,
      cwd: options.cwd || workspaceFolder?.uri.fsPath || (target.program ? path.dirname(target.program) : undefined),
      env: options.env,
      args: options.args,
      moduleSearchPaths: options.moduleSearchPaths,
      pythonPath: options.pythonPath,
      venvPath: options.venvPath,
      ...target,
    };
    return config;
  }

  private async _resolveNamedConfiguration(configName: string, options: LaunchOptions): Promise<ResolvedLaunchRequest> {
    const workspaces = vscode.workspace.workspaceFolders ?? [];
    const candidates = workspaces.length > 0 ? workspaces : [undefined];

    for (const folder of candidates) {
      const saved = vscode.workspace.getConfiguration('dapper', folder?.uri).get<vscode.DebugConfiguration>('debug');
      if (saved?.name === configName) {
        const config = this._mergeNamedConfig(saved, options);
        await this._applyPreferredInterpreter(config, folder, options);
        return {
          workspaceFolder: folder,
          config,
          resolvedTarget: { kind: 'config', value: configName },
        };
      }

      const launchConfigurations = vscode.workspace.getConfiguration('launch', folder?.uri).get<vscode.DebugConfiguration[]>('configurations', []);
      const match = launchConfigurations.find((config) => config?.name === configName);
      if (!match) {
        continue;
      }
      if (match.type !== 'dapper' || match.request !== 'launch') {
        throw new Error(`Launch configuration '${configName}' is not a Dapper launch configuration`);
      }
      const config = this._mergeNamedConfig(match, options);
      await this._applyPreferredInterpreter(config, folder, options);
      return {
        workspaceFolder: folder,
        config,
        resolvedTarget: { kind: 'config', value: configName },
      };
    }

    throw new Error(`Launch configuration not found: ${configName}`);
  }

  private _mergeNamedConfig(
    baseConfig: vscode.DebugConfiguration,
    options: LaunchOptions,
  ): vscode.DebugConfiguration & LaunchRequestArguments {
    const merged: vscode.DebugConfiguration & LaunchRequestArguments = {
      ...baseConfig,
      type: 'dapper',
      request: 'launch',
      name: options.sessionName || String(baseConfig.name || 'Dapper: Launch'),
    };

    if (options.args) merged.args = options.args;
    if (options.cwd) merged.cwd = options.cwd;
    if (options.env) merged.env = { ...(baseConfig.env as Record<string, string> | undefined), ...options.env };
    if (options.moduleSearchPaths) merged.moduleSearchPaths = options.moduleSearchPaths;
    if (options.pythonPath) merged.pythonPath = options.pythonPath;
    if (options.venvPath) merged.venvPath = options.venvPath;
    if (options.stopOnEntry !== undefined) merged.stopOnEntry = options.stopOnEntry;
    if (options.justMyCode !== undefined) merged.justMyCode = options.justMyCode;
    if (options.subprocessAutoAttach !== undefined) merged.subprocessAutoAttach = options.subprocessAutoAttach;

    return merged;
  }

  private async _applyPreferredInterpreter(
    config: vscode.DebugConfiguration & LaunchRequestArguments,
    workspaceFolder: vscode.WorkspaceFolder | undefined,
    options: LaunchOptions,
  ): Promise<void> {
    if (config.pythonPath || config.venvPath || options.pythonPath || options.venvPath) {
      return;
    }
    try {
      const pythonEnv = await PythonEnvironmentManager.getPythonEnvironment(workspaceFolder);
      if (pythonEnv.pythonPath) {
        config.pythonPath = pythonEnv.pythonPath;
      }
    } catch (err) {
      logger.debug('LaunchService: no active Python extension interpreter available', {
        error: String(err),
      });
    }
  }

  private _resolveFilePath(file: string): string {
    if (path.isAbsolute(file)) {
      return path.normalize(file);
    }

    const workspaceFolder = this._resolveWorkspaceFolderFromPath(undefined) ?? vscode.workspace.workspaceFolders?.[0];
    if (workspaceFolder) {
      return path.normalize(path.join(workspaceFolder.uri.fsPath, file));
    }

    return path.resolve(file);
  }

  private _resolveWorkspaceFolderFromPath(cwd: string | undefined): vscode.WorkspaceFolder | undefined {
    if (cwd) {
      const cwdUri = vscode.Uri.file(path.resolve(cwd));
      return vscode.workspace.getWorkspaceFolder(cwdUri);
    }
    const editorUri = vscode.window.activeTextEditor?.document.uri;
    if (editorUri?.scheme === 'file') {
      return vscode.workspace.getWorkspaceFolder(editorUri);
    }
    return vscode.workspace.workspaceFolders?.[0];
  }

  private _currentPythonFile(): string | undefined {
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.document.languageId !== 'python' || editor.document.isUntitled || editor.document.uri.scheme !== 'file') {
      return undefined;
    }
    return editor.document.uri.fsPath;
  }

  private _defaultSessionName(target: { program?: string; module?: string }): string {
    if (target.program) {
      return `Debug ${path.basename(target.program)}`;
    }
    if (target.module) {
      return `Debug ${target.module}`;
    }
    return 'Dapper: Launch';
  }

  private _waitForStartedSession(
    launchToken: string,
    sessionName: string,
    token?: vscode.CancellationToken,
  ): StartedSessionWaiter {
    let settled = false;
    let startDisposable: vscode.Disposable | undefined;
    let timeout: NodeJS.Timeout | undefined;

    const clearResources = () => {
      if (timeout) {
        clearTimeout(timeout);
        timeout = undefined;
      }
      startDisposable?.dispose();
      startDisposable = undefined;
    };

    const promise = new Promise<vscode.DebugSession>((resolve, reject) => {
      timeout = setTimeout(() => {
        if (settled) {
          return;
        }
        settled = true;
        clearResources();
        reject(new Error(`Timed out waiting for Dapper session '${sessionName}' to start`));
      }, START_TIMEOUT_MS);

      startDisposable = vscode.debug.onDidStartDebugSession((session) => {
        if (settled) {
          return;
        }
        if (token?.isCancellationRequested) {
          settled = true;
          clearResources();
          reject(new Error('Launch cancelled'));
          return;
        }

        if (session.type !== 'dapper') {
          return;
        }

        const sessionToken = (session.configuration as LaunchConfigurationWithToken | undefined)?.__dapperLaunchToken;
        if (sessionToken !== launchToken) {
          return;
        }

        settled = true;
        clearResources();
        resolve(session);
      });
    });

    return {
      promise,
      cancel: () => {
        if (settled) {
          return;
        }
        settled = true;
        clearResources();
      },
    };
  }

  private async _waitForStop(session: vscode.DebugSession, token?: vscode.CancellationToken): Promise<boolean> {
    let journal = this.registry.resolve(session.id);
    const baselineCheckpoint = journal?.checkpoint ?? 0;
    if (this._journalShowsStopped(journal)) {
      return true;
    }

    return new Promise<boolean>((resolve) => {
      let settled = false;
      let pollHandle: NodeJS.Timeout | undefined;

      const finish = (value: boolean) => {
        if (settled) {
          return;
        }
        settled = true;
        if (pollHandle) {
          clearTimeout(pollHandle);
        }
        clearTimeout(timeout);
        terminateDisposable.dispose();
        resolve(value);
      };

      const checkJournal = () => {
        if (token?.isCancellationRequested) {
          finish(false);
          return;
        }

        journal = this.registry.resolve(session.id) ?? journal;
        if (this._journalShowsStopped(journal)) {
          finish(true);
          return;
        }
        if (this._journalShowsTerminated(journal, baselineCheckpoint)) {
          finish(false);
          return;
        }

        if (!settled) {
          pollHandle = setTimeout(checkJournal, 50);
        }
      };

      const timeout = setTimeout(() => {
        finish(false);
      }, STOP_TIMEOUT_MS);

      const terminateDisposable = vscode.debug.onDidTerminateDebugSession((terminatedSession) => {
        if (terminatedSession.id === session.id) {
          finish(false);
        }
      });

      checkJournal();
    });
  }

  private _journalShowsStopped(journal: StateJournal | undefined): boolean {
    return Boolean(journal?.lastSnapshot?.stoppedThreads?.length);
  }

  private _journalShowsTerminated(
    journal: StateJournal | undefined,
    sinceCheckpoint: number,
  ): boolean {
    return Boolean(
      journal?.getRecentHistory(20).some(
        entry => entry.type === 'terminated' && entry.checkpoint > sinceCheckpoint,
      ),
    );
  }

  private _pythonPathFromVenv(venvPath: string): string {
    return process.platform === 'win32'
      ? path.join(venvPath, 'Scripts', 'python.exe')
      : path.join(venvPath, 'bin', 'python');
  }

  private _createLaunchToken(): string {
    return `dapper-launch-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }

  private _delay(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}