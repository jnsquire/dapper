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
import { DapperDebugSessionRequestHandlers } from './dapperDebugSessionRequests.js';

export { PythonDebugAdapterTransport } from './pythonDebugAdapterTransport.js';

export class DapperDebugSession extends LoggingDebugSession {
  private static readonly THREAD_ID = 1;
  private _configurationDone = false;
  private _isRunning = false;
  private readonly _transport: PythonDebugAdapterTransport;
  private readonly _requestHandlers: DapperDebugSessionRequestHandlers;

  public constructor(transportOrSocket?: PythonDebugAdapterTransport | Net.Socket) {
    super();
    this._transport = transportOrSocket instanceof PythonDebugAdapterTransport
      ? transportOrSocket
      : new PythonDebugAdapterTransport(transportOrSocket);
    this._transport.attachSession(this);
    this._requestHandlers = new DapperDebugSessionRequestHandlers({
      sendRequestToPython: this.sendRequestToPython.bind(this),
      sendSharedRequestToPython: this._transport.sendSharedRequest.bind(this._transport),
      formatPythonError: this.formatPythonError.bind(this),
      sendResponse: (response: DebugProtocol.Response) => {
        this.sendResponse(response);
      },
      setConfigurationDone: (value: boolean) => {
        this._configurationDone = value;
      },
      setRunning: (value: boolean) => {
        this._isRunning = value;
      },
      disposeTransportAttachment: () => {
        this.disposeTransportAttachment();
      },
      hasAttachedSessions: () => this._transport.hasAttachedSessions(),
    });
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

  protected async initializeRequest(
    response: DebugProtocol.InitializeResponse,
    args: DebugProtocol.InitializeRequestArguments,
  ): Promise<void> {
    await this._requestHandlers.initializeRequest(response, args);
  }

  protected configurationDoneRequest(
    response: DebugProtocol.ConfigurationDoneResponse,
    args: DebugProtocol.ConfigurationDoneArguments,
    _request?: DebugProtocol.Request,
  ): void {
    this._requestHandlers.configurationDoneRequest(response, args);
  }

  protected async launchRequest(
    response: DebugProtocol.LaunchResponse,
    args: LaunchRequestArguments,
    _request?: DebugProtocol.Request,
  ): Promise<void> {
    await this._requestHandlers.launchRequest(response, args);
  }

  protected async disconnectRequest(
    response: DebugProtocol.DisconnectResponse,
    args: DebugProtocol.DisconnectArguments,
    _request?: DebugProtocol.Request,
  ): Promise<void> {
    await this._requestHandlers.disconnectRequest(response, args);
  }

  protected async setBreakPointsRequest(response: DebugProtocol.SetBreakpointsResponse, args: DebugProtocol.SetBreakpointsArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this._requestHandlers.setBreakPointsRequest(response, args);
  }

  protected async threadsRequest(response: DebugProtocol.ThreadsResponse, _request?: DebugProtocol.Request): Promise<void> {
    await this._requestHandlers.threadsRequest(response);
  }

  protected async stackTraceRequest(response: DebugProtocol.StackTraceResponse, args: DebugProtocol.StackTraceArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this._requestHandlers.stackTraceRequest(response, args);
  }

  protected async scopesRequest(response: DebugProtocol.ScopesResponse, args: DebugProtocol.ScopesArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this._requestHandlers.scopesRequest(response, args);
  }

  protected async variablesRequest(response: DebugProtocol.VariablesResponse, args: DebugProtocol.VariablesArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this._requestHandlers.variablesRequest(response, args);
  }

  protected async attachRequest(response: DebugProtocol.AttachResponse, args: AttachRequestArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this._requestHandlers.attachRequest(response, args);
  }

  protected async setFunctionBreakPointsRequest(response: DebugProtocol.SetFunctionBreakpointsResponse, args: DebugProtocol.SetFunctionBreakpointsArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this._requestHandlers.setFunctionBreakPointsRequest(response, args);
  }

  protected async setExceptionBreakPointsRequest(response: DebugProtocol.SetExceptionBreakpointsResponse, args: DebugProtocol.SetExceptionBreakpointsArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this._requestHandlers.setExceptionBreakPointsRequest(response, args);
  }

  protected async continueRequest(response: DebugProtocol.ContinueResponse, args: DebugProtocol.ContinueArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this._requestHandlers.continueRequest(response, args);
  }

  protected async nextRequest(response: DebugProtocol.NextResponse, args: DebugProtocol.NextArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this._requestHandlers.nextRequest(response, args);
  }

  protected async stepInRequest(response: DebugProtocol.StepInResponse, args: DebugProtocol.StepInArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this._requestHandlers.stepInRequest(response, args);
  }

  protected async stepOutRequest(response: DebugProtocol.StepOutResponse, args: DebugProtocol.StepOutArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this._requestHandlers.stepOutRequest(response, args);
  }

  protected async stepInTargetsRequest(response: DebugProtocol.StepInTargetsResponse, args: DebugProtocol.StepInTargetsArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this._requestHandlers.stepInTargetsRequest(response, args);
  }

  protected async pauseRequest(response: DebugProtocol.PauseResponse, args: DebugProtocol.PauseArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this._requestHandlers.pauseRequest(response, args);
  }

  protected async terminateRequest(response: DebugProtocol.TerminateResponse, args: DebugProtocol.TerminateArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this._requestHandlers.terminateRequest(response, args);
  }

  protected async loadedSourcesRequest(response: DebugProtocol.LoadedSourcesResponse, args: DebugProtocol.LoadedSourcesArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this._requestHandlers.loadedSourcesRequest(response, args);
  }

  protected async breakpointLocationsRequest(response: DebugProtocol.BreakpointLocationsResponse, args: DebugProtocol.BreakpointLocationsArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this._requestHandlers.breakpointLocationsRequest(response, args);
  }

  protected async sourceRequest(response: DebugProtocol.SourceResponse, args: DebugProtocol.SourceArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this._requestHandlers.sourceRequest(response, args);
  }

  protected async modulesRequest(response: DebugProtocol.ModulesResponse, args: DebugProtocol.ModulesArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this._requestHandlers.modulesRequest(response, args);
  }

  protected async setVariableRequest(response: DebugProtocol.SetVariableResponse, args: DebugProtocol.SetVariableArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this._requestHandlers.setVariableRequest(response, args);
  }

  protected async setExpressionRequest(response: DebugProtocol.SetExpressionResponse, args: DebugProtocol.SetExpressionArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this._requestHandlers.setExpressionRequest(response, args);
  }

  protected async evaluateRequest(response: DebugProtocol.EvaluateResponse, args: DebugProtocol.EvaluateArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this._requestHandlers.evaluateRequest(response, args);
  }

  protected async dataBreakpointInfoRequest(response: DebugProtocol.DataBreakpointInfoResponse, args: DebugProtocol.DataBreakpointInfoArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this._requestHandlers.dataBreakpointInfoRequest(response, args);
  }

  protected async setDataBreakpointsRequest(response: DebugProtocol.SetDataBreakpointsResponse, args: DebugProtocol.SetDataBreakpointsArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this._requestHandlers.setDataBreakpointsRequest(response, args);
  }

  protected async exceptionInfoRequest(response: DebugProtocol.ExceptionInfoResponse, args: DebugProtocol.ExceptionInfoArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this._requestHandlers.exceptionInfoRequest(response, args);
  }

  protected async completionsRequest(response: DebugProtocol.CompletionsResponse, args: DebugProtocol.CompletionsArguments, _request?: DebugProtocol.Request): Promise<void> {
    await this._requestHandlers.completionsRequest(response, args);
  }

  protected async customRequest(command: string, response: DebugProtocol.Response, args: any, _request?: DebugProtocol.Request): Promise<void> {
    await this._requestHandlers.customRequest(command, response, args);
  }
}