import * as vscode from 'vscode';
import { DebugAdapterDescriptor, DebugAdapterExecutable, DebugAdapterServer } from 'vscode';
import {
    LoggingDebugSession,
    InitializedEvent, TerminatedEvent, StoppedEvent, OutputEvent,
    ContinuedEvent, ThreadEvent, BreakpointEvent, LoadedSourceEvent,
    ModuleEvent, ExitedEvent, Event,
} from '@vscode/debugadapter';
import type { DebugProtocol } from '@vscode/debugprotocol';
import { spawn } from 'child_process';
import * as Net from 'net';
import * as os from 'os';
import * as fs from 'fs';
import { fileURLToPath } from 'url';
import { delimiter as pathDelimiter, dirname, join as pathJoin } from 'path';
import { EnvironmentManager, InstallMode } from '../environment/EnvironmentManager.js';
import { logger } from '../utils/logger.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const CHILD_ATTACH_TRACE_PATH = pathJoin(os.tmpdir(), 'dapper-child-attach.log');
const ATTACH_BY_PID_DIAGNOSTIC_PREFIX = 'DAPPER_ATTACH_BY_PID_DIAGNOSTIC ';
const ATTACH_BY_PID_CONNECT_TIMEOUT_MS = 15_000;

function traceChildAttach(message: string, data?: unknown): void {
  try {
    const payload = data === undefined ? '' : ` ${JSON.stringify(data)}`;
    fs.appendFileSync(
      CHILD_ATTACH_TRACE_PATH,
      `${new Date().toISOString()} ${message}${payload}\n`,
      'utf8',
    );
  } catch {
    // Best-effort debug tracing only.
  }
}

// Define the debug configuration type that we expect
export interface LaunchRequestArguments extends DebugProtocol.LaunchRequestArguments {
  program?: string;
  module?: string;
  moduleSearchPaths?: string[];
  venvPath?: string;
  pythonPath?: string;
  subprocessAutoAttach?: boolean;
  args?: string[];
  stopOnEntry?: boolean;
  console?: 'internalConsole' | 'integratedTerminal' | 'externalTerminal';
  cwd?: string;
  env?: { [key: string]: string };
  /** Force reinstall of the dapper Python wheel before starting the session. */
  forceReinstall?: boolean;
}

interface AttachRequestArguments extends DebugProtocol.AttachRequestArguments {
  processId?: number | string;
  pythonPath?: string;
  venvPath?: string;
  cwd?: string;
  env?: { [key: string]: string };
  justMyCode?: boolean;
  strictExpressionWatchPolicy?: boolean;
  forceReinstall?: boolean;
}

interface InternalChildLaunchConfiguration extends vscode.DebugConfiguration {
  __dapperIsChildSession: true;
  __dapperChildSessionId: string;
  __dapperChildPid: number;
  __dapperChildName: string;
  __dapperParentDebugSessionId: string;
  __dapperChildIpcPort: number;
}

interface PendingChildSession {
  launcherSessionId: string;
  pid: number;
  name: string;
  ipcPort: number;
  parentDebugSessionId: string;
  parentSession: vscode.DebugSession;
  workspaceFolder?: vscode.WorkspaceFolder;
  cwd?: string;
  command?: string[];
  listener?: Net.Server;
  socket?: Net.Socket;
  adapterServer?: Net.Server;
  vscodeSessionId?: string;
  launchRequested?: boolean;
  terminated?: boolean;
}

interface AttachByPidDiagnostic {
  code: string;
  message: string;
  detail?: string;
  hint?: string;
}

class DapperAttachByPidError extends Error {
  public readonly userMessage: string;
  public readonly diagnostic?: AttachByPidDiagnostic;

  public constructor(userMessage: string, options?: { diagnostic?: AttachByPidDiagnostic; cause?: Error }) {
    super(userMessage);
    this.name = 'DapperAttachByPidError';
    this.userMessage = userMessage;
    this.diagnostic = options?.diagnostic;
    if (options?.cause) {
      this.cause = options.cause;
    }
  }
}

export class DapperDebugSession extends LoggingDebugSession {
  // We don't support multiple threads, so we can use a constant for the default thread ID
  private static readonly THREAD_ID = 1;
  private _configurationDone = false;
  private _isRunning = false;
  private _pythonSocket?: Net.Socket; // Connection to Python debug_launcher for IPC
  private _socketReady: Promise<Net.Socket>; // Resolves once Python connects
  private _resolveSocket!: (socket: Net.Socket) => void;
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
    this._socketReady = new Promise(resolve => { this._resolveSocket = resolve; });
    if (pythonSocket) {
      this.setPythonSocket(pythonSocket);
    }
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
    // Remove any existing listener to be idempotent
    if (this._pythonSocket) {
      this._pythonSocket.removeAllListeners('data');
      this._pythonSocket.removeAllListeners('close');
    }
    this._pythonSocket = socket;

    // Set up listener for incoming events from Python
    socket.on('data', (data: Buffer) => {
      this.handlePythonMessage(data);
    });

    socket.on('close', () => {
      logger.log('Python IPC socket closed');
      // If the socket closes while the session is still running,
      // ensure VS Code knows the debug session is done.
      if (this._isRunning) {
        this._isRunning = false;
        this.sendEvent(new ExitedEvent(0));
        this.sendEvent(new TerminatedEvent());
      }
    });

