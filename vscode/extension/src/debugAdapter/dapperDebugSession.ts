import * as Net from 'net';
import {
  LoggingDebugSession,
  InitializedEvent, TerminatedEvent, StoppedEvent, OutputEvent,
  ContinuedEvent, ThreadEvent, BreakpointEvent, LoadedSourceEvent,
  ModuleEvent, ExitedEvent, Event,
} from '@vscode/debugadapter';
import type { DebugProtocol } from '@vscode/debugprotocol';
import type { AttachRequestArguments, LaunchRequestArguments } from './debugAdapterTypes.js';
import { PythonDebugAdapterTransport } from './pythonDebugAdapterTransport.js';
import { logger } from '../utils/logger.js';

export { PythonDebugAdapterTransport } from './pythonDebugAdapterTransport.js';

export class DapperDebugSession extends LoggingDebugSession {
  private static readonly THREAD_ID = 1;
  private _configurationDone = false;
  private _isRunning = false;
  private readonly _transport: PythonDebugAdapterTransport;
  private _eventWaiters: Array<{
    event: string;
    filter: (data: any) => boolean;
    resolve: (data: any) => void;
  }> = [];

  public constructor(transportOrSocket?: PythonDebugAdapterTransport | Net.Socket) {
    super();
    this._transport = transportOrSocket instanceof PythonDebugAdapterTransport
      ? transportOrSocket
      : new PythonDebugAdapterTransport(transportOrSocket);
    this._transport.attachSession(this);
    this.setDebuggerLinesStartAt1(false);
    this.setDebuggerColumnsStartAt1(false);
  }

  get configurationDone(): boolean {
    return this._configurationDone;
  }

  get isRunning(): boolean {
    return this._isRunning;
  }

  public handleTransportMessage(message: any): void {
    const eventName = message.event;
    const waiterIndex = this._eventWaiters.findIndex(w => w.event === eventName && w.filter(message));
    if (waiterIndex !== -1) {
      const waiter = this._eventWaiters[waiterIndex];
      this._eventWaiters.splice(waiterIndex, 1);
      waiter.resolve(message);
    }

    this.handleGeneralEvent(message);
  }

  public handleTransportClosed(exitCode: number): void {
    if (!this._isRunning) {
      return;
    }

    this._isRunning = false;
    this.sendEvent(new ExitedEvent(exitCode));
    this.sendEvent(new TerminatedEvent());
  }

  public disposeTransportAttachment(): void {
    this._transport.detachSession(this);
  }

  private handleGeneralEvent(message: any) {
    const body = message.body ?? {};
    switch (message.event) {
      case 'stopped':
        this.sendEvent(new StoppedEvent(body.reason, body.threadId ?? DapperDebugSession.THREAD_ID, body.text));
        break;
      case 'continued':
        this.sendEvent(new ContinuedEvent(body.threadId ?? DapperDebugSession.THREAD_ID, body.allThreadsContinued ?? true));
        break;
      case 'output':
        this.sendEvent(new OutputEvent(body.output, body.category));
        break;
      case 'initialized':
        this.sendEvent(new InitializedEvent());
        break;
      case 'terminated':
        this.sendEvent(new TerminatedEvent());
        break;
      case 'exited':
        this.sendEvent(new ExitedEvent(body.exitCode ?? 0));
        break;
      case 'thread':
        this.sendEvent(new ThreadEvent(body.reason, body.threadId));
        break;
      case 'breakpoint':
        this.sendEvent(new BreakpointEvent(body.reason, body.breakpoint));
        break;
      case 'loadedSource':
        this.sendEvent(new LoadedSourceEvent(body.reason, body.source));
        break;
      case 'module':
        this.sendEvent(new ModuleEvent(body.reason, body.module));
        break;
      case 'process':
      case 'dapper/childProcess':
      case 'dapper/childProcessExited':
      case 'dapper/childProcessCandidate':
      case 'dapper/hotReloadResult':
      case 'dapper/telemetry':
        this.sendEvent(new Event(message.event, body));
        break;
      case 'dapper/log':
        this.sendEvent(new OutputEvent(body.message || '', body.category || 'console'));
        break;
    }
  }

