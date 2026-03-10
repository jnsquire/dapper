import * as Net from 'net';
import { delimiter as pathDelimiter } from 'path';
import * as vscode from 'vscode';
import { EnvironmentManager, InstallMode, type PythonEnvInfo } from '../environment/EnvironmentManager.js';
import { buildDefaultLogFilePath } from './logFileNaming.js';
import type { LaunchRequestArguments } from './debugAdapterTypes.js';
import { PythonDebugAdapterTransport, type TransportSession } from './pythonDebugAdapterTransport.js';
import { logger } from '../utils/logger.js';
import type { DapperLaunchHistoryService } from '../views/DapperLaunchesView.js';

export interface NoDebugLaunchHandler {
  launch(
    configuration: vscode.DebugConfiguration & LaunchRequestArguments,
    workspaceFolder?: vscode.WorkspaceFolder,
  ): Promise<NoDebugLaunchResult>;
}

export interface NoDebugLaunchResult {
  started: boolean;
  pythonPath: string;
  venvPath?: string;
}

class SessionlessLaunchTracker implements TransportSession {
  public constructor(
    private readonly _launchToken: string | undefined,
    private readonly _launchHistory?: DapperLaunchHistoryService,
  ) {}

  public handleTransportMessage(message: any): void {
    if (!this._launchToken) {
      return;
    }

    const body = message?.body ?? {};
    if (message?.event === 'process') {
      this._launchHistory?.updateProcessForLaunch(this._launchToken, body);
      return;
    }

    if (message?.event === 'exited') {
      const exitCode = typeof body.exitCode === 'number' ? body.exitCode : undefined;
      this._launchHistory?.markLaunchExited(this._launchToken, exitCode);
    }
  }

  public handleTransportClosed(_exitCode: number): void {}
}

export class DapperNoDebugLauncher implements NoDebugLaunchHandler {
  private readonly _envManager: EnvironmentManager;

  public constructor(
    context: vscode.ExtensionContext,
    private readonly _extensionVersion: string,
    private readonly _launchHistory?: DapperLaunchHistoryService,
  ) {
    this._envManager = new EnvironmentManager(context, logger.getChannel());
  }

  public async launch(
    configuration: vscode.DebugConfiguration & LaunchRequestArguments,
    workspaceFolder?: vscode.WorkspaceFolder,
  ): Promise<NoDebugLaunchResult> {
    const installMode = (vscode.workspace.getConfiguration('dapper.python').get<string>('installMode') || 'auto') as InstallMode;
    const forceReinstall = !!vscode.workspace.getConfiguration('dapper.python').get<boolean>('forceReinstall')
      || !!(configuration.forceReinstall as boolean | undefined);

    const envInfo = await this._envManager.prepareEnvironment(this._extensionVersion, installMode, forceReinstall, {
      workspaceFolder,
      preferredPythonPath: typeof configuration.pythonPath === 'string' ? configuration.pythonPath : undefined,
      preferredVenvPath: typeof configuration.venvPath === 'string' ? configuration.venvPath : undefined,
      allowInstallToPreferredInterpreter: configuration.__dapperExplicitEnvironmentSelection === true,
      searchRootPath: typeof configuration.__dapperEnvironmentSearchRoot === 'string' ? configuration.__dapperEnvironmentSearchRoot : undefined,
    });

    const pythonPath = envInfo.pythonPath;
    const cwd = (configuration.cwd as string | undefined) || workspaceFolder?.uri.fsPath || process.cwd();
    const launchToken = this._resolveLaunchToken(configuration);
    const sessionName = (configuration.name as string | undefined) || 'Run';
    const runId = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const { terminalEnv, logFile } = this._buildProcessEnv(envInfo, configuration, workspaceFolder, runId);
    if (launchToken) {
      this._launchHistory?.updateLogFile(launchToken, logFile);
    }

    const transport = new PythonDebugAdapterTransport();
    transport.attachSession(new SessionlessLaunchTracker(launchToken, this._launchHistory));

    const pythonIpcServer = Net.createServer((pythonSocket) => {
      pythonIpcServer.close();
      transport.setPythonSocket(pythonSocket);
    });
    pythonIpcServer.on('error', (error: Error) => {
      logger.error('No-debug IPC listener error', error);
    });

    await new Promise<void>((resolve, reject) => {
      pythonIpcServer.once('error', reject);
      pythonIpcServer.listen(0, '127.0.0.1', () => {
        pythonIpcServer.off('error', reject);
        resolve();
      });
    });

    const pythonIpcPort = (pythonIpcServer.address() as Net.AddressInfo).port;
    const args = this._buildLauncherArgs(configuration, pythonIpcPort);

    logger.debug('DapperNoDebugLauncher.launch', {
      name: sessionName,
      workspaceFolder: workspaceFolder?.uri.fsPath,
      pythonPath,
      venvPath: envInfo.venvPath,
      launchToken,
    });

    let terminal: vscode.Terminal | undefined;
    let closeDisposable: vscode.Disposable | undefined;
    try {
      terminal = vscode.window.createTerminal({
        name: `Dapper: ${sessionName}`,
        shellPath: pythonPath,
        shellArgs: args,
        cwd,
        env: terminalEnv,
        isTransient: true,
      });
      if (launchToken) {
        this._launchHistory?.attachTerminal(launchToken, terminal);
      }

      closeDisposable = vscode.window.onDidCloseTerminal((closedTerminal) => {
        if (closedTerminal !== terminal) {
          return;
        }

        closeDisposable?.dispose();
        closeDisposable = undefined;
        const exitCode = closedTerminal.exitStatus?.code ?? 0;
        logger.log(`No-debug launcher exited with code ${exitCode}`);
        if (launchToken) {
          this._launchHistory?.detachTerminal(launchToken);
          this._launchHistory?.markTerminalExited(launchToken, exitCode);
        }
        transport.dispose();
        pythonIpcServer.close();
      });

      terminal.show(false);
      return {
        started: true,
        pythonPath,
        venvPath: envInfo.venvPath,
      };
    } catch (error) {
      closeDisposable?.dispose();
      if (launchToken) {
        this._launchHistory?.detachTerminal(launchToken);
      }
      transport.dispose();
      pythonIpcServer.close();
      terminal?.dispose();
      throw error;
    }
  }

