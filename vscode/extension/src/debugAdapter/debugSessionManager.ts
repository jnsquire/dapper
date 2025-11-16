import * as vscode from 'vscode';

export class DebugSessionManager implements vscode.Disposable {
  private sessions = new Map<string, vscode.DebugSession>();
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
      console.log(`Debug session started: ${session.id}`);
    }
  }

  private onDidTerminateDebugSession(session: vscode.DebugSession): void {
    if (session.type === 'dapper') {
      this.sessions.delete(session.id);
      console.log(`Debug session terminated: ${session.id}`);
    }
  }

  private onDidReceiveCustomEvent(e: vscode.DebugSessionCustomEvent): void {
    if (e.session.type === 'dapper') {
      console.log(`Custom event received: ${e.event}`, e.body);
      // Handle custom events from the debug adapter
    }
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
      console.error('Failed to start debugging session:', error);
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
  }
}
