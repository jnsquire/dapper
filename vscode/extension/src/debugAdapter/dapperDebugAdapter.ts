import * as vscode from 'vscode';
import { DebugAdapterDescriptor, DebugAdapterExecutable, ProviderResult, DebugAdapterServer } from 'vscode';
import {
    LoggingDebugSession,
    InitializedEvent, TerminatedEvent, StoppedEvent, OutputEvent,
    Thread, StackFrame, Scope, Source, Handles, Breakpoint
} from '@vscode/debugadapter';
import { DebugProtocol } from '@vscode/debugprotocol';
import * as Net from 'net';
import * as path from 'path';
import { fileURLToPath } from 'url';
import { dirname } from 'path';
import { EnvironmentManager, InstallMode } from '../env/EnvironmentManager.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Define the debug configuration type that we expect
export interface LaunchRequestArguments extends DebugProtocol.LaunchRequestArguments {
  program: string;
  args?: string[];
  stopOnEntry?: boolean;
  console?: 'internalConsole' | 'integratedTerminal' | 'externalTerminal';
  cwd?: string;
  env?: { [key: string]: string };
}

export class DapperDebugSession extends LoggingDebugSession {
  // We don't support multiple threads, so we can use a constant for the default thread ID
  private static readonly THREAD_ID = 1;
  private _configurationDone = false;
  private _isRunning = false;

  public constructor() {
    super();
    this.setDebuggerLinesStartAt1(false);
    this.setDebuggerColumnsStartAt1(false);
  }

  protected initializeRequest(
    response: DebugProtocol.InitializeResponse,
    _args: DebugProtocol.InitializeRequestArguments
  ): void {
    response.body = response.body || {};
    response.body.supportsConfigurationDoneRequest = true;
    response.body.supportsSetVariable = true;
    response.body.supportsEvaluateForHovers = true;
    response.body.supportsStepBack = false;

    this.sendResponse(response);
    this.sendEvent(new InitializedEvent());
  }

  protected configurationDoneRequest(
    response: DebugProtocol.ConfigurationDoneResponse,
    _args: DebugProtocol.ConfigurationDoneArguments,
    _request?: DebugProtocol.Request
  ): void {
    this._configurationDone = true;
    this.sendResponse(response);
  }

  protected async launchRequest(
    response: DebugProtocol.LaunchResponse,
    args: LaunchRequestArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    this._isRunning = true;
    this.sendResponse(response);
    // TODO: Implement actual launch logic
  }

  protected async disconnectRequest(
    response: DebugProtocol.DisconnectResponse,
    _args: DebugProtocol.DisconnectArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    this._isRunning = false;
    this.sendResponse(response);
  }

  protected async setBreakPointsRequest(
    response: DebugProtocol.SetBreakpointsResponse,
    args: DebugProtocol.SetBreakpointsArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    // TODO: Implement breakpoint setting logic
    response.body = {
      breakpoints: []
    };
    this.sendResponse(response);
  }

  protected threadsRequest(
    response: DebugProtocol.ThreadsResponse,
    _request?: DebugProtocol.Request
  ): void {
    response.body = {
      threads: [
        {
          id: DapperDebugSession.THREAD_ID,
          name: 'Thread 1'
        }
      ]
    };
    this.sendResponse(response);
  }

  protected async stackTraceRequest(
    response: DebugProtocol.StackTraceResponse,
    _args: DebugProtocol.StackTraceArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    // TODO: Implement stack trace logic
    response.body = {
      stackFrames: [],
      totalFrames: 0
    };
    this.sendResponse(response);
  }

  protected scopesRequest(
    response: DebugProtocol.ScopesResponse,
    _args: DebugProtocol.ScopesArguments,
    _request?: DebugProtocol.Request
  ): void {
    // TODO: Implement scopes logic
    response.body = {
      scopes: []
    };
    this.sendResponse(response);
  }

  protected variablesRequest(
    response: DebugProtocol.VariablesResponse,
    _args: DebugProtocol.VariablesArguments,
    _request?: DebugProtocol.Request
  ): void {
    // TODO: Implement variables logic
    response.body = {
      variables: []
    };
    this.sendResponse(response);
  }
}

