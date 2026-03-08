import * as vscode from 'vscode';
import { DebugAdapterServer } from 'vscode';
import { spawn } from 'child_process';
import * as Net from 'net';
import * as os from 'os';
import { delimiter as pathDelimiter } from 'path';
import { EnvironmentManager, InstallMode } from '../environment/EnvironmentManager.js';
import { buildDefaultLogFilePath } from './logFileNaming.js';
import {
  type AttachByPidDiagnostic,
  type AttachRequestArguments,
  type LaunchRequestArguments,
} from './debugAdapterTypes.js';
import { DapperDebugSession, PythonDebugAdapterTransport } from './dapperDebugSession.js';
import type { DapperLaunchHistoryService } from '../views/DapperLaunchesView.js';

const ATTACH_BY_PID_DIAGNOSTIC_PREFIX = 'DAPPER_ATTACH_BY_PID_DIAGNOSTIC ';
const ATTACH_BY_PID_CONNECT_TIMEOUT_MS = 15_000;

class DapperAttachByPidError extends Error {
  public readonly userMessage: string;
  public readonly diagnostic?: AttachByPidDiagnostic;

  public constructor(userMessage: string, options?: { diagnostic?: AttachByPidDiagnostic; cause?: Error }) {
    super(userMessage);
    this.name = 'DapperAttachByPidError';
    this.userMessage = userMessage;
    this.diagnostic = options?.diagnostic;
    if (options?.cause) {
      (this as Error & { cause?: Error }).cause = options.cause;
    }
  }
}

export class MainSessionController {
  private _server?: Net.Server;
  private _serverPort?: number;
  private _adapterTerminal?: vscode.Terminal;
  private _pythonIpcServer?: Net.Server;
  private _mainTransport?: PythonDebugAdapterTransport;
  private _mainBootstrapPromise?: Promise<void>;
  private readonly _mainSessionIds = new Set<string>();
  private _terminalCloseDisposable?: vscode.Disposable;

  public constructor(
    private readonly _envManager: EnvironmentManager,
    private readonly _extensionVersion: string,
    private readonly _launchHistory?: DapperLaunchHistoryService,
  ) {}

  public get serverPort(): number | undefined {
    return this._serverPort;
  }

  public hasActiveServer(): boolean {
    return Boolean(this._server && this._serverPort != null);
  }

  public addSessionId(sessionId: string): void {
    this._mainSessionIds.add(sessionId);
  }

  public removeSessionId(sessionId: string): boolean {
    if (!this._mainSessionIds.delete(sessionId)) {
      return false;
    }
    return this._mainSessionIds.size === 0;
  }

  public createDirectAttachDescriptor(
    configuration: vscode.DebugConfiguration,
  ): DebugAdapterServer | undefined {
    if (configuration.request !== 'attach') {
      return undefined;
    }

    const processId = this._resolveProcessId(configuration);
    const host = typeof configuration.host === 'string' ? configuration.host.trim() : '';
    const rawPort = configuration.port;
    const port = typeof rawPort === 'number'
      ? rawPort
      : typeof rawPort === 'string' && rawPort.trim()
        ? Number(rawPort)
        : undefined;
    const program = typeof configuration.program === 'string' ? configuration.program.trim() : '';
    const moduleName = typeof configuration.module === 'string' ? configuration.module.trim() : '';

    const hasHostPort = Boolean(host) && Number.isInteger(port) && (port as number) > 0;
    if ((program && moduleName) || (hasHostPort && (program || moduleName)) || (processId != null && (program || moduleName))) {
      throw new Error('Provide exactly one target: processId, host/port, program, or module.');
    }
    if (processId != null && hasHostPort) {
      throw new Error('Provide exactly one attach target: processId or host/port.');
    }
    if (!hasHostPort) {
      return undefined;
    }

    return new DebugAdapterServer(port as number, host);
  }

