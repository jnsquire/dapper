/**
 * dapper_breakpoints — List or manage breakpoints via the VS Code API.
 */

import * as vscode from 'vscode';
import type { JournalRegistry } from '../stateJournal.js';
import { toBreakpointVerificationRecord } from '../stateJournal.js';
import { resolveSession, jsonResult, errorResult } from '../toolUtils.js';

interface BreakpointsToolInput {
  sessionId?: string;
  action: 'list' | 'add' | 'remove' | 'clear';
  file?: string;
  lines?: number[];
  condition?: string;
  logMessage?: string;
}

interface BreakpointInfo {
  file: string;
  line: number;
  enabled: boolean;
  verified?: boolean;
  verificationState?: 'verified' | 'pending' | 'rejected';
  verificationMessage?: string;
  condition?: string;
  hitCondition?: string;
  logMessage?: string;
}

export class BreakpointsTool implements vscode.LanguageModelTool<BreakpointsToolInput> {
  constructor(private registry: JournalRegistry) {}

  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<BreakpointsToolInput>,
    _token: vscode.CancellationToken,
  ): Promise<vscode.LanguageModelToolResult> {
    const { sessionId, action, file, lines, condition, logMessage } = options.input;

    if (action === 'list') {
      return this._listBreakpoints(sessionId, file);
    }

    if (!file) {
      return errorResult(`Action '${action}' requires a file path`);
    }

    const uri = this._resolveFileUri(file);
    if (!uri) {
      return errorResult(`Could not resolve file: ${file}`);
    }

    switch (action) {
      case 'add':
        return this._addBreakpoints(sessionId, uri, lines ?? [], condition, logMessage);
      case 'remove':
        return this._removeBreakpoints(sessionId, uri, lines ?? []);
      case 'clear':
        return this._clearBreakpoints(sessionId, uri);
      default:
        return errorResult(`Unknown action: ${action}`);
    }
  }

  private _resolveFileUri(file: string): vscode.Uri | undefined {
    if (file.startsWith('/') || /^[a-zA-Z]:[\\/]/.test(file)) {
      return vscode.Uri.file(file);
    }
    const folders = vscode.workspace.workspaceFolders;
    if (folders && folders.length > 0) {
      return vscode.Uri.joinPath(folders[0].uri, file);
    }
    return undefined;
  }

  private async _listBreakpoints(
    sessionId: string | undefined,
    file: string | undefined,
  ): Promise<vscode.LanguageModelToolResult> {
    const allBreakpoints = vscode.debug.breakpoints;
    const resolved = resolveSession(this.registry, sessionId);
    const journal = resolved?.journal;

    const results: BreakpointInfo[] = [];
    for (const bp of allBreakpoints) {
      if (!(bp instanceof vscode.SourceBreakpoint)) continue;

      const bpPath = bp.location.uri.fsPath;
      if (file) {
        const normalizedFile = file.startsWith('/')
          ? file
          : vscode.Uri.joinPath(vscode.workspace.workspaceFolders?.[0]?.uri ?? vscode.Uri.file('/'), file).fsPath;
        if (bpPath !== normalizedFile) continue;
      }

      const info: BreakpointInfo = {
        file: vscode.workspace.asRelativePath(bpPath, false),
        line: bp.location.range.start.line + 1,
        enabled: bp.enabled,
      };
      if (bp.condition) info.condition = bp.condition;
      if (bp.hitCondition) info.hitCondition = bp.hitCondition;
      if (bp.logMessage) info.logMessage = bp.logMessage;
      const cachedVerification = journal?.getBreakpointVerification(bpPath, bp.location.range.start.line + 1);
      if (cachedVerification) {
        info.verified = cachedVerification.verified;
        info.verificationState = cachedVerification.verificationState;
        if (cachedVerification.verificationMessage) {
          info.verificationMessage = cachedVerification.verificationMessage;
        }
      }
      results.push(info);
    }

    return jsonResult({
      action: 'list',
      count: results.length,
      breakpoints: results,
    });
  }

  private async _addBreakpoints(
    sessionId: string | undefined,
    uri: vscode.Uri,
    lines: number[],
    condition?: string,
    logMessage?: string,
  ): Promise<vscode.LanguageModelToolResult> {
    if (lines.length === 0) {
      return errorResult('No line numbers provided for add action');
    }

    const newBps = lines.map(line => {
      const position = new vscode.Position(line - 1, 0);
      const location = new vscode.Location(uri, position);
      return new vscode.SourceBreakpoint(location, true, condition, undefined, logMessage);
    });

    vscode.debug.addBreakpoints(newBps);

    const resolved = resolveSession(this.registry, sessionId);
    if (resolved) {
      const uriStr = uri.toString();
      const allBps = vscode.debug.breakpoints
        .filter((bp): bp is vscode.SourceBreakpoint =>
          bp instanceof vscode.SourceBreakpoint && bp.location.uri.toString() === uriStr,
        )
        .map(bp => ({
          line: bp.location.range.start.line + 1,
          condition: bp.condition,
          logMessage: bp.logMessage,
        }));
      try {
        const result = await resolved.session.customRequest('setBreakpoints', {
          source: { path: uri.fsPath },
          breakpoints: allBps,
        });
        const adapterBreakpoints: Array<Record<string, unknown>> = Array.isArray(result?.breakpoints)
          ? result.breakpoints
          : [];
        adapterBreakpoints.forEach((bp: Record<string, unknown>, index: number) => {
          const line = typeof bp?.line === 'number' ? bp.line : allBps[index]?.line;
          if (typeof line !== 'number') {
            return;
          }
          const message = typeof bp?.message === 'string' ? bp.message : undefined;
          const record = toBreakpointVerificationRecord(bp?.verified, message);
          if (record) {
            resolved.journal.updateBreakpointVerification(uri.fsPath, line, record);
          }
        });
      } catch {
        // Session may not be paused or adapter may be unavailable; ignore.
      }
    }

    return jsonResult({
      action: 'add',
      file: uri.fsPath,
      lines,
      count: newBps.length,
      condition: condition ?? null,
      logMessage: logMessage ?? null,
    });
  }

  private _removeBreakpoints(
    sessionId: string | undefined,
    uri: vscode.Uri,
    lines: number[],
  ): vscode.LanguageModelToolResult {
    const uriStr = uri.toString();
    const lineSet = new Set(lines.map(line => line - 1));
    const toRemove = vscode.debug.breakpoints.filter((bp): bp is vscode.SourceBreakpoint => {
      if (!(bp instanceof vscode.SourceBreakpoint)) return false;
      return (
        bp.location.uri.toString() === uriStr &&
        (lines.length === 0 || lineSet.has(bp.location.range.start.line))
      );
    });

    if (toRemove.length > 0) {
      vscode.debug.removeBreakpoints(toRemove);
    }

    const resolved = resolveSession(this.registry, sessionId);
    if (resolved) {
      if (lines.length === 0) {
        resolved.journal.clearBreakpointVerifications(uri.fsPath);
      } else {
        for (const line of lines) {
          resolved.journal.deleteBreakpointVerification(uri.fsPath, line);
        }
      }
    }

    return jsonResult({
      action: 'remove',
      file: uri.fsPath,
      lines,
      removed: toRemove.length,
    });
  }

  private _clearBreakpoints(
    sessionId: string | undefined,
    uri: vscode.Uri,
  ): vscode.LanguageModelToolResult {
    const uriStr = uri.toString();
    const toRemove = vscode.debug.breakpoints.filter((bp): bp is vscode.SourceBreakpoint =>
      bp instanceof vscode.SourceBreakpoint && bp.location.uri.toString() === uriStr,
    );

    if (toRemove.length > 0) {
      vscode.debug.removeBreakpoints(toRemove);
    }

    const resolved = resolveSession(this.registry, sessionId);
    resolved?.journal.clearBreakpointVerifications(uri.fsPath);

    return jsonResult({
      action: 'clear',
      file: uri.fsPath,
      removed: toRemove.length,
    });
  }
}
