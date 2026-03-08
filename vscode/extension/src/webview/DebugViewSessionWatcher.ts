import * as vscode from 'vscode';
import type { StackFrame, ThreadInfo } from './debugViewProtocol.js';

export class DebugViewSessionWatcher implements vscode.Disposable {
  private readonly _panel: vscode.WebviewPanel;
  private readonly _disposables: vscode.Disposable[] = [];

  constructor(panel: vscode.WebviewPanel) {
    this._panel = panel;
    // dispose this watcher when the panel is closed to avoid leaks
    panel.onDidDispose(() => this.dispose(), null, this._disposables);
    this._registerListeners();
  }

  private _registerListeners(): void {
    // 1. Session start
    this._disposables.push(
      vscode.debug.onDidStartDebugSession(() => {
        this._post({ command: 'sessionState', state: 'running' });
        this._refreshThreads();
      })
    );

    // 2. Session end
    this._disposables.push(
      vscode.debug.onDidTerminateDebugSession(() => {
        this._post({ command: 'clearStack' });
        this._post({ command: 'sessionState', state: 'stopped' });
      })
    );

    // 3. Active stack item changed (user selected a thread/frame, or a breakpoint was hit)
    this._disposables.push(
      vscode.debug.onDidChangeActiveStackItem(async (stackItem) => {
        if (!stackItem) return;
        // stackItem is vscode.StackFrame | vscode.Thread
        const session = vscode.debug.activeDebugSession;
        if (!session) return;
        this._post({ command: 'sessionState', state: 'paused' });
        await this._fetchStack(session);
        await this._refreshThreads(session);
      })
    );
  }

  /** Fetch the stack trace for the active thread and push it to the webview. */
  private async _fetchStack(session: vscode.DebugSession): Promise<void> {
    try {
      // Get the current thread ID from the active stack item
      const activeItem = vscode.debug.activeStackItem;
      // activeItem could be a StackFrame or Thread; neither has a common
      // typed property for the thread ID so we use type assertions here.
      const threadId =
        activeItem && 'threadId' in activeItem
          ? (activeItem as any).threadId
          : activeItem && 'id' in activeItem
            ? (activeItem as any).id
            : undefined;
      if (threadId === undefined) return;

      const response = await session.customRequest('stackTrace', {
        threadId,
        startFrame: 0,
        levels: 50,
      });

      const rawFrames: any[] = response?.stackFrames ?? [];
      const frames: StackFrame[] = this._mapFrames(rawFrames);

      this._post({ command: 'stackTrace', frames });
    } catch (e) {
      // session may have ended; log for debugging
      console.error('Error fetching stack trace', e);
    }
  }

  /** Fetch current threads and push them to the webview. */
  private async _refreshThreads(session?: vscode.DebugSession): Promise<void> {
    const s = session ?? vscode.debug.activeDebugSession;
    if (!s) return;
    try {
      const response = await s.customRequest('threads', {});
      const rawThreads: any[] = response?.threads ?? [];
      const threads: ThreadInfo[] = rawThreads.map((t: any) => ({
        id: t.id,
        name: t.name ?? `Thread ${t.id}`,
        state: 'paused', // debug adapter doesn't currently report per‑thread state
      }));
      this._post({ command: 'threads', threads });
    } catch (e) {
      console.error('Error refreshing thread list', e);
    }
  }

  /** Handle a selectThread command from the webview. Fetches the stack for that thread. */
  /**
   * Handle a selectThread command from the webview. Fetches and posts a stack trace
   * for the requested thread. Public because it's invoked by the webview host.
   */
  public async handleSelectThread(threadId: number): Promise<void> {
    const session = vscode.debug.activeDebugSession;
    if (!session) return;
    try {
      const response = await session.customRequest('stackTrace', {
        threadId,
        startFrame: 0,
        levels: 50,
      });
      const rawFrames: any[] = response?.stackFrames ?? [];
      const frames: StackFrame[] = this._mapFrames(rawFrames);
      this._post({ command: 'stackTrace', frames });
    } catch (e) {
      console.error('Error fetching stack for selected thread', e);
    }
  }

  /** Handle an expandFrame / selectFrame request from the webview — fetches variables. */
  /**
   * Called by the webview when a frame is expanded/selected. Retrieves all
   * variables visible in that frame and sends them to the webview.
   */
  public async handleFetchVariables(frameId: number): Promise<void> {
    const session = vscode.debug.activeDebugSession;
    if (!session) return;
    try {
      const scopesResp = await session.customRequest('scopes', { frameId });
      const scopes: any[] = scopesResp?.scopes ?? [];
      const allVars: import('./debugViewProtocol.js').Variable[] = [];
      for (const scope of scopes) {
        const varsResp = await session.customRequest('variables', {
          variablesReference: scope.variablesReference,
        });
        const vars: any[] = varsResp?.variables ?? [];
        for (const v of vars) {
          allVars.push({
            name: v.name,
            value: v.value ?? '',
            type: v.type,
            hasChildren: (v.variablesReference ?? 0) > 0,
            variablesReference: v.variablesReference ?? 0,
          });
        }
      }
      this._panel.webview.postMessage({ command: 'variables', frameId, variables: allVars });
    } catch (e) {
      console.error('Error fetching variables for frame', e);
    }
  }

  private _post(message: any): void {
    try {
      this._panel.webview.postMessage(message);
    } catch (e) {
      // Panel may have been disposed
      console.error('Failed to post message to webview', e);
    }
  }

  dispose(): void {
    this._disposables.forEach(d => d.dispose());
    this._disposables.length = 0;
  }

  /**
   * Map raw stack frames returned by the debug adapter into our protocol type.
   */
  private _mapFrames(rawFrames: any[]): StackFrame[] {
    return rawFrames.map((f: any) => ({
      id: f.id,
      name: f.name ?? '<unknown>',
      source: f.source?.path ?? f.source?.name ?? '<unknown>',
      line: f.line ?? 0,
      column: f.column ?? 0,
      isOptimized: f.presentationHint === 'subtle',
      isSynthetic: typeof f.source?.path === 'string' && /^<.*>$/.test(f.source.path),
      isCython: typeof f.source?.path === 'string' && f.source.path.endsWith('.pyx'),
    }));
  }
}