  public async ensureMainSessionInfrastructure(session: vscode.DebugSession): Promise<void> {
    if (!this._mainBootstrapPromise) {
      this._mainBootstrapPromise = this._initializeMainSessionInfrastructure(session)
        .catch((error) => {
          this._mainBootstrapPromise = undefined;
          throw error;
        });
    }

    await this._mainBootstrapPromise;
  }

  public async createDebugAdapterDescriptor(session: vscode.DebugSession): Promise<DebugAdapterServer> {
    if (this._mainBootstrapPromise || !this.hasActiveServer()) {
      try {
        await this.ensureMainSessionInfrastructure(session);
      } catch (error) {
        const outChannel = this._envManager.getOutputChannel();
        this.reset();
        const message = error instanceof Error ? error.message : String(error);
        outChannel.error(`createDebugAdapterDescriptor failed: ${error instanceof Error ? error : message}`);
        this._envManager.showOutputChannel();
        const userMessage = error instanceof DapperAttachByPidError
          ? `${error.userMessage} See the 'Dapper Python Env' output channel for details.`
          : `Failed to initialize Dapper Python environment: ${message}. See the 'Dapper Python Env' output channel for details.`;
        vscode.window.showErrorMessage(userMessage);
        throw error;
      }
    }

    if (!this._server || this._serverPort == null) {
      throw new Error('Dapper adapter server was not created');
    }

    this.addSessionId(session.id);
    return new DebugAdapterServer(this._serverPort, '127.0.0.1');
  }

  public reset(): void {
    if (this._server) {
      this._server.close();
      this._server = undefined;
    }
    this._serverPort = undefined;
    if (this._pythonIpcServer) {
      this._pythonIpcServer.close();
      this._pythonIpcServer = undefined;
    }
    if (this._adapterTerminal) {
      this._adapterTerminal.dispose();
      this._adapterTerminal = undefined;
    }
    this._terminalCloseDisposable?.dispose();
    this._terminalCloseDisposable = undefined;
    this._mainTransport?.dispose();
    this._mainTransport = undefined;
    this._mainBootstrapPromise = undefined;
    this._mainSessionIds.clear();
  }

  public dispose(): void {
    this.reset();
  }

  private _extractAttachByPidDiagnostic(outputLines: string[]): AttachByPidDiagnostic | undefined {
    for (const line of outputLines) {
      const index = line.indexOf(ATTACH_BY_PID_DIAGNOSTIC_PREFIX);
      if (index === -1) {
        continue;
      }

      const payload = line.slice(index + ATTACH_BY_PID_DIAGNOSTIC_PREFIX.length).trim();
      if (!payload) {
        continue;
      }

      try {
        return JSON.parse(payload) as AttachByPidDiagnostic;
      } catch (error) {
        this._envManager.getOutputChannel().warn(
          `Failed to parse attach-by-PID diagnostic payload: ${error instanceof Error ? error.message : String(error)}`,
        );
      }
    }

    return undefined;
  }

  private _formatAttachByPidErrorMessage(
    processId: number,
    diagnostic: AttachByPidDiagnostic | undefined,
    fallbackDetail?: string,
  ): string {
    const parts: string[] = [];
    if (diagnostic?.message) {
      parts.push(diagnostic.message);
    } else {
      parts.push(`Attach by PID failed for process ${processId}.`);
    }
    if (diagnostic?.detail) {
      parts.push(`Detail: ${diagnostic.detail}`);
    } else if (fallbackDetail) {
      parts.push(`Detail: ${fallbackDetail}`);
    }
    if (diagnostic?.hint) {
      parts.push(`Hint: ${diagnostic.hint}`);
    }
    return parts.join(' ');
  }

