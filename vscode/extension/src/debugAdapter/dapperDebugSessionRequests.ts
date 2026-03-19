import type { DebugProtocol } from '@vscode/debugprotocol';
import type { BreakpointVerificationRecord } from '../agent/stateJournal.js';

import type { AttachRequestArguments, LaunchRequestArguments } from './debugAdapterTypes.js';
import { logger } from '../utils/logger.js';

type SendRequest = (command: string, args?: any, timeoutMs?: number) => Promise<any>;
type SendSharedRequest = (key: string, command: string, args?: any, timeoutMs?: number) => Promise<any>;
const CONFIGURATION_DONE_READINESS_TIMEOUT_MS = 5_000;

export type ReadinessGateState =
  | { kind: 'ready' }
  | { kind: 'pending'; pendingBreakpoints: number }
  | { kind: 'rejected'; rejectedBreakpoints: number; firstRejected?: BreakpointVerificationRecord }
  | { kind: 'error'; lastError: string }
  | { kind: 'timedOut'; pendingBreakpoints: number };

interface SessionControls {
  sendRequestToPython: SendRequest;
  sendSharedRequestToPython: SendSharedRequest;
  formatPythonError(result: any): string;
  sendResponse(response: DebugProtocol.Response): void;
  setConfigurationDone(value: boolean): void;
  setRunning(value: boolean): void;
  disposeTransportAttachment(): void;
  hasAttachedSessions(): boolean;
  setPendingBreakpoints(args: DebugProtocol.SetBreakpointsArguments): void;
  updateBreakpointVerification(args: DebugProtocol.SetBreakpointsArguments, result: any): void;
  getReadinessGateState(): ReadinessGateState;
  waitForReadinessGateState(timeoutMs: number): Promise<ReadinessGateState>;
}

export class DapperDebugSessionRequestHandlers {
  constructor(private readonly controls: SessionControls) {}

  private applyReadinessGateFailure(response: DebugProtocol.Response, readiness = this.controls.getReadinessGateState()): boolean {
    switch (readiness.kind) {
      case 'ready':
        return false;
      case 'timedOut':
        response.success = false;
        response.message = `Debugger session did not become ready before timeout: waiting for ${readiness.pendingBreakpoints} breakpoint verification result(s).`;
        return true;
      case 'error':
        response.success = false;
        response.message = `Debugger session is not ready: ${readiness.lastError}`;
        return true;
      case 'pending':
        response.success = false;
        response.message = `Debugger session is not ready: waiting for ${readiness.pendingBreakpoints} breakpoint verification result(s).`;
        return true;
      case 'rejected': {
        response.success = false;
        const rejectionMessage = readiness.firstRejected?.verificationMessage;
        response.message = rejectionMessage
          ? `Debugger session is not ready: ${rejectionMessage}`
          : `Debugger session is not ready: ${readiness.rejectedBreakpoints} breakpoint(s) were rejected.`;
        return true;
      }
    }
  }

  private applyPythonFailure(response: DebugProtocol.Response, result: any): boolean {
    if (!(result && result.success === false)) {
      return false;
    }

    response.success = false;
    response.message = this.controls.formatPythonError(result);
    return true;
  }

  public async initializeRequest(
    response: DebugProtocol.InitializeResponse,
    args: DebugProtocol.InitializeRequestArguments,
  ): Promise<void> {
    logger.log('initializeRequest: sending to Python');
    let result: any;
    try {
      result = await this.controls.sendSharedRequestToPython('initialize', 'initialize', args);
      logger.debug(`initializeRequest: got response: ${JSON.stringify(result).substring(0, 200)}`);
    } catch (error) {
      logger.error('initializeRequest failed', error);
      result = { success: true, body: {} };
    }

    response.body = response.body || {};
    if (result.success && result.body) {
      Object.assign(response.body, result.body);
    }

    response.body.supportsConfigurationDoneRequest = true;
    response.body.supportsSetVariable = true;
    response.body.supportsEvaluateForHovers = true;

    this.controls.sendResponse(response);
  }