  private formatPythonError(result: any): string {
    if (!result) return 'Unknown error';

    let message = result.message || 'Unknown error';
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
    return this._transport.sendRequest(command, args, timeoutMs);
  }

  private waitForEvent(event: string, filter: (data: any) => boolean = () => true): Promise<any> {
    return new Promise(resolve => {
      this._eventWaiters.push({ event, filter, resolve });
    });
  }

  protected async initializeRequest(
    response: DebugProtocol.InitializeResponse,
    args: DebugProtocol.InitializeRequestArguments,
  ): Promise<void> {
    logger.log('initializeRequest: sending to Python');
    let result: any;
    try {
      result = await this._transport.sendSharedRequest('initialize', 'initialize', args);
      logger.debug(`initializeRequest: got response: ${JSON.stringify(result).substring(0, 200)}`);
    } catch (e) {
      logger.error('initializeRequest failed', e);
      result = { success: true, body: {} };
    }

    response.body = response.body || {};
    if (result.success && result.body) {
      Object.assign(response.body, result.body);
    }

    response.body.supportsConfigurationDoneRequest = true;
    response.body.supportsSetVariable = true;
    response.body.supportsEvaluateForHovers = true;

    this.sendResponse(response);
  }

  protected configurationDoneRequest(
    response: DebugProtocol.ConfigurationDoneResponse,
    args: DebugProtocol.ConfigurationDoneArguments,
    _request?: DebugProtocol.Request,
  ): void {
    logger.log('configurationDoneRequest: forwarding to Python');
    this._configurationDone = true;
    void this._transport.sendSharedRequest('configurationDone', 'configurationDone', args).catch((error) => {
      logger.error('configurationDoneRequest failed', error);
    });
    this.sendResponse(response);
  }

  protected async launchRequest(
    response: DebugProtocol.LaunchResponse,
    args: LaunchRequestArguments,
    _request?: DebugProtocol.Request,
  ): Promise<void> {
    logger.log('launchRequest: forwarding to Python');
    const result = await this._transport.sendSharedRequest('launch', 'launch', args);
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
    _request?: DebugProtocol.Request,
  ): Promise<void> {
    this._isRunning = false;
    this.disposeTransportAttachment();
    try {
      if (!this._transport.hasAttachedSessions()) {
        await this.sendRequestToPython('disconnect', args);
      }
    } catch {
      // Socket may already be closed; ignore
    }
    this.sendResponse(response);
  }

  protected async setBreakPointsRequest(response: DebugProtocol.SetBreakpointsResponse, args: DebugProtocol.SetBreakpointsArguments, _request?: DebugProtocol.Request): Promise<void> {
    logger.debug(`setBreakpoints: source=${args.source?.path ?? '<unknown>'} lines=${(args.breakpoints || []).map(b => b.line).join(',')}`);
    const result = await this.sendRequestToPython('setBreakpoints', args);
    logger.debug(`setBreakpoints: response breakpoints=${JSON.stringify(result?.body?.breakpoints?.map((b: any) => ({ line: b.line, verified: b.verified })))}`);
    response.body = { breakpoints: (result.body && result.body.breakpoints) || [] };
    this.sendResponse(response);
  }

  protected async threadsRequest(response: DebugProtocol.ThreadsResponse, _request?: DebugProtocol.Request): Promise<void> {
    try {
      const result = await this.sendRequestToPython('threads', {});
      response.body = { threads: (result.body && result.body.threads) || [] };
    } catch {
      response.body = { threads: [{ id: DapperDebugSession.THREAD_ID, name: 'MainThread' }] };
    }
    this.sendResponse(response);
  }

  protected async stackTraceRequest(response: DebugProtocol.StackTraceResponse, args: DebugProtocol.StackTraceArguments, _request?: DebugProtocol.Request): Promise<void> {
    try {
      const result = await this.sendRequestToPython('stackTrace', args);
      response.body = {
        stackFrames: (result.body && result.body.stackFrames) || [],
        totalFrames: (result.body && result.body.totalFrames) || 0,
      };
    } catch {
      response.body = { stackFrames: [], totalFrames: 0 };
    }
    this.sendResponse(response);
  }

