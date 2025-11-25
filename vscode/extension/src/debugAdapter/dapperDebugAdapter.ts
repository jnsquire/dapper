import * as vscode from 'vscode';
import { DebugAdapterDescriptor, DebugAdapterExecutable, DebugAdapterServer } from 'vscode';
import {
    LoggingDebugSession,
    InitializedEvent, TerminatedEvent, StoppedEvent, OutputEvent,
    Thread, StackFrame, Scope, Source, Handles, Breakpoint
} from '@vscode/debugadapter';
import type { DebugProtocol } from '@vscode/debugprotocol';
import * as Net from 'net';
import { fileURLToPath } from 'url';
import { dirname } from 'path';
import { EnvironmentManager, InstallMode } from '../environment/EnvironmentManager.js';

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
  private _pythonSocket?: Net.Socket; // Connection to Python debug_launcher for IPC
  private _buffer: Buffer = Buffer.alloc(0);
  private _nextRequestId = 1;
  private _pendingRequestsMap = new Map<number, (response: any) => void>();
  private _eventWaiters: Array<{
    event: string;
    filter: (data: any) => boolean;
    resolve: (data: any) => void;
  }> = [];

  public constructor(pythonSocket?: Net.Socket) {
    super();
    this._pythonSocket = pythonSocket;
    this.setDebuggerLinesStartAt1(false);
    this.setDebuggerColumnsStartAt1(false);
  }

  get configurationDone(): boolean {
    return this._configurationDone;
  }

  get isRunning(): boolean {
    return this._isRunning;
  }

  public setPythonSocket(socket: Net.Socket): void {
    this._pythonSocket = socket;
    
    // Set up listener for incoming events from Python
    socket.on('data', (data: Buffer) => {
      this.handlePythonMessage(data);
    });
  }

  private handlePythonMessage(data: Buffer): void {
    this._buffer = Buffer.concat([this._buffer, data]);

    while (true) {
      if (this._buffer.length < 8) {
        return; // Need more data for header
      }

      // Header: MAGIC(2) + VER(1) + KIND(1) + LEN(4)
      // MAGIC = "DP" (0x44 0x50)
      if (this._buffer[0] !== 0x44 || this._buffer[1] !== 0x50) {
        console.error('Invalid magic bytes in IPC stream');
        this._buffer = Buffer.alloc(0);
        return;
      }

      const length = this._buffer.readUInt32BE(4);
      if (this._buffer.length < 8 + length) {
        return; // Need more data for payload
      }

      const payload = this._buffer.subarray(8, 8 + length);
      this._buffer = this._buffer.subarray(8 + length);

      try {
        const message = JSON.parse(payload.toString('utf8'));
        this.processPythonMessage(message);
      } catch (e) {
        console.error('Failed to parse Python message', e);
      }
    }
  }

  private processPythonMessage(message: any) {
    // Handle responses to requests
    if (message.event === 'response' && message.id) {
      const resolve = this._pendingRequestsMap.get(message.id);
      if (resolve) {
        this._pendingRequestsMap.delete(message.id);
        resolve(message);
        return;
      }
    }

    // Handle event waiters
    const eventName = message.event;
    const waiterIndex = this._eventWaiters.findIndex(w => w.event === eventName && w.filter(message));
    if (waiterIndex !== -1) {
      const waiter = this._eventWaiters[waiterIndex];
      this._eventWaiters.splice(waiterIndex, 1);
      waiter.resolve(message);
      // Don't return here, as we might also want to emit the event generally
    }

    // Handle general events
    this.handleGeneralEvent(message);
  }

  private handleGeneralEvent(message: any) {
    if (message.event === 'stopped') {
      this.sendEvent(new StoppedEvent(message.reason, DapperDebugSession.THREAD_ID));
    } else if (message.event === 'output') {
      this.sendEvent(new OutputEvent(message.output, message.category));
    } else if (message.event === 'initialized') {
      this.sendEvent(new InitializedEvent());
    } else if (message.event === 'terminated') {
      this.sendEvent(new TerminatedEvent());
    }
  }

  private sendRequestToPython(command: string, args: any = {}): Promise<any> {
    return new Promise((resolve) => {
      const requestId = this._nextRequestId++;
      this._pendingRequestsMap.set(requestId, resolve);
      this.sendCommandToPython(command, args, requestId);
    });
  }

  private waitForEvent(event: string, filter: (data: any) => boolean = () => true): Promise<any> {
    return new Promise(resolve => {
      this._eventWaiters.push({ event, filter, resolve });
    });
  }

  private sendCommandToPython(command: string, args: any = {}, id?: number): void {
    if (!this._pythonSocket) {
      console.error('Cannot send command: Python socket not connected');
      return;
    }

    const payloadObj: any = { command, arguments: args };
    if (id !== undefined) {
      payloadObj.id = id;
    }
    
    const payload = Buffer.from(JSON.stringify(payloadObj), 'utf8');
    
    const header = Buffer.alloc(8);
    header.write('DP', 0); // MAGIC
    header.writeUInt8(1, 2); // VER
    header.writeUInt8(2, 3); // KIND (2 = Command)
    header.writeUInt32BE(payload.length, 4); // LEN

    this._pythonSocket.write(Buffer.concat([header, payload]));
  }

  protected async initializeRequest(
    response: DebugProtocol.InitializeResponse,
    args: DebugProtocol.InitializeRequestArguments
  ): Promise<void> {
    // Send initialize to Python and wait for response
    const result = await this.sendRequestToPython('initialize', args);
    
    response.body = response.body || {};
    if (result.success && result.body) {
      Object.assign(response.body, result.body);
    }
    
    // Ensure we set these if Python didn't
    response.body.supportsConfigurationDoneRequest = true;
    response.body.supportsSetVariable = true;
    response.body.supportsEvaluateForHovers = true;

    this.sendResponse(response);
    // Note: Python sends 'initialized' event separately, which handleGeneralEvent will forward
  }

  protected configurationDoneRequest(
    response: DebugProtocol.ConfigurationDoneResponse,
    args: DebugProtocol.ConfigurationDoneArguments,
    _request?: DebugProtocol.Request
  ): void {
    this._configurationDone = true;
    this.sendRequestToPython('configurationDone', args);
    this.sendResponse(response);
  }

  protected async launchRequest(
    response: DebugProtocol.LaunchResponse,
    args: LaunchRequestArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    this._isRunning = true;
    this.sendResponse(response);
  }

  protected async disconnectRequest(
    response: DebugProtocol.DisconnectResponse,
    args: DebugProtocol.DisconnectArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    this._isRunning = false;
    await this.sendRequestToPython('disconnect', args);
    this.sendResponse(response);
  }

  protected async setBreakPointsRequest(
    response: DebugProtocol.SetBreakpointsResponse,
    args: DebugProtocol.SetBreakpointsArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    const result = await this.sendRequestToPython('setBreakpoints', args);
    response.body = {
      breakpoints: (result.body && result.body.breakpoints) || []
    };
    this.sendResponse(response);
  }

  protected async threadsRequest(
    response: DebugProtocol.ThreadsResponse,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    const result = await this.sendRequestToPython('threads', {});
    response.body = {
      threads: (result.body && result.body.threads) || []
    };
    this.sendResponse(response);
  }

  protected async stackTraceRequest(
    response: DebugProtocol.StackTraceResponse,
    args: DebugProtocol.StackTraceArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    const result = await this.sendRequestToPython('stackTrace', args);
    response.body = {
      stackFrames: (result.body && result.body.stackFrames) || [],
      totalFrames: (result.body && result.body.totalFrames) || 0
    };
    this.sendResponse(response);
  }

  protected async scopesRequest(
    response: DebugProtocol.ScopesResponse,
    args: DebugProtocol.ScopesArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    const result = await this.sendRequestToPython('scopes', args);
    response.body = {
      scopes: (result.body && result.body.scopes) || []
    };
    this.sendResponse(response);
  }

  protected async variablesRequest(
    response: DebugProtocol.VariablesResponse,
    args: DebugProtocol.VariablesArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    // Send request
    this.sendCommandToPython('variables', args);
    
    // Wait for 'variables' event with matching reference
    const event = await this.waitForEvent('variables', (e) => e.variablesReference === args.variablesReference);
    
    response.body = {
      variables: event.variables || []
    };
    this.sendResponse(response);
  }
}