  public async configurationDoneRequest(
    response: DebugProtocol.ConfigurationDoneResponse,
    args: DebugProtocol.ConfigurationDoneArguments,
  ): Promise<void> {
    logger.log('configurationDoneRequest: waiting for breakpoint readiness');
    const readiness = await this.controls.waitForReadinessGateState(CONFIGURATION_DONE_READINESS_TIMEOUT_MS);
    if (this.applyReadinessGateFailure(response, readiness)) {
      this.controls.sendResponse(response);
      return;
    }

    logger.log('configurationDoneRequest: forwarding to Python');
    this.controls.setConfigurationDone(true);
    try {
      await this.controls.sendRequestToPython('configurationDone', args);
    } catch (error) {
      logger.error('configurationDoneRequest failed', error);
      response.success = false;
      response.message = error instanceof Error ? error.message : String(error);
    }
    this.controls.sendResponse(response);
  }

  public async launchRequest(
    response: DebugProtocol.LaunchResponse,
    args: LaunchRequestArguments,
  ): Promise<void> {
    logger.log('launchRequest: forwarding to Python');
    const result = await this.controls.sendSharedRequestToPython('launch', 'launch', args);
    logger.log(`launchRequest: response success=${result?.success}`);
    if (!this.applyPythonFailure(response, result)) {
      this.controls.setRunning(true);
    }
    this.controls.sendResponse(response);
  }

  public async disconnectRequest(
    response: DebugProtocol.DisconnectResponse,
    args: DebugProtocol.DisconnectArguments,
  ): Promise<void> {
    this.controls.setRunning(false);
    this.controls.disposeTransportAttachment();
    try {
      if (!this.controls.hasAttachedSessions()) {
        await this.controls.sendRequestToPython('disconnect', args);
      }
    } catch {
      // Socket may already be closed; ignore
    }
    this.controls.sendResponse(response);
  }

  public async setBreakPointsRequest(
    response: DebugProtocol.SetBreakpointsResponse,
    args: DebugProtocol.SetBreakpointsArguments,
  ): Promise<void> {
    logger.debug(`setBreakpoints: source=${args.source?.path ?? '<unknown>'} lines=${(args.breakpoints || []).map(b => b.line).join(',')}`);
    this.controls.setPendingBreakpoints(args);
    const result = await this.controls.sendRequestToPython('setBreakpoints', args);
    this.controls.updateBreakpointVerification(args, result);
    logger.debug(`setBreakpoints: response breakpoints=${JSON.stringify(result?.body?.breakpoints?.map((b: any) => ({ line: b.line, verified: b.verified })))}`);
    response.body = { breakpoints: (result.body && result.body.breakpoints) || [] };
    this.controls.sendResponse(response);
  }

  public async threadsRequest(response: DebugProtocol.ThreadsResponse): Promise<void> {
    try {
      const result = await this.controls.sendRequestToPython('threads', {});
      response.body = { threads: (result.body && result.body.threads) || [] };
    } catch {
      response.body = { threads: [{ id: 1, name: 'MainThread' }] };
    }
    this.controls.sendResponse(response);
  }

  public async stackTraceRequest(response: DebugProtocol.StackTraceResponse, args: DebugProtocol.StackTraceArguments): Promise<void> {
    try {
      const result = await this.controls.sendRequestToPython('stackTrace', args);
      response.body = {
        stackFrames: (result.body && result.body.stackFrames) || [],
        totalFrames: (result.body && result.body.totalFrames) || 0,
      };
    } catch {
      response.body = { stackFrames: [], totalFrames: 0 };
    }
    this.controls.sendResponse(response);
  }

  public async scopesRequest(response: DebugProtocol.ScopesResponse, args: DebugProtocol.ScopesArguments): Promise<void> {
    try {
      const result = await this.controls.sendRequestToPython('scopes', args);
      response.body = { scopes: (result.body && result.body.scopes) || [] };
    } catch {
      response.body = { scopes: [] };
    }
    this.controls.sendResponse(response);
  }

  public async variablesRequest(response: DebugProtocol.VariablesResponse, args: DebugProtocol.VariablesArguments): Promise<void> {
    try {
      const result = await this.controls.sendRequestToPython('variables', args);
      response.body = { variables: (result.body && result.body.variables) || [] };
    } catch {
      response.body = { variables: [] };
    }
    this.controls.sendResponse(response);
  }

