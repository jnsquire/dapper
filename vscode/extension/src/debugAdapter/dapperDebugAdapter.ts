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

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
import { PythonEnvironmentManager } from '../python/environment.js';

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

  async createDebugAdapterDescriptor(
    session: vscode.DebugSession,
    _executable: DebugAdapterExecutable | undefined
  ): Promise<DebugAdapterDescriptor> {
    if (!this.server) {
      try {
        const workspaceFolder = session.workspaceFolder || 
          (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders[0]);
        
        // Get the Python environment and launch configuration
        const extensionPath = path.dirname(__dirname);
        const dapperPath = path.join(extensionPath, '..', '..'); // Go up to dapper root
        const scriptPath = path.join(dapperPath, 'dapper', 'debug_launcher.py');
        
        // Get Python path from configuration or use default
        const config = session.configuration;
        const pythonPath = config.pythonPath || 'python';
        const command = pythonPath;
        const args = [scriptPath];
        
        // Pass through any debug configuration
        if (config.cwd) {
            args.push('--cwd', config.cwd);
        }
        if (config.module) {
            args.push('-m', config.module);
        } else if (config.program) {
            // Convert Windows paths to forward slashes for Python
            const programPath = config.program.replace(/\\/g, '/');
            args.push(programPath);
        }
        if (config.args) {
            args.push(...config.args);
        }
        
        // Start the debug adapter in a separate process
        const server = Net.createServer(socket => {
          const session = new DapperDebugSession();
          (session as any).setRunAsServer(true);
          (session as any).start(socket as NodeJS.ReadableStream, socket);
        }).listen(0);
        
        this.server = server;
        
        // Start the Python debug adapter process
        // Spawn the debug adapter process with the Python environment
        const env = {
            ...process.env,
            ...config.env,
            // Ensure Dapper is in the Python path
            PYTHONPATH: [
                dapperPath,
                process.env.PYTHONPATH
            ].filter(Boolean).join(path.delimiter)
        };

        this.childProcess = require('child_process').spawn(command, args, {
            cwd: config.cwd || process.cwd(),
            env,
            stdio: ['pipe', 'pipe', 'pipe'],
            shell: process.platform === 'win32' // Use shell on Windows for .bat/.cmd files
        });

        this.childProcess.stdout.on('data', (data: Buffer) => {
          console.log(`[DAP] ${data.toString().trim()}`);
        });
        
        this.childProcess.on('error', (err: Error) => {
          console.error('Failed to start debug adapter:', err);
          vscode.window.showErrorMessage(`Failed to start Dapper debug adapter: ${err.message}`);
        });
        
        this.childProcess.on('exit', (code: number) => {
          console.log(`Debug adapter process exited with code ${code}`);
          if (code !== 0) {
            vscode.window.showErrorMessage(`Dapper debug adapter process exited with code ${code}`);
          }
        });
        
      } catch (error) {
        console.error('Error creating debug adapter:', error);
        vscode.window.showErrorMessage(
          'Failed to initialize Python environment. Make sure the Python extension is installed and configured correctly.'
        );
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