    // Unblock any sendRequestToPython calls that are awaiting the socket
    this._resolveSocket(socket);
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
        logger.error('Invalid magic bytes in IPC stream');
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
        logger.error('Failed to parse Python message', e);
      }
    }
  }

  private processPythonMessage(message: any) {
    const eventName = message.event;
    const msgJson = JSON.stringify(message);
    logger.debug(`Python → TS: ${msgJson.length > 500 ? msgJson.substring(0, 500) + '…' : msgJson}`);

    // Handle responses to requests
    if (eventName === 'response') {
      const msgId = message.id;
      if (msgId != null) {
        const resolve = this._pendingRequestsMap.get(msgId);
        if (resolve) {
          logger.debug(`Matched response id=${msgId} to pending request`);
          this._pendingRequestsMap.delete(msgId);
          resolve(message);
          return;
        }
        logger.warn(`Response id=${msgId} has no matching pending request (pending: ${[...this._pendingRequestsMap.keys()]})`);
      } else if (this._pendingRequestsMap.size > 0) {
        // Fallback: Python response arrived without an id.  Match it to the
        // oldest pending request (FIFO) so the caller isn't left hanging.
        const firstKey = this._pendingRequestsMap.keys().next().value!;
        const resolve = this._pendingRequestsMap.get(firstKey)!;
        this._pendingRequestsMap.delete(firstKey);
        logger.warn(`Response has no id — FIFO-matched to pending request ${firstKey}`);
        resolve(message);
        return;
      } else {
        logger.warn(`Response with no id and no pending requests. Keys: ${Object.keys(message).join(', ')}`);
      }
    }

    // Handle event waiters
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
    const body = message.body ?? {};
    if (message.event === 'stopped') {
      this.sendEvent(new StoppedEvent(body.reason, body.threadId ?? DapperDebugSession.THREAD_ID, body.text));
    } else if (message.event === 'continued') {
      this.sendEvent(new ContinuedEvent(body.threadId ?? DapperDebugSession.THREAD_ID, body.allThreadsContinued ?? true));
    } else if (message.event === 'output') {
      this.sendEvent(new OutputEvent(body.output, body.category));
    } else if (message.event === 'initialized') {
      this.sendEvent(new InitializedEvent());
    } else if (message.event === 'terminated') {
      this.sendEvent(new TerminatedEvent());
    } else if (message.event === 'exited') {
      this.sendEvent(new ExitedEvent(body.exitCode ?? 0));
    } else if (message.event === 'thread') {
      this.sendEvent(new ThreadEvent(body.reason, body.threadId));
    } else if (message.event === 'breakpoint') {
      this.sendEvent(new BreakpointEvent(body.reason, body.breakpoint));
    } else if (message.event === 'loadedSource') {
      this.sendEvent(new LoadedSourceEvent(body.reason, body.source));
    } else if (message.event === 'module') {
      this.sendEvent(new ModuleEvent(body.reason, body.module));
    } else if (message.event === 'process') {
      this.sendEvent(new Event('process', body));
    } else if (
      message.event === 'dapper/childProcess'
      || message.event === 'dapper/childProcessExited'
      || message.event === 'dapper/childProcessCandidate'
    ) {
      this.sendEvent(new Event(message.event, body));
    } else if (message.event === 'dapper/hotReloadResult') {
      this.sendEvent(new Event('dapper/hotReloadResult', body));
    } else if (message.event === 'dapper/log') {
      // Forward structured log messages to the output channel
      this.sendEvent(new OutputEvent(
        body.message || '',
        body.category || 'console'
      ));
    } else if (message.event === 'dapper/telemetry') {
      // Forward telemetry snapshot as a custom event
      this.sendEvent(new Event('dapper/telemetry', body));
    }
  }

  private formatPythonError(result: any): string {
    if (!result) return 'Unknown error';

    let message = result.message || 'Unknown error';

    // Extract structured error details from Python's error hierarchy
    const details = result.body?.details || result.body?.error;
    if (details) {
      if (details.error_code) {
        message = `[${details.error_code}] ${message}`;
      }
      if (details.cause) {
        message += ` (caused by: ${details.cause})`;
      }
    }

    return message;
  }

  private async sendRequestToPython(command: string, args: any = {}, timeoutMs: number = 30000): Promise<any> {
    await this._socketReady;
    return new Promise((resolve, reject) => {
      const requestId = this._nextRequestId++;
      logger.debug(`TS → Python: ${command} (requestId=${requestId})`);
      const timer = setTimeout(() => {
        if (this._pendingRequestsMap.delete(requestId)) {
          const msg = `[Dapper] Request ${command} (id=${requestId}) timed out after ${timeoutMs}ms`;
          logger.error(msg);
          reject(new Error(msg));
        }
      }, timeoutMs);
      this._pendingRequestsMap.set(requestId, (result) => {
        clearTimeout(timer);
        resolve(result);
      });
      this.sendCommandToPython(command, args, requestId);
    });
  }

  private waitForEvent(event: string, filter: (data: any) => boolean = () => true): Promise<any> {
    return new Promise(resolve => {
      this._eventWaiters.push({ event, filter, resolve });
    });
  }

  private sendCommandToPython(command: string, args: any = {}, id?: number): void {
    // Caller must have awaited _socketReady, so the socket is guaranteed to be set
    const socket = this._pythonSocket!;

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

    socket.write(Buffer.concat([header, payload]));
  }

  protected async initializeRequest(
    response: DebugProtocol.InitializeResponse,
    args: DebugProtocol.InitializeRequestArguments
  ): Promise<void> {
    logger.log('initializeRequest: sending to Python');
    // Send initialize to Python and wait for response
    let result: any;
    try {
      result = await this.sendRequestToPython('initialize', args);
      logger.debug(`initializeRequest: got response: ${JSON.stringify(result).substring(0, 200)}`);
    } catch (e) {
      logger.error('initializeRequest failed', e);
      result = { success: true, body: {} };
    }
    
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
    logger.log('configurationDoneRequest: forwarding to Python');
    this._configurationDone = true;
    this.sendRequestToPython('configurationDone', args);
    this.sendResponse(response);
  }

  protected async launchRequest(
    response: DebugProtocol.LaunchResponse,
    args: LaunchRequestArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    logger.log('launchRequest: forwarding to Python');
    const result = await this.sendRequestToPython('launch', args);
    logger.log(`launchRequest: response success=${result?.success}`);
    if (result && result.success === false) {
      response.success = false;
      response.message = this.formatPythonError(result);
    } else {
      this._isRunning = true;
    }
    this.sendResponse(response);
  }

  protected async disconnectRequest(
    response: DebugProtocol.DisconnectResponse,
    args: DebugProtocol.DisconnectArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    this._isRunning = false;
    try {
      await this.sendRequestToPython('disconnect', args);
    } catch {
      // Socket may already be closed; ignore
    }
    this.sendResponse(response);
  }

  protected async setBreakPointsRequest(
    response: DebugProtocol.SetBreakpointsResponse,
    args: DebugProtocol.SetBreakpointsArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    logger.debug(`setBreakpoints: source=${args.source?.path ?? '<unknown>'} lines=${(args.breakpoints || []).map(b => b.line).join(',')}`);
    const result = await this.sendRequestToPython('setBreakpoints', args);
    logger.debug(`setBreakpoints: response breakpoints=${JSON.stringify(result?.body?.breakpoints?.map((b: any) => ({line: b.line, verified: b.verified})))}`);
    response.body = {
      breakpoints: (result.body && result.body.breakpoints) || []
    };
    this.sendResponse(response);
  }

  protected async threadsRequest(
    response: DebugProtocol.ThreadsResponse,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    try {
      const result = await this.sendRequestToPython('threads', {});
      response.body = {
        threads: (result.body && result.body.threads) || []
      };
    } catch {
      // Socket closed or timeout — return a single synthetic thread
      response.body = { threads: [{ id: DapperDebugSession.THREAD_ID, name: 'MainThread' }] };
    }
    this.sendResponse(response);
  }

  protected async stackTraceRequest(
    response: DebugProtocol.StackTraceResponse,
    args: DebugProtocol.StackTraceArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    try {
      const result = await this.sendRequestToPython('stackTrace', args);
      response.body = {
        stackFrames: (result.body && result.body.stackFrames) || [],
        totalFrames: (result.body && result.body.totalFrames) || 0
      };
    } catch {
      response.body = { stackFrames: [], totalFrames: 0 };
    }
    this.sendResponse(response);
  }

  protected async scopesRequest(
    response: DebugProtocol.ScopesResponse,
    args: DebugProtocol.ScopesArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    try {
      const result = await this.sendRequestToPython('scopes', args);
      response.body = {
        scopes: (result.body && result.body.scopes) || []
      };
    } catch {
      response.body = { scopes: [] };
    }
    this.sendResponse(response);
  }

  protected async variablesRequest(
    response: DebugProtocol.VariablesResponse,
    args: DebugProtocol.VariablesArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    try {
      const result = await this.sendRequestToPython('variables', args);
      response.body = {
        variables: (result.body && result.body.variables) || []
      };
    } catch {
      response.body = { variables: [] };
    }
    this.sendResponse(response);
  }

  protected async attachRequest(
    response: DebugProtocol.AttachResponse,
    args: DebugProtocol.AttachRequestArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    const result = await this.sendRequestToPython('attach', args);
    if (result && result.success === false) {
      response.success = false;
      response.message = this.formatPythonError(result);
    }
    this.sendResponse(response);
  }

  protected async setFunctionBreakPointsRequest(
    response: DebugProtocol.SetFunctionBreakpointsResponse,
    args: DebugProtocol.SetFunctionBreakpointsArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    const result = await this.sendRequestToPython('setFunctionBreakpoints', args);
    response.body = {
      breakpoints: (result.body && result.body.breakpoints) || []
    };
    this.sendResponse(response);
  }

  protected async setExceptionBreakPointsRequest(
    response: DebugProtocol.SetExceptionBreakpointsResponse,
    args: DebugProtocol.SetExceptionBreakpointsArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    await this.sendRequestToPython('setExceptionBreakpoints', args);
    this.sendResponse(response);
  }

  protected async continueRequest(
    response: DebugProtocol.ContinueResponse,
    args: DebugProtocol.ContinueArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    const result = await this.sendRequestToPython('continue', args);
    response.body = {
      allThreadsContinued: result.body?.allThreadsContinued ?? true
    };
    this.sendResponse(response);
  }

  protected async nextRequest(
    response: DebugProtocol.NextResponse,
    args: DebugProtocol.NextArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    await this.sendRequestToPython('next', args);
    this.sendResponse(response);
  }

  protected async stepInRequest(
    response: DebugProtocol.StepInResponse,
    args: DebugProtocol.StepInArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    await this.sendRequestToPython('stepIn', args);
    this.sendResponse(response);
  }

  protected async stepOutRequest(
    response: DebugProtocol.StepOutResponse,
    args: DebugProtocol.StepOutArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    await this.sendRequestToPython('stepOut', args);
    this.sendResponse(response);
  }

  protected async stepInTargetsRequest(
    response: DebugProtocol.StepInTargetsResponse,
    args: DebugProtocol.StepInTargetsArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    const result = await this.sendRequestToPython('stepInTargets', args);
    response.body = {
      targets: (result.body && result.body.targets) || []
    };
    this.sendResponse(response);
  }

  protected async pauseRequest(
    response: DebugProtocol.PauseResponse,
    args: DebugProtocol.PauseArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    const result = await this.sendRequestToPython('pause', args);
    if (result && result.success === false) {
      response.success = false;
      response.message = this.formatPythonError(result);
    }
    this.sendResponse(response);
  }

  protected async terminateRequest(
    response: DebugProtocol.TerminateResponse,
    args: DebugProtocol.TerminateArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    await this.sendRequestToPython('terminate', args);
    this.sendResponse(response);
  }

  protected async loadedSourcesRequest(
    response: DebugProtocol.LoadedSourcesResponse,
    args: DebugProtocol.LoadedSourcesArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    const result = await this.sendRequestToPython('loadedSources', args);
    response.body = {
      sources: (result.body && result.body.sources) || []
    };
    this.sendResponse(response);
  }

  protected async breakpointLocationsRequest(
    response: DebugProtocol.BreakpointLocationsResponse,
    args: DebugProtocol.BreakpointLocationsArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    const result = await this.sendRequestToPython('breakpointLocations', args);
    response.body = {
      breakpoints: (result.body && result.body.breakpoints) || []
    };
    this.sendResponse(response);
  }

  protected async sourceRequest(
    response: DebugProtocol.SourceResponse,
    args: DebugProtocol.SourceArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    const result = await this.sendRequestToPython('source', args);
    if (result && result.success === false) {
      response.success = false;
      response.message = this.formatPythonError(result);
    } else {
      response.body = {
        content: result.body?.content ?? '',
        mimeType: result.body?.mimeType
      };
    }
    this.sendResponse(response);
  }

  protected async modulesRequest(
    response: DebugProtocol.ModulesResponse,
    args: DebugProtocol.ModulesArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    const result = await this.sendRequestToPython('modules', args);
    response.body = {
      modules: (result.body && result.body.modules) || [],
      totalModules: result.body?.totalModules
    };
    this.sendResponse(response);
  }

  protected async setVariableRequest(
    response: DebugProtocol.SetVariableResponse,
    args: DebugProtocol.SetVariableArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    const result = await this.sendRequestToPython('setVariable', args);
    if (result && result.success === false) {
      response.success = false;
      response.message = this.formatPythonError(result);
    } else {
      response.body = result.body ?? {};
    }
    this.sendResponse(response);
  }

  protected async setExpressionRequest(
    response: DebugProtocol.SetExpressionResponse,
    args: DebugProtocol.SetExpressionArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    const result = await this.sendRequestToPython('setExpression', args);
    if (result && result.success === false) {
      response.success = false;
      response.message = this.formatPythonError(result);
    } else {
      response.body = {
        value: result.body?.value ?? '',
        type: result.body?.type,
      };
    }
    this.sendResponse(response);
  }

  protected async evaluateRequest(
    response: DebugProtocol.EvaluateResponse,
    args: DebugProtocol.EvaluateArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    const result = await this.sendRequestToPython('evaluate', args);
    if (result && result.success === false) {
      response.success = false;
      response.message = this.formatPythonError(result);
    } else {
      response.body = result.body ?? { result: '', variablesReference: 0 };
    }
    this.sendResponse(response);
  }

  protected async dataBreakpointInfoRequest(
    response: DebugProtocol.DataBreakpointInfoResponse,
    args: DebugProtocol.DataBreakpointInfoArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    const result = await this.sendRequestToPython('dataBreakpointInfo', args);
    response.body = result.body ?? { dataId: null, description: 'Unavailable' };
    this.sendResponse(response);
  }

  protected async setDataBreakpointsRequest(
    response: DebugProtocol.SetDataBreakpointsResponse,
    args: DebugProtocol.SetDataBreakpointsArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    const result = await this.sendRequestToPython('setDataBreakpoints', args);
    response.body = {
      breakpoints: (result.body && result.body.breakpoints) || []
    };
    this.sendResponse(response);
  }

  protected async exceptionInfoRequest(
    response: DebugProtocol.ExceptionInfoResponse,
    args: DebugProtocol.ExceptionInfoArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    const result = await this.sendRequestToPython('exceptionInfo', args);
    if (result && result.success === false) {
      response.success = false;
      response.message = this.formatPythonError(result);
    } else {
      response.body = result.body ?? { exceptionId: '', breakMode: 'never' };
    }
    this.sendResponse(response);
  }

  protected async completionsRequest(
    response: DebugProtocol.CompletionsResponse,
    args: DebugProtocol.CompletionsArguments,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    const result = await this.sendRequestToPython('completions', args);
    response.body = {
      targets: (result.body && result.body.targets) || []
    };
    this.sendResponse(response);
  }

  protected async customRequest(
    command: string,
    response: DebugProtocol.Response,
    args: any,
    _request?: DebugProtocol.Request
  ): Promise<void> {
    // Forward all dapper/* custom requests to Python
    if (command.startsWith('dapper/')) {
      try {
        const result = await this.sendRequestToPython(command, args || {});
        if (result && result.success === false) {
          response.success = false;
          response.message = this.formatPythonError(result);
        } else {
          response.body = result?.body || {};
        }
      } catch (e) {
        response.success = false;
        response.message = e instanceof Error ? e.message : String(e);
      }
    } else {
      response.success = false;
      response.message = `Unrecognized custom request: ${command}`;
    }
    this.sendResponse(response);
  }
}