  public async attachRequest(
    response: DebugProtocol.AttachResponse,
    args: AttachRequestArguments,
  ): Promise<void> {
    const result = await this.controls.sendSharedRequestToPython('attach', 'attach', args);
    this.applyPythonFailure(response, result);
    this.controls.sendResponse(response);
  }

  public async setFunctionBreakPointsRequest(response: DebugProtocol.SetFunctionBreakpointsResponse, args: DebugProtocol.SetFunctionBreakpointsArguments): Promise<void> {
    const result = await this.controls.sendRequestToPython('setFunctionBreakpoints', args);
    response.body = { breakpoints: (result.body && result.body.breakpoints) || [] };
    this.controls.sendResponse(response);
  }

  public async setExceptionBreakPointsRequest(response: DebugProtocol.SetExceptionBreakpointsResponse, args: DebugProtocol.SetExceptionBreakpointsArguments): Promise<void> {
    await this.controls.sendRequestToPython('setExceptionBreakpoints', args);
    this.controls.sendResponse(response);
  }

  public async continueRequest(response: DebugProtocol.ContinueResponse, args: DebugProtocol.ContinueArguments): Promise<void> {
    if (this.applyReadinessGateFailure(response)) {
      this.controls.sendResponse(response);
      return;
    }
    const result = await this.controls.sendRequestToPython('continue', args);
    response.body = { allThreadsContinued: result.body?.allThreadsContinued ?? true };
    this.controls.sendResponse(response);
  }

  public async nextRequest(response: DebugProtocol.NextResponse, args: DebugProtocol.NextArguments): Promise<void> {
    if (this.applyReadinessGateFailure(response)) {
      this.controls.sendResponse(response);
      return;
    }
    await this.controls.sendRequestToPython('next', args);
    this.controls.sendResponse(response);
  }

  public async stepInRequest(response: DebugProtocol.StepInResponse, args: DebugProtocol.StepInArguments): Promise<void> {
    if (this.applyReadinessGateFailure(response)) {
      this.controls.sendResponse(response);
      return;
    }
    await this.controls.sendRequestToPython('stepIn', args);
    this.controls.sendResponse(response);
  }

  public async stepOutRequest(response: DebugProtocol.StepOutResponse, args: DebugProtocol.StepOutArguments): Promise<void> {
    if (this.applyReadinessGateFailure(response)) {
      this.controls.sendResponse(response);
      return;
    }
    await this.controls.sendRequestToPython('stepOut', args);
    this.controls.sendResponse(response);
  }

  public async stepInTargetsRequest(response: DebugProtocol.StepInTargetsResponse, args: DebugProtocol.StepInTargetsArguments): Promise<void> {
    const result = await this.controls.sendRequestToPython('stepInTargets', args);
    response.body = { targets: (result.body && result.body.targets) || [] };
    this.controls.sendResponse(response);
  }

  public async pauseRequest(response: DebugProtocol.PauseResponse, args: DebugProtocol.PauseArguments): Promise<void> {
    const result = await this.controls.sendRequestToPython('pause', args);
    if (result && result.success === false) {
      response.success = false;
      response.message = this.controls.formatPythonError(result);
    }
    this.controls.sendResponse(response);
  }

  public async terminateRequest(response: DebugProtocol.TerminateResponse, args: DebugProtocol.TerminateArguments): Promise<void> {
    await this.controls.sendRequestToPython('terminate', args);
    this.controls.sendResponse(response);
  }

  public async loadedSourcesRequest(response: DebugProtocol.LoadedSourcesResponse, args: DebugProtocol.LoadedSourcesArguments): Promise<void> {
    const result = await this.controls.sendRequestToPython('loadedSources', args);
    response.body = { sources: (result.body && result.body.sources) || [] };
    this.controls.sendResponse(response);
  }

  public async breakpointLocationsRequest(response: DebugProtocol.BreakpointLocationsResponse, args: DebugProtocol.BreakpointLocationsArguments): Promise<void> {
    const result = await this.controls.sendRequestToPython('breakpointLocations', args);
    response.body = { breakpoints: (result.body && result.body.breakpoints) || [] };
    this.controls.sendResponse(response);
  }