export class DapperDebugAdapterDescriptorFactory implements vscode.DebugAdapterDescriptorFactory, vscode.Disposable {
  private server?: Net.Server;
  private childProcess?: any; // Child process for the debug adapter
  private readonly envManager: EnvironmentManager;
  private readonly extensionVersion: string;

  constructor(private readonly context: vscode.ExtensionContext) {
    this.envManager = new EnvironmentManager(context);
    this.extensionVersion = context.extension.packageJSON.version || '0.0.0';
  }

  async createDebugAdapterDescriptor(
    session: vscode.DebugSession,
    _executable: DebugAdapterExecutable | undefined
  ): Promise<DebugAdapterDescriptor> {
    if (!this.server) {
      try {
        const config = session.configuration;
        const installMode = (vscode.workspace.getConfiguration('dapper.python').get<string>('installMode') || 'auto') as InstallMode;
        const forceReinstall = !!vscode.workspace.getConfiguration('dapper.python').get<boolean>('forceReinstall');

        // Prepare environment (create venv & install dapper if needed)
        const envInfo = await this.envManager.prepareEnvironment(this.extensionVersion, installMode, forceReinstall);
        const pythonPath = envInfo.pythonPath;

        // Build arguments: use dapper.debug_launcher CLI
        const args: string[] = ['-m', 'dapper.debug_launcher'];
        const program = config.program as string | undefined;
        if (program) {
          const programPath = String(program).replace(/\\/g, '/');
          args.push('--program', programPath);
        } else {
          vscode.window.showWarningMessage('Dapper: launch.program not set; debug launcher expects a program path.');
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

        // Create server for VS Code <-> adapter Protocol
        const server = Net.createServer(socket => {
          const sessionImpl = new DapperDebugSession();
          (sessionImpl as any).setRunAsServer(true);
          (sessionImpl as any).start(socket as NodeJS.ReadableStream, socket);
        }).listen(0);
        this.server = server;

        const envVars = {
          ...process.env,
          ...(config.env || {}),
          // Provide explicit indicator of managed environment
          DAPPER_MANAGED_VENV: envInfo.venvPath || '',
          DAPPER_VERSION_EXPECTED: this.extensionVersion,
        };

        // Spawn adapter process
        this.childProcess = require('child_process').spawn(pythonPath, args, {
          cwd: config.cwd || process.cwd(),
          env: envVars,
          stdio: ['pipe', 'pipe', 'pipe'],
          shell: process.platform === 'win32'
        });

        const outChannel = this.envManager.getOutputChannel();
        this.childProcess.stdout.on('data', (data: Buffer) => {
          outChannel.appendLine(`[adapter stdout] ${data.toString().trim()}`);
        });
        this.childProcess.stderr.on('data', (data: Buffer) => {
          outChannel.appendLine(`[adapter stderr] ${data.toString().trim()}`);
        });
        this.childProcess.on('error', (err: Error) => {
          outChannel.appendLine(`[ERROR] Debug adapter spawn failed: ${err.message}`);
          vscode.window.showErrorMessage(`Failed to start Dapper debug adapter: ${err.message}`);
        });
        this.childProcess.on('exit', (code: number) => {
          outChannel.appendLine(`[INFO] Debug adapter exited with code ${code}`);
          if (code !== 0) {
            vscode.window.showErrorMessage(`Dapper debug adapter process exited with code ${code}`);
          }
        });
      } catch (error) {
        console.error('Error creating debug adapter:', error);
        vscode.window.showErrorMessage('Failed to initialize Dapper Python environment.');
        throw error;
      }
    }

    // Connect to the debug adapter server
    return new DebugAdapterServer(
      (this.server.address() as Net.AddressInfo).port,
      '127.0.0.1'
    );
  }

  dispose() {
    if (this.server) {
      this.server.close();
      this.server = undefined;
    }
    
    if (this.childProcess) {
      this.childProcess.kill();
      this.childProcess = undefined;
    }
  }
}