export class DapperDebugAdapterDescriptorFactory implements vscode.DebugAdapterDescriptorFactory, vscode.Disposable {
  private server?: Net.Server;
  private _adapterTerminal?: vscode.Terminal; // Integrated terminal hosting the adapter (provides PTY)
  private readonly envManager: EnvironmentManager;
  private readonly extensionVersion: string;
  private _pythonSocket?: Net.Socket; // Socket connection to Python debug_launcher
  private _currentSession?: DapperDebugSession; // Current debug session
  private _pythonIpcServer?: Net.Server;
  private _pythonSocketReady?: Promise<Net.Socket>;
  private _resolvePythonSocketReady?: (socket: Net.Socket) => void;
  private _rejectPythonSocketReady?: (error: Error) => void;
  private readonly _childSessions = new Map<string, PendingChildSession>();
  private readonly _childSessionIdsByPid = new Map<number, string>();
  private readonly _disposables: vscode.Disposable[] = [];

  constructor(private readonly context: vscode.ExtensionContext) {
    this.envManager = new EnvironmentManager(context, logger.getChannel());
    this.extensionVersion = context.extension.packageJSON.version || '0.0.0';
    this._disposables.push(
      vscode.debug.onDidReceiveDebugSessionCustomEvent((event) => {
        void this._handleDebugSessionCustomEvent(event);
      }),
      vscode.debug.onDidTerminateDebugSession((session) => {
        this._handleDebugSessionTerminated(session);
      }),
    );
  }

