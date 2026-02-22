import * as vscode from 'vscode';

export class DebugSessionManager implements vscode.Disposable {
  private sessions = new Map<string, vscode.DebugSession>();
  private _stoppedSessions = new Set<string>();
  private disposables: vscode.Disposable[] = [];

  constructor() {
    this.disposables = [
      vscode.debug.onDidStartDebugSession(this.onDidStartDebugSession, this),
      vscode.debug.onDidTerminateDebugSession(this.onDidTerminateDebugSession, this),
      vscode.debug.onDidReceiveDebugSessionCustomEvent(this.onDidReceiveCustomEvent, this)
    ];
  }

  private onDidStartDebugSession(session: vscode.DebugSession): void {
    if (session.type === 'dapper') {
      this.sessions.set(session.id, session);
    }
  }

  private onDidTerminateDebugSession(session: vscode.DebugSession): void {
    if (session.type === 'dapper') {
      this.sessions.delete(session.id);
      this._stoppedSessions.delete(session.id);
    }
  }

  private onDidReceiveCustomEvent(e: vscode.DebugSessionCustomEvent): void {
    if (e.session.type !== 'dapper') {
      return;
    }

    if (e.event === 'stopped') {
      this._stoppedSessions.add(e.session.id);
    } else if (e.event === 'continued' || e.event === 'terminated') {
      this._stoppedSessions.delete(e.session.id);
    } else if (e.event === 'dapper/hotReloadResult') {
      const warnings: unknown[] = Array.isArray(e.body?.warnings) ? e.body.warnings : [];
      if (warnings.length > 0) {
        const message = `Dapper hot reload warnings: ${warnings.map(String).join('; ')}`;
        vscode.window.showWarningMessage(message);
      }
    }
  }

  public isSessionStopped(sessionId: string): boolean {
    return this._stoppedSessions.has(sessionId);
  }

  public async startDebugging(
    name: string,
    config: vscode.DebugConfiguration
  ): Promise<boolean> {
    try {
      return await vscode.debug.startDebugging(undefined, {
        ...config,
        name,
        type: 'dapper',
        request: 'launch',
      });
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      vscode.window.showErrorMessage(`Failed to start debugging: ${errorMessage}`);
      return false;
    }
  }

  public getSession(sessionId: string): vscode.DebugSession | undefined {
    return this.sessions.get(sessionId);
  }

  public dispose() {
    this.disposables.forEach(d => d.dispose());
    this.sessions.clear();
    this._stoppedSessions.clear();
  }
}