  private _buildLauncherArgs(
    configuration: vscode.DebugConfiguration & LaunchRequestArguments,
    pythonIpcPort: number,
  ): string[] {
    const args: string[] = ['-m', 'dapper.launcher'];
    const program = configuration.program as string | undefined;
    const moduleName = configuration.module as string | undefined;

    if (program) {
      args.push('--program', String(program).replace(/\\/g, '/'));
    } else if (moduleName) {
      args.push('--module', String(moduleName));
    } else {
      throw new Error('Provide exactly one launch target: program or module.');
    }

    if (Array.isArray(configuration.moduleSearchPaths)) {
      for (const moduleSearchPath of configuration.moduleSearchPaths) {
        args.push('--module-search-path', String(moduleSearchPath));
      }
    }
    if (Array.isArray(configuration.args)) {
      for (const arg of configuration.args) {
        args.push('--arg', String(arg));
      }
    }
    if (configuration.stopOnEntry) {
      args.push('--stop-on-entry');
    }
    args.push('--no-debug');
    args.push('--ipc', 'tcp');
    args.push('--ipc-port', String(pythonIpcPort));
    return args;
  }

  private _buildProcessEnv(
    envInfo: PythonEnvInfo,
    configuration: LaunchRequestArguments,
    workspaceFolder: vscode.WorkspaceFolder | undefined,
    runId: string,
  ): { terminalEnv: Record<string, string>; logFile: string } {
    const debuggerConfig = vscode.workspace.getConfiguration('dapper.debugger');
    const configuredLogFile = (debuggerConfig.get<string>('logFile', '') || '').trim();
    let logFile: string;
    if (configuredLogFile) {
      const wsFolder = workspaceFolder?.uri.fsPath
        ?? vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
        ?? '';
      logFile = configuredLogFile.replace(/\$\{workspaceFolder\}/g, wsFolder);
      logFile = logFile.replace(/%([^%]+)%/g, (_match: string, name: string) => process.env[name] ?? `%${name}%`);
      if (process.platform !== 'win32') {
        logFile = logFile.replace(/\\/g, '/');
      }
    } else {
      logFile = buildDefaultLogFilePath('run', runId);
    }

    const debugLogLevel = (debuggerConfig.get<string>('logLevel', 'DEBUG') || 'DEBUG').toUpperCase();
    const rawEnv = {
      ...process.env,
      ...(configuration.env || {}),
      DAPPER_MANAGED_VENV: envInfo.venvPath || '',
      DAPPER_VERSION_EXPECTED: this._extensionVersion,
      DAPPER_LOG_FILE: logFile,
      DAPPER_LOG_LEVEL: debugLogLevel,
    };
    const terminalEnv: Record<string, string> = {};
    for (const [key, value] of Object.entries(rawEnv)) {
      if (typeof value === 'string') {
        terminalEnv[key] = value;
      }
    }

    if (envInfo.dapperLibPath) {
      const existing = terminalEnv.PYTHONPATH || '';
      terminalEnv.PYTHONPATH = existing
        ? `${envInfo.dapperLibPath}${pathDelimiter}${existing}`
        : envInfo.dapperLibPath;
    }

    return { terminalEnv, logFile };
  }

  private _resolveLaunchToken(configuration: vscode.DebugConfiguration): string | undefined {
    const candidate = configuration as Record<string, unknown>;
    return typeof candidate.__dapperLaunchToken === 'string' ? candidate.__dapperLaunchToken : undefined;
  }
}