  private async _waitForPythonIpcSocket(processId: number, outChannel: vscode.LogOutputChannel): Promise<void> {
    const transport = this._mainTransport;
    if (!transport) {
      throw new DapperAttachByPidError(`Attach by PID failed for process ${processId} before the IPC listener was ready.`);
    }

    await transport.waitForSocket(
      ATTACH_BY_PID_CONNECT_TIMEOUT_MS,
      [
        `Timed out waiting for process ${processId} to execute the injected attach bootstrap.`,
        'The target must be a live CPython 3.14 process with remote debugging enabled.',
        'Long-running native work or a blocked main thread can delay sys.remote_exec() reaching a safe evaluation point.',
      ].join(' '),
    );
    outChannel.info(`Attached process ${processId} connected back over IPC`);
  }

  private _resolveProcessId(config: vscode.DebugConfiguration): number | undefined {
    const raw = (config as AttachRequestArguments).processId;
    if (typeof raw === 'number' && Number.isFinite(raw) && raw > 0) {
      return raw;
    }
    if (typeof raw === 'string') {
      const trimmed = raw.trim();
      if (!trimmed) {
        return undefined;
      }
      const parsed = Number(trimmed);
      if (Number.isFinite(parsed) && parsed > 0) {
        return parsed;
      }
    }
    return undefined;
  }

  private _createPythonIpcServer(outChannel: vscode.LogOutputChannel): number {
    const transport = this._mainTransport ?? new PythonDebugAdapterTransport();
    this._mainTransport = transport;

    const pythonIpcServer = Net.createServer((pythonSocket) => {
      if (this._pythonIpcServer !== pythonIpcServer || this._mainTransport !== transport) {
        outChannel.warn('Rejecting unexpected extra Python IPC connection for active main session');
        pythonSocket.destroy();
        return;
      }

      this._pythonIpcServer = pythonIpcServer;
      pythonIpcServer.close();
      outChannel.info('Python debug adapter connected via IPC');
      transport.setPythonSocket(pythonSocket);
    }).listen(0);

    pythonIpcServer.on('error', (err: Error) => {
      outChannel.error(`Python IPC listener error: ${err.message}`);
    });

    this._pythonIpcServer = pythonIpcServer;
    return (pythonIpcServer.address() as Net.AddressInfo).port;
  }

  private _createAdapterServer(outChannel: vscode.LogOutputChannel): void {
    const server = Net.createServer((vscodeSocket) => {
      const transport = this._mainTransport;
      if (!transport) {
        outChannel.warn('Rejecting VS Code DAP connection before main transport was initialized');
        vscodeSocket.destroy();
        return;
      }

      outChannel.info('VS Code connected to DAP server');
      const sessionImpl = new DapperDebugSession(transport);
      sessionImpl.setRunAsServer(true);
      const detachSession = () => {
        sessionImpl.disposeTransportAttachment();
      };
      vscodeSocket.once('close', detachSession);
      vscodeSocket.once('error', detachSession);
      sessionImpl.start(vscodeSocket, vscodeSocket);
    }).listen(0);
    this._server = server;
    this._serverPort = (server.address() as Net.AddressInfo).port;
  }