  private _isInternalChildLaunchConfig(
    config: vscode.DebugConfiguration,
  ): config is InternalChildLaunchConfiguration {
    const candidate = config as Partial<InternalChildLaunchConfiguration>;
    return candidate.__dapperIsChildSession === true
      && typeof candidate.__dapperChildSessionId === 'string';
  }

  private async _handleDebugSessionCustomEvent(
    event: vscode.DebugSessionCustomEvent,
  ): Promise<void> {
    if (event.session.type !== 'dapper') {
      return;
    }

    traceChildAttach('custom-event', {
      sessionId: event.session.id,
      event: event.event,
      body: event.body,
    });

    try {
      if (event.event === 'dapper/childProcess') {
        await this._handleChildProcessEvent(event.session, event.body ?? {});
      } else if (event.event === 'dapper/childProcessExited') {
        this._handleChildProcessExitedEvent(event.body ?? {});
      } else if (event.event === 'dapper/childProcessCandidate') {
        this._handleChildProcessCandidateEvent(event.session, event.body ?? {});
      }
    } catch (error) {
      this.envManager.getOutputChannel().error(
        `Child session event handling failed: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  }

  private async _handleChildProcessEvent(
    parentSession: vscode.DebugSession,
    body: Record<string, unknown>,
  ): Promise<void> {
    const launcherSessionId = typeof body.sessionId === 'string' ? body.sessionId : undefined;
    const pid = typeof body.pid === 'number' ? body.pid : undefined;
    const ipcPort = typeof body.ipcPort === 'number' ? body.ipcPort : undefined;
    const name = typeof body.name === 'string' && body.name.length > 0 ? body.name : 'child';
    const cwd = typeof body.cwd === 'string' ? body.cwd : undefined;
    const command = Array.isArray(body.command)
      ? body.command.filter((value): value is string => typeof value === 'string')
      : undefined;
    const outChannel = this.envManager.getOutputChannel();

    if (!launcherSessionId || pid == null || ipcPort == null) {
      traceChildAttach('child-event-malformed', body);
      outChannel.warn(`Ignoring malformed dapper/childProcess event: ${JSON.stringify(body)}`);
      return;
    }

    if (this._childSessions.has(launcherSessionId)) {
      traceChildAttach('child-event-duplicate', { launcherSessionId, pid, ipcPort });
      outChannel.info(`Child session ${launcherSessionId} is already being tracked`);
      return;
    }

    traceChildAttach('child-event-accepted', {
      launcherSessionId,
      pid,
      ipcPort,
      parentDebugSessionId: parentSession.id,
      cwd,
      command,
    });

    const pending: PendingChildSession = {
      launcherSessionId,
      pid,
      name,
      ipcPort,
      parentDebugSessionId: parentSession.id,
      parentSession,
      workspaceFolder: parentSession.workspaceFolder,
      cwd,
      command,
    };
    this._childSessions.set(launcherSessionId, pending);
    this._childSessionIdsByPid.set(pid, launcherSessionId);

    const listener = Net.createServer((socket) => {
      const current = this._childSessions.get(launcherSessionId);
      if (!current || current.terminated) {
        traceChildAttach('child-socket-rejected', { launcherSessionId, reason: 'terminated-or-missing' });
        socket.destroy();
        return;
      }

      if (current.socket) {
        traceChildAttach('child-socket-rejected', { launcherSessionId, reason: 'duplicate-connection' });
        outChannel.warn(`Child session ${launcherSessionId} received an unexpected extra IPC connection`);
        socket.destroy();
        return;
      }

      current.socket = socket;
      if (current.listener) {
        current.listener.close();
        current.listener = undefined;
      }

      outChannel.info(`Child process ${current.pid} connected on 127.0.0.1:${current.ipcPort}`);
      traceChildAttach('child-socket-connected', {
        launcherSessionId,
        pid: current.pid,
        ipcPort: current.ipcPort,
      });
      void this._startChildDebugSession(current).catch((error) => {
        traceChildAttach('child-launch-failed', {
          launcherSessionId,
          error: error instanceof Error ? error.message : String(error),
        });
        outChannel.error(
          `Failed to start child debug session for ${launcherSessionId}: ${error instanceof Error ? error.message : String(error)}`,
        );
        this._disposePendingChildSession(launcherSessionId, { destroySocket: true });
      });
    });

    await new Promise<void>((resolve, reject) => {
      const onError = (error: Error) => {
        listener.off('listening', onListening);
        reject(error);
      };
      const onListening = () => {
        listener.off('error', onError);
        resolve();
      };

      listener.once('error', onError);
      listener.once('listening', onListening);
      listener.listen(ipcPort, '127.0.0.1');
    }).catch((error) => {
      traceChildAttach('child-listener-listen-failed', {
        launcherSessionId,
        error: error instanceof Error ? error.message : String(error),
      });
      this._disposePendingChildSession(launcherSessionId, { destroySocket: true });
      throw error;
    });

    listener.on('error', (error) => {
      traceChildAttach('child-listener-runtime-error', {
        launcherSessionId,
        error: error instanceof Error ? error.message : String(error),
      });
      outChannel.error(
        `Child IPC listener failed for ${launcherSessionId}: ${error instanceof Error ? error.message : String(error)}`,
      );
      this._disposePendingChildSession(launcherSessionId, { destroySocket: true });
    });

    pending.listener = listener;
    traceChildAttach('child-listener-ready', { launcherSessionId, pid, ipcPort });
    outChannel.info(`Listening for child process ${pid} on 127.0.0.1:${ipcPort}`);
  }

  private async _startChildDebugSession(pending: PendingChildSession): Promise<void> {
    if (pending.launchRequested || pending.terminated || !pending.socket) {
      traceChildAttach('child-launch-skipped', {
        launcherSessionId: pending.launcherSessionId,
        launchRequested: pending.launchRequested,
        terminated: pending.terminated,
        hasSocket: Boolean(pending.socket),
      });
      return;
    }

    pending.launchRequested = true;
    traceChildAttach('child-launch-start', {
      launcherSessionId: pending.launcherSessionId,
      pid: pending.pid,
      parentDebugSessionId: pending.parentDebugSessionId,
    });

    const config: InternalChildLaunchConfiguration = {
      type: 'dapper',
      request: 'launch',
      name: `Dapper Child: ${pending.name} (${pending.pid})`,
      program: pending.command?.[0] || pending.name,
      cwd: pending.cwd,
      __dapperIsChildSession: true,
      __dapperChildSessionId: pending.launcherSessionId,
      __dapperChildPid: pending.pid,
      __dapperChildName: pending.name,
      __dapperParentDebugSessionId: pending.parentDebugSessionId,
      __dapperChildIpcPort: pending.ipcPort,
    };

    const started = pending.parentSession
      ? await vscode.debug.startDebugging(pending.workspaceFolder, config, {
          parentSession: pending.parentSession,
          compact: false,
          lifecycleManagedByParent: false,
          consoleMode: vscode.DebugConsoleMode.MergeWithParent,
        })
      : await vscode.debug.startDebugging(pending.workspaceFolder, config);

    if (!started) {
      traceChildAttach('child-launch-declined', {
        launcherSessionId: pending.launcherSessionId,
        pid: pending.pid,
      });
      this.envManager.getOutputChannel().error(
        `VS Code declined to start child debug session for pid=${pending.pid}`,
      );
      this._disposePendingChildSession(pending.launcherSessionId, { destroySocket: true });
    } else {
      traceChildAttach('child-launch-requested', {
        launcherSessionId: pending.launcherSessionId,
        pid: pending.pid,
      });
    }
  }

  private _handleChildProcessExitedEvent(body: Record<string, unknown>): void {
    const pid = typeof body.pid === 'number' ? body.pid : undefined;
    const sessionId = typeof body.sessionId === 'string' ? body.sessionId : undefined;
    const launcherSessionId = sessionId ?? (pid == null ? undefined : this._childSessionIdsByPid.get(pid));
    if (!launcherSessionId) {
      return;
    }

    const pending = this._childSessions.get(launcherSessionId);
    if (!pending) {
      if (pid != null) {
        this._childSessionIdsByPid.delete(pid);
      }
      return;
    }

    pending.terminated = true;
    traceChildAttach('child-exited-event', { launcherSessionId, pid: pid ?? pending.pid });
    if (!pending.vscodeSessionId) {
      this._disposePendingChildSession(launcherSessionId, { destroySocket: true });
    }
  }

  private _handleChildProcessCandidateEvent(
    parentSession: vscode.DebugSession,
    body: Record<string, unknown>,
  ): void {
    const source = typeof body.source === 'string' ? body.source : 'unknown';
    const target = typeof body.target === 'string' ? body.target : '<unknown>';
    this.envManager.getOutputChannel().info(
      `Child-process candidate detected for session ${parentSession.id}: ${source} -> ${target}`,
    );
  }

  private _handleDebugSessionTerminated(session: vscode.DebugSession): void {
    if (session.type !== 'dapper') {
      return;
    }

    if (this._isInternalChildLaunchConfig(session.configuration)) {
      this._disposePendingChildSession(session.configuration.__dapperChildSessionId, { destroySocket: true });
      return;
    }

    const childIds = [...this._childSessions.values()]
      .filter((pending) => pending.parentDebugSessionId === session.id)
      .map((pending) => pending.launcherSessionId);
    for (const launcherSessionId of childIds) {
      this._disposePendingChildSession(launcherSessionId, { destroySocket: true });
    }

    this._resetMainSessionState();
  }

  private _resetMainSessionState(): void {
    if (this.server) {
      this.server.close();
      this.server = undefined;
    }
    if (this._pythonIpcServer) {
      this._pythonIpcServer.close();
      this._pythonIpcServer = undefined;
    }
    if (this._adapterTerminal) {
      this._adapterTerminal.dispose();
      this._adapterTerminal = undefined;
    }
    if (this._pythonSocket && !this._pythonSocket.destroyed) {
      this._pythonSocket.destroy();
    }
    this._pythonSocket = undefined;
    this._pythonSocketReady = undefined;
    this._resolvePythonSocketReady = undefined;
    this._rejectPythonSocketReady = undefined;
    this._currentSession = undefined;
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
        this.envManager.getOutputChannel().warn(
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
    const socketReady = this._pythonSocketReady;
    if (!socketReady) {
      throw new DapperAttachByPidError(`Attach by PID failed for process ${processId} before the IPC listener was ready.`);
    }

    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => {
        reject(new DapperAttachByPidError(
          [
            `Timed out waiting for process ${processId} to execute the injected attach bootstrap.`,
            'The target must be a live CPython 3.14 process with remote debugging enabled.',
            'Long-running native work or a blocked main thread can delay sys.remote_exec() reaching a safe evaluation point.',
          ].join(' '),
        ));
      }, ATTACH_BY_PID_CONNECT_TIMEOUT_MS);

      socketReady.then(() => {
        clearTimeout(timer);
        outChannel.info(`Attached process ${processId} connected back over IPC`);
        resolve();
      }, (error) => {
        clearTimeout(timer);
        reject(error);
      });
    });
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
    this._pythonSocketReady = new Promise<Net.Socket>((resolve, reject) => {
      this._resolvePythonSocketReady = resolve;
      this._rejectPythonSocketReady = reject;
    });

    const pythonIpcServer = Net.createServer((pythonSocket) => {
      this._pythonIpcServer = pythonIpcServer;
      outChannel.info('Python debug adapter connected via IPC');
      this._pythonSocket = pythonSocket;
      this._resolvePythonSocketReady?.(pythonSocket);
      this._currentSession?.setPythonSocket(pythonSocket);
      outChannel.info(`Python IPC: session already exists = ${!!this._currentSession}`);

      pythonSocket.on('error', (err: Error) => {
        outChannel.error(`Python IPC socket error: ${err.message}`);
      });
    }).listen(0);

    pythonIpcServer.on('error', (err: Error) => {
      this._rejectPythonSocketReady?.(err);
    });

    this._pythonIpcServer = pythonIpcServer;
    return (pythonIpcServer.address() as Net.AddressInfo).port;
  }

  private _createAdapterServer(outChannel: vscode.LogOutputChannel): void {
    const server = Net.createServer((vscodeSocket) => {
      outChannel.info(`VS Code connected to DAP server (pythonSocket ready = ${!!this._pythonSocket})`);
      const sessionImpl = new DapperDebugSession(this._pythonSocket);
      this._currentSession = sessionImpl;
      sessionImpl.setRunAsServer(true);
      sessionImpl.start(vscodeSocket, vscodeSocket);
    }).listen(0);
    this.server = server;
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
      logFile = pathJoin(os.tmpdir(), `dapper-debug-${session.id}.log`);
    }

    const debugLogLevel = (debuggerConfig
      .get<string>('logLevel', 'DEBUG') || 'DEBUG')
      .toUpperCase();
    const rawEnv = {
      ...process.env,
      ...(config.env || {}),
      DAPPER_MANAGED_VENV: envInfo.venvPath || '',
      DAPPER_VERSION_EXPECTED: this.extensionVersion,
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

  private _disposePendingChildSession(
    launcherSessionId: string,
    options: { destroySocket: boolean },
  ): void {
    const pending = this._childSessions.get(launcherSessionId);
    if (!pending) {
      return;
    }

    pending.terminated = true;
    if (pending.listener) {
      pending.listener.close();
      pending.listener = undefined;
    }
    if (pending.adapterServer) {
      pending.adapterServer.close();
      pending.adapterServer = undefined;
    }
    if (options.destroySocket && pending.socket && !pending.socket.destroyed) {
      pending.socket.destroy();
    }

    this._childSessions.delete(launcherSessionId);
    this._childSessionIdsByPid.delete(pending.pid);
  }

  private async _createChildDebugAdapterDescriptor(
    session: vscode.DebugSession,
    config: InternalChildLaunchConfiguration,
  ): Promise<DebugAdapterDescriptor> {
    const pending = this._childSessions.get(config.__dapperChildSessionId);
    if (!pending || !pending.socket) {
      traceChildAttach('child-descriptor-missing-socket', {
        launcherSessionId: config.__dapperChildSessionId,
      });
      throw new Error(`Child debug session ${config.__dapperChildSessionId} has no pending IPC socket`);
    }

    pending.vscodeSessionId = session.id;
    traceChildAttach('child-descriptor-start', {
      launcherSessionId: config.__dapperChildSessionId,
      vscodeSessionId: session.id,
    });

    const adapterServer = Net.createServer((vscodeSocket) => {
      adapterServer.close();
      pending.adapterServer = undefined;
      const sessionImpl = new DapperDebugSession(pending.socket);
      sessionImpl.setRunAsServer(true);
      sessionImpl.start(vscodeSocket, vscodeSocket);
    });

    const port = await new Promise<number>((resolve, reject) => {
      const onError = (error: Error) => {
        adapterServer.off('listening', onListening);
        reject(error);
      };
      const onListening = () => {
        adapterServer.off('error', onError);
        resolve((adapterServer.address() as Net.AddressInfo).port);
      };

      adapterServer.once('error', onError);
      adapterServer.once('listening', onListening);
      adapterServer.listen(0, '127.0.0.1');
    });

    adapterServer.on('error', (error) => {
      this.envManager.getOutputChannel().error(
        `Child debug adapter server failed for ${config.__dapperChildSessionId}: ${error instanceof Error ? error.message : String(error)}`,
      );
      this._disposePendingChildSession(config.__dapperChildSessionId, { destroySocket: true });
    });

    pending.adapterServer = adapterServer;
    traceChildAttach('child-descriptor-ready', {
      launcherSessionId: config.__dapperChildSessionId,
      vscodeSessionId: session.id,
      port,
    });
    return new DebugAdapterServer(port, '127.0.0.1');
  }

  async createDebugAdapterDescriptor(
    session: vscode.DebugSession,
    _executable: DebugAdapterExecutable | undefined
  ): Promise<DebugAdapterDescriptor> {
    if (this._isInternalChildLaunchConfig(session.configuration)) {
      return this._createChildDebugAdapterDescriptor(session, session.configuration);
    }

    if (!this.server) {
      try {
        const config = session.configuration;
        const attachConfig = config as AttachRequestArguments;
        const installMode = (vscode.workspace.getConfiguration('dapper.python').get<string>('installMode') || 'auto') as InstallMode;
        const forceReinstall = !!vscode.workspace.getConfiguration('dapper.python').get<boolean>('forceReinstall')
          || !!(config.forceReinstall as boolean | undefined);
        const outChannel = this.envManager.getOutputChannel();

        // Prepare environment (create venv & install dapper if needed)
        const envInfo = await this.envManager.prepareEnvironment(this.extensionVersion, installMode, forceReinstall, {
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
        const processId = this._resolveProcessId(config);

        const pythonIpcPort = this._createPythonIpcServer(outChannel);
        this._createAdapterServer(outChannel);

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
        } else {
          // Build arguments: use dapper.launcher as the entry point
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
          adapterTerminal.show(false);

          const closeDisposable = vscode.window.onDidCloseTerminal(t => {
            if (t !== adapterTerminal) return;
            closeDisposable.dispose();
            const code = t.exitStatus?.code ?? 0;
            outChannel.info(`Debug adapter exited with code ${code}`);
            if (code !== 0 && code !== undefined) {
              outChannel.error(`Debug adapter exited with non-zero code ${code}. Check the terminal output above.`);
              this.envManager.showOutputChannel();
              vscode.window.showErrorMessage(`Dapper debug adapter exited with code ${code}.`);
            }
            if (this._currentSession) {
              outChannel.info('Sending ExitedEvent + TerminatedEvent from terminal close handler');
              this._currentSession.sendEvent(new ExitedEvent(code));
              this._currentSession.sendEvent(new TerminatedEvent());
            } else {
              outChannel.warn('Terminal closed but no active debug session to notify');
            }
            outChannel.info('Resetting adapter factory state after terminal exit');
            this._resetMainSessionState();
          });
        }
      } catch (error) {
        const outChannel = this.envManager.getOutputChannel();
        this._resetMainSessionState();
        const message = error instanceof Error ? error.message : String(error);
        outChannel.error(`createDebugAdapterDescriptor failed: ${error instanceof Error ? error : message}`);
        this.envManager.showOutputChannel();
        logger.error('Error creating debug adapter', error);
        const userMessage = error instanceof DapperAttachByPidError
          ? `${error.userMessage} See the 'Dapper Python Env' output channel for details.`
          : `Failed to initialize Dapper Python environment: ${message}. See the 'Dapper Python Env' output channel for details.`;
        vscode.window.showErrorMessage(userMessage);
        throw error;
      }
    }

    // Connect to the debug adapter server
    const server = this.server;
    if (!server) {
      throw new Error('Dapper adapter server was not created');
    }

    return new DebugAdapterServer(
      (server.address() as Net.AddressInfo).port,
      '127.0.0.1'
    );
  }

  dispose() {
    for (const disposable of this._disposables) {
      disposable.dispose();
    }
    this._disposables.length = 0;
    for (const launcherSessionId of [...this._childSessions.keys()]) {
      this._disposePendingChildSession(launcherSessionId, { destroySocket: true });
    }
    if (this.server) {
      this.server.close();
      this.server = undefined;
    }
    if (this._pythonIpcServer) {
      this._pythonIpcServer.close();
      this._pythonIpcServer = undefined;
    }
    if (this._adapterTerminal) {
      this._adapterTerminal.dispose();
      this._adapterTerminal = undefined;
    }
    this._pythonSocket = undefined;
    this._currentSession = undefined;
  }
}