export class DapperDebugAdapterDescriptorFactory implements vscode.DebugAdapterDescriptorFactory, vscode.Disposable {
  private server?: Net.Server;
  private childProcess?: any; // Child process for the debug adapter
  private readonly envManager: EnvironmentManager;
  private readonly extensionVersion: string;
  private _pythonSocket?: Net.Socket; // Socket connection to Python debug_launcher
  private _currentSession?: DapperDebugSession; // Current debug session

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

        // Create a second server for Python to connect back with IPC
        const pythonIpcServer = Net.createServer(pythonSocket => {
          // This is the IPC connection from Python debug_launcher
          const outChannel = this.envManager.getOutputChannel();
          outChannel.appendLine('[INFO] Python debug adapter connected via IPC');

          // Store the python socket so DapperDebugSession can use it
          this._pythonSocket = pythonSocket;

          // If a session already exists, provide it the socket
          this._currentSession?.setPythonSocket(pythonSocket);

          pythonSocket.on('error', (err: Error) => {
            outChannel.appendLine(`[ERROR] Python IPC socket error: ${err.message}`);
          });
        }).listen(0);

        const pythonIpcPort = (pythonIpcServer.address() as Net.AddressInfo).port;

        // Pass the IPC port to Python so it can connect back
        args.push('--ipc', 'tcp');
        args.push('--ipc-port', pythonIpcPort.toString());
        args.push('--ipc-binary');

        // Create server for VS Code <-> DapperDebugSession Protocol
        const server = Net.createServer(vscodeSocket => {
          const sessionImpl = new DapperDebugSession(this._pythonSocket);
          this._currentSession = sessionImpl;
          sessionImpl.setRunAsServer(true);
          sessionImpl.start(vscodeSocket, vscodeSocket);
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