  private async _initializeMainSessionInfrastructure(session: vscode.DebugSession): Promise<void> {
    const config = session.configuration;
    const attachConfig = config as AttachRequestArguments;
    const installMode = (vscode.workspace.getConfiguration('dapper.python').get<string>('installMode') || 'auto') as InstallMode;
    const forceReinstall = !!vscode.workspace.getConfiguration('dapper.python').get<boolean>('forceReinstall')
      || !!(config.forceReinstall as boolean | undefined);
    const outChannel = this._envManager.getOutputChannel();

    const envInfo = await this._envManager.prepareEnvironment(this._extensionVersion, installMode, forceReinstall, {
      workspaceFolder: session.workspaceFolder,
      preferredPythonPath: typeof config.pythonPath === 'string' ? config.pythonPath : undefined,
      preferredVenvPath: typeof config.venvPath === 'string' ? config.venvPath : undefined,
    });
    const pythonPath = envInfo.pythonPath;
    const cwd = (config.cwd as string | undefined) || session.workspaceFolder?.uri.fsPath || process.cwd();
    const { terminalEnv, logFile } = this._buildProcessEnv(
      envInfo,
      config as LaunchRequestArguments | AttachRequestArguments,
      session,
    );
    const launchToken = this._resolveLaunchToken(config);
    if (launchToken) {
      this._launchHistory?.updateLogFile(launchToken, logFile);
    }
    const processId = this._resolveProcessId(config);

    this._mainTransport = new PythonDebugAdapterTransport();
    const pythonIpcPort = this._createPythonIpcServer(outChannel);
    this._createAdapterServer(outChannel);

    if (config.request === 'launch') {
      const program = config.program as string | undefined;
      const moduleName = config.module as string | undefined;
      if (program && moduleName) {
        throw new Error('Provide exactly one launch target: program or module.');
      }
    }

    if (config.request === 'attach' && processId != null) {
      await this._spawnAttachByPidHelper(
        pythonPath,
        processId,
        pythonIpcPort,
        cwd,
        terminalEnv,
        attachConfig,
        outChannel,
      );
      outChannel.info(`Waiting for attached process ${processId} to connect back over IPC`);
      await this._waitForPythonIpcSocket(processId, outChannel);
      return;
    }

    const args: string[] = ['-m', 'dapper.launcher'];
    const program = config.program as string | undefined;
    const moduleName = config.module as string | undefined;
    if (program) {
      const programPath = String(program).replace(/\\/g, '/');
      args.push('--program', programPath);
    } else if (moduleName) {
      args.push('--module', String(moduleName));
    } else {
      vscode.window.showWarningMessage('Dapper: neither launch.program nor launch.module is set; debug launcher expects one launch target.');
    }

    if (Array.isArray(config.moduleSearchPaths)) {
      for (const p of config.moduleSearchPaths) {
        args.push('--module-search-path', String(p));
      }
    }
    if (config.args && Array.isArray(config.args)) {
      for (const a of config.args) {
        args.push('--arg', String(a));
      }
    }
    if (config.stopOnEntry) {
      args.push('--stop-on-entry');
    }
    if (config.noDebug) {
      args.push('--no-debug');
    }

    args.push('--ipc', 'tcp');
    args.push('--ipc-port', pythonIpcPort.toString());

    if (envInfo.dapperLibPath) {
      outChannel.info(`PYTHONPATH injection: ${envInfo.dapperLibPath}`);
    }

    outChannel.info(`Session log file: ${logFile}`);
    const sessionName = session.name || (config.name as string | undefined) || 'Debug';

    const adapterTerminal = vscode.window.createTerminal({
      name: `Dapper: ${sessionName}`,
      shellPath: pythonPath,
      shellArgs: args,
      cwd,
      env: terminalEnv,
      isTransient: true,
    });
    this._adapterTerminal = adapterTerminal;
    if (launchToken) {
      this._launchHistory?.attachTerminal(launchToken, adapterTerminal);
    }
    adapterTerminal.show(false);

    this._terminalCloseDisposable = vscode.window.onDidCloseTerminal((terminal) => {
      if (terminal !== adapterTerminal) {
        return;
      }
      this._terminalCloseDisposable?.dispose();
      this._terminalCloseDisposable = undefined;
      const code = terminal.exitStatus?.code ?? 0;
      outChannel.info(`Debug adapter exited with code ${code}`);
      if (code !== 0 && code !== undefined) {
        outChannel.error(`Debug adapter exited with non-zero code ${code}. Check the terminal output above.`);
        this._envManager.showOutputChannel();
        vscode.window.showErrorMessage(`Dapper debug adapter exited with code ${code}.`);
      }
      if (this._mainTransport) {
        outChannel.info('Sending ExitedEvent + TerminatedEvent from terminal close handler');
        this._mainTransport.notifyAdapterExited(code);
      } else {
        outChannel.warn('Terminal closed but no active debug transport to notify');
      }
      if (launchToken) {
        this._launchHistory?.detachTerminal(launchToken);
        this._launchHistory?.markTerminalExited(launchToken, code);
      }
      outChannel.info('Resetting adapter factory state after terminal exit');
      this.reset();
    });
  }