  public async sourceRequest(response: DebugProtocol.SourceResponse, args: DebugProtocol.SourceArguments): Promise<void> {
    const result = await this.controls.sendRequestToPython('source', args);
    if (!this.applyPythonFailure(response, result)) {
      response.body = { content: result.body?.content ?? '', mimeType: result.body?.mimeType };
    }
    this.controls.sendResponse(response);
  }

  public async modulesRequest(response: DebugProtocol.ModulesResponse, args: DebugProtocol.ModulesArguments): Promise<void> {
    const result = await this.controls.sendRequestToPython('modules', args);
    response.body = {
      modules: (result.body && result.body.modules) || [],
      totalModules: result.body?.totalModules,
    };
    this.controls.sendResponse(response);
  }

  public async setVariableRequest(response: DebugProtocol.SetVariableResponse, args: DebugProtocol.SetVariableArguments): Promise<void> {
    const result = await this.controls.sendRequestToPython('setVariable', args);
    if (!this.applyPythonFailure(response, result)) {
      response.body = result.body ?? {};
    }
    this.controls.sendResponse(response);
  }

  public async setExpressionRequest(response: DebugProtocol.SetExpressionResponse, args: DebugProtocol.SetExpressionArguments): Promise<void> {
    const result = await this.controls.sendRequestToPython('setExpression', args);
    if (!this.applyPythonFailure(response, result)) {
      response.body = { value: result.body?.value ?? '', type: result.body?.type };
    }
    this.controls.sendResponse(response);
  }

  public async evaluateRequest(response: DebugProtocol.EvaluateResponse, args: DebugProtocol.EvaluateArguments): Promise<void> {
    const result = await this.controls.sendRequestToPython('evaluate', args);
    if (!this.applyPythonFailure(response, result)) {
      response.body = result.body ?? { result: '', variablesReference: 0 };
    }
    this.controls.sendResponse(response);
  }

  public async dataBreakpointInfoRequest(response: DebugProtocol.DataBreakpointInfoResponse, args: DebugProtocol.DataBreakpointInfoArguments): Promise<void> {
    const result = await this.controls.sendRequestToPython('dataBreakpointInfo', args);
    response.body = result.body ?? { dataId: null, description: 'Unavailable' };
    this.controls.sendResponse(response);
  }

  public async setDataBreakpointsRequest(response: DebugProtocol.SetDataBreakpointsResponse, args: DebugProtocol.SetDataBreakpointsArguments): Promise<void> {
    const result = await this.controls.sendRequestToPython('setDataBreakpoints', args);
    response.body = { breakpoints: (result.body && result.body.breakpoints) || [] };
    this.controls.sendResponse(response);
  }

  public async exceptionInfoRequest(response: DebugProtocol.ExceptionInfoResponse, args: DebugProtocol.ExceptionInfoArguments): Promise<void> {
    const result = await this.controls.sendRequestToPython('exceptionInfo', args);
    if (!this.applyPythonFailure(response, result)) {
      response.body = result.body ?? { exceptionId: '', breakMode: 'never' };
    }
    this.controls.sendResponse(response);
  }

  public async completionsRequest(response: DebugProtocol.CompletionsResponse, args: DebugProtocol.CompletionsArguments): Promise<void> {
    const result = await this.controls.sendRequestToPython('completions', args);
    response.body = { targets: (result.body && result.body.targets) || [] };
    this.controls.sendResponse(response);
  }

  public async customRequest(command: string, response: DebugProtocol.Response, args: any): Promise<void> {
    if (command.startsWith('dapper/')) {
      try {
        const result = await this.controls.sendRequestToPython(command, args || {});
        if (!this.applyPythonFailure(response, result)) {
          response.body = result?.body || {};
        }
      } catch (error) {
        response.success = false;
        response.message = error instanceof Error ? error.message : String(error);
      }
    } else {
      response.success = false;
      response.message = `Unrecognized custom request: ${command}`;
    }
    this.controls.sendResponse(response);
  }
}