  protected async scopesRequest(response: DebugProtocol.ScopesResponse, args: DebugProtocol.ScopesArguments, _request?: DebugProtocol.Request): Promise<void> {
    try {
      const result = await this.sendRequestToPython('scopes', args);
      response.body = { scopes: (result.body && result.body.scopes) || [] };
    } catch {
      response.body = { scopes: [] };
    }
    this.sendResponse(response);
  }

  protected async variablesRequest(response: DebugProtocol.VariablesResponse, args: DebugProtocol.VariablesArguments, _request?: DebugProtocol.Request): Promise<void> {
    try {
      const result = await this.sendRequestToPython('variables', args);
      response.body = { variables: (result.body && result.body.variables) || [] };
    } catch {
      response.body = { variables: [] };
    }
    this.sendResponse(response);
  }

  protected async attachRequest(response: DebugProtocol.AttachResponse, args: AttachRequestArguments, _request?: DebugProtocol.Request): Promise<void> {
    const result = await this._transport.sendSharedRequest('attach', 'attach', args);
    if (result && result.success === false) {
      response.success = false;
      response.message = this.formatPythonError(result);
    }
    this.sendResponse(response);
  }

  protected async setFunctionBreakPointsRequest(response: DebugProtocol.SetFunctionBreakpointsResponse, args: DebugProtocol.SetFunctionBreakpointsArguments, _request?: DebugProtocol.Request): Promise<void> {
    const result = await this.sendRequestToPython('setFunctionBreakpoints', args);
    response.body = { breakpoints: (result.body && result.body.breakpoints) || [] };
    this.sendResponse(response);
  }

  protected async setExceptionBreakPointsRequest(response: DebugProtocol.SetExceptionBreakpointsResponse, args: DebugProtocol.SetExceptionBreakpointsArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this.sendRequestToPython('setExceptionBreakpoints', args);
    this.sendResponse(response);
  }

  protected async continueRequest(response: DebugProtocol.ContinueResponse, args: DebugProtocol.ContinueArguments, _request?: DebugProtocol.Request): Promise<void> {
    const result = await this.sendRequestToPython('continue', args);
    response.body = { allThreadsContinued: result.body?.allThreadsContinued ?? true };
    this.sendResponse(response);
  }

  protected async nextRequest(response: DebugProtocol.NextResponse, args: DebugProtocol.NextArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this.sendRequestToPython('next', args);
    this.sendResponse(response);
  }

  protected async stepInRequest(response: DebugProtocol.StepInResponse, args: DebugProtocol.StepInArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this.sendRequestToPython('stepIn', args);
    this.sendResponse(response);
  }

  protected async stepOutRequest(response: DebugProtocol.StepOutResponse, args: DebugProtocol.StepOutArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this.sendRequestToPython('stepOut', args);
    this.sendResponse(response);
  }

  protected async stepInTargetsRequest(response: DebugProtocol.StepInTargetsResponse, args: DebugProtocol.StepInTargetsArguments, _request?: DebugProtocol.Request): Promise<void> {
    const result = await this.sendRequestToPython('stepInTargets', args);
    response.body = { targets: (result.body && result.body.targets) || [] };
    this.sendResponse(response);
  }

  protected async pauseRequest(response: DebugProtocol.PauseResponse, args: DebugProtocol.PauseArguments, _request?: DebugProtocol.Request): Promise<void> {
    const result = await this.sendRequestToPython('pause', args);
    if (result && result.success === false) {
      response.success = false;
      response.message = this.formatPythonError(result);
    }
    this.sendResponse(response);
  }

  protected async terminateRequest(response: DebugProtocol.TerminateResponse, args: DebugProtocol.TerminateArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this.sendRequestToPython('terminate', args);
    this.sendResponse(response);
  }

  protected async loadedSourcesRequest(response: DebugProtocol.LoadedSourcesResponse, args: DebugProtocol.LoadedSourcesArguments, _request?: DebugProtocol.Request): Promise<void> {
    const result = await this.sendRequestToPython('loadedSources', args);
    response.body = { sources: (result.body && result.body.sources) || [] };
    this.sendResponse(response);
  }

  protected async breakpointLocationsRequest(response: DebugProtocol.BreakpointLocationsResponse, args: DebugProtocol.BreakpointLocationsArguments, _request?: DebugProtocol.Request): Promise<void> {
    const result = await this.sendRequestToPython('breakpointLocations', args);
    response.body = { breakpoints: (result.body && result.body.breakpoints) || [] };
    this.sendResponse(response);
  }