  private _resolveLaunchToken(config: vscode.DebugConfiguration): string | undefined {
    const candidate = config as Record<string, unknown>;
    return typeof candidate.__dapperLaunchToken === 'string' ? candidate.__dapperLaunchToken : undefined;
  }

  private _buildProcessEnv(
    envInfo: Awaited<ReturnType<EnvironmentManager['prepareEnvironment']>>,
    config: LaunchRequestArguments | AttachRequestArguments,
    session: vscode.DebugSession,
  ): { terminalEnv: Record<string, string>; logFile: string; debugLogLevel: string } {
    const debuggerConfig = vscode.workspace.getConfiguration('dapper.debugger');
    const configuredLogFile = (debuggerConfig.get<string>('logFile', '') || '').trim();
    let logFile: string;
    if (configuredLogFile) {
      const wsFolder = session.workspaceFolder?.uri.fsPath
        ?? vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
        ?? '';
      logFile = configuredLogFile.replace(/\$\{workspaceFolder\}/g, wsFolder);
      logFile = logFile.replace(/%([^%]+)%/g, (_match: string, name: string) => process.env[name] ?? `%${name}%`);
      if (process.platform !== 'win32') {
        logFile = logFile.replace(/\\/g, '/');
      }
    } else {
      logFile = buildDefaultLogFilePath('debug', session.id);
    }

    const debugLogLevel = (debuggerConfig.get<string>('logLevel', 'DEBUG') || 'DEBUG').toUpperCase();
    const rawEnv = {
      ...process.env,
      ...(config.env || {}),
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

    return { terminalEnv, logFile, debugLogLevel };
  }

  private async _spawnAttachByPidHelper(
    pythonPath: string,
    processId: number,
    pythonIpcPort: number,
    cwd: string,
    env: Record<string, string>,
    config: AttachRequestArguments,
    outChannel: vscode.LogOutputChannel,
  ): Promise<void> {
    const args: string[] = [
      '-m',
      'dapper.launcher.attach_by_pid',
      '--pid',
      String(processId),
      '--ipc',
      'tcp',
      '--ipc-port',
      String(pythonIpcPort),
    ];
    if (config.justMyCode === false) {
      args.push('--no-just-my-code');
    }
    if (config.strictExpressionWatchPolicy) {
      args.push('--strict-expression-watch-policy');
    }

    outChannel.info(`Launching attach helper for PID ${processId}: ${pythonPath} ${args.join(' ')}`);

    await new Promise<void>((resolve, reject) => {
      const child = spawn(pythonPath, args, {
        cwd,
        env,
        stdio: ['ignore', 'pipe', 'pipe'],
      });
      const outputLines: string[] = [];
      const onData = (chunk: Buffer) => {
        const text = chunk.toString().trimEnd();
        if (!text) {
          return;
        }
        outChannel.info(text);
        outputLines.push(text);
      };

      child.stdout?.on('data', onData);
      child.stderr?.on('data', onData);
      child.on('error', reject);
      child.on('close', (code) => {
        if (code === 0) {
          resolve();
          return;
        }
        const tail = outputLines.slice(-20).join('\n');
        const diagnostic = this._extractAttachByPidDiagnostic(outputLines);
        const fallbackDetail = `Attach helper exited with code ${code}${tail ? `:\n${tail}` : ''}`;
        reject(new DapperAttachByPidError(
          this._formatAttachByPidErrorMessage(processId, diagnostic, fallbackDetail),
          {
            diagnostic,
            cause: new Error(fallbackDetail),
          },
        ));
      });
    });
  }
}