  protected async sourceRequest(response: DebugProtocol.SourceResponse, args: DebugProtocol.SourceArguments, _request?: DebugProtocol.Request): Promise<void> {
    const result = await this.sendRequestToPython('source', args);
    if (result && result.success === false) {
      response.success = false;
      response.message = this.formatPythonError(result);
    } else {
      response.body = { content: result.body?.content ?? '', mimeType: result.body?.mimeType };
    }
    this.sendResponse(response);
  }

  protected async modulesRequest(response: DebugProtocol.ModulesResponse, args: DebugProtocol.ModulesArguments, _request?: DebugProtocol.Request): Promise<void> {
    const result = await this.sendRequestToPython('modules', args);
    response.body = {
      modules: (result.body && result.body.modules) || [],
      totalModules: result.body?.totalModules,
    };
    this.sendResponse(response);
  }

  protected async setVariableRequest(response: DebugProtocol.SetVariableResponse, args: DebugProtocol.SetVariableArguments, _request?: DebugProtocol.Request): Promise<void> {
    const result = await this.sendRequestToPython('setVariable', args);
    if (result && result.success === false) {
      response.success = false;
      response.message = this.formatPythonError(result);
    } else {
      response.body = result.body ?? {};
    }
    this.sendResponse(response);
  }

  protected async setExpressionRequest(response: DebugProtocol.SetExpressionResponse, args: DebugProtocol.SetExpressionArguments, _request?: DebugProtocol.Request): Promise<void> {
    const result = await this.sendRequestToPython('setExpression', args);
    if (result && result.success === false) {
      response.success = false;
      response.message = this.formatPythonError(result);
    } else {
      response.body = { value: result.body?.value ?? '', type: result.body?.type };
    }
    this.sendResponse(response);
  }

  protected async evaluateRequest(response: DebugProtocol.EvaluateResponse, args: DebugProtocol.EvaluateArguments, _request?: DebugProtocol.Request): Promise<void> {
    const result = await this.sendRequestToPython('evaluate', args);
    if (result && result.success === false) {
      response.success = false;
      response.message = this.formatPythonError(result);
    } else {
      response.body = result.body ?? { result: '', variablesReference: 0 };
    }
    this.sendResponse(response);
  }

  protected async dataBreakpointInfoRequest(response: DebugProtocol.DataBreakpointInfoResponse, args: DebugProtocol.DataBreakpointInfoArguments, _request?: DebugProtocol.Request): Promise<void> {
    const result = await this.sendRequestToPython('dataBreakpointInfo', args);
    response.body = result.body ?? { dataId: null, description: 'Unavailable' };
    this.sendResponse(response);
  }

  protected async setDataBreakpointsRequest(response: DebugProtocol.SetDataBreakpointsResponse, args: DebugProtocol.SetDataBreakpointsArguments, _request?: DebugProtocol.Request): Promise<void> {
    const result = await this.sendRequestToPython('setDataBreakpoints', args);
    response.body = { breakpoints: (result.body && result.body.breakpoints) || [] };
    this.sendResponse(response);
  }

  protected async exceptionInfoRequest(response: DebugProtocol.ExceptionInfoResponse, args: DebugProtocol.ExceptionInfoArguments, _request?: DebugProtocol.Request): Promise<void> {
    const result = await this.sendRequestToPython('exceptionInfo', args);
    if (result && result.success === false) {
      response.success = false;
      response.message = this.formatPythonError(result);
    } else {
      response.body = result.body ?? { exceptionId: '', breakMode: 'never' };
    }
    this.sendResponse(response);
  }

  protected async completionsRequest(response: DebugProtocol.CompletionsResponse, args: DebugProtocol.CompletionsArguments, _request?: DebugProtocol.Request): Promise<void> {
    const result = await this.sendRequestToPython('completions', args);
    response.body = { targets: (result.body && result.body.targets) || [] };
    this.sendResponse(response);
  }

  protected async customRequest(command: string, response: DebugProtocol.Response, args: any, _request?: DebugProtocol.Request): Promise<void> {
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