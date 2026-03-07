import * as vscode from 'vscode';

const TRACKED_PID_STATE_KEY = 'dapper.processTree.trackedPids';

interface ProcessSessionNode {
  session: vscode.DebugSession;
  parentSessionId?: string;
  processName?: string;
  pid?: number;
  startMethod?: string;
}

type ProcessTreeElement = SessionTreeElement | TrackedPidTreeElement;

interface SessionTreeElement {
  kind: 'session';
  sessionId: string;
}

interface TrackedPidTreeElement {
  kind: 'trackedPid';
  pid: number;
}

interface ProcessTreeState {
  sessionCount: number;
  trackedPidCount: number;
}

export class DapperProcessTreeProvider implements vscode.TreeDataProvider<ProcessTreeElement>, vscode.Disposable {
  private readonly _nodes = new Map<string, ProcessSessionNode>();
  private readonly _trackedPids = new Set<number>();
  private readonly _state: vscode.Memento | undefined;
  private readonly _onDidChangeTreeData = new vscode.EventEmitter<ProcessTreeElement | undefined | void>();
  private readonly _disposables: vscode.Disposable[] = [];

  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  constructor(state?: vscode.Memento) {
    this._state = state;
    for (const pid of this._loadTrackedPids()) {
      this._trackedPids.add(pid);
    }

    const activeSession = vscode.debug.activeDebugSession;
    if (activeSession?.type === 'dapper') {
      this._upsertSession(activeSession);
    }

    this._disposables.push(
      vscode.debug.onDidStartDebugSession((session) => {
        if (session.type !== 'dapper') {
          return;
        }
        this._upsertSession(session);
      }),
      vscode.debug.onDidTerminateDebugSession((session) => {
        if (session.type !== 'dapper') {
          return;
        }
        this._removeSession(session.id);
      }),
      vscode.debug.onDidReceiveDebugSessionCustomEvent((event) => {
        if (event.session.type !== 'dapper') {
          return;
        }

        if (event.event === 'process') {
          this._updateProcessEvent(event.session, event.body ?? {});
        }
      }),
    );
  }

  get state(): ProcessTreeState {
    return {
      sessionCount: this._nodes.size,
      trackedPidCount: this._trackedPids.size,
    };
  }

  refresh(): void {
    this._onDidChangeTreeData.fire();
  }

  async addTrackedPid(pid: number): Promise<boolean> {
    if (!Number.isInteger(pid) || pid <= 0 || this._trackedPids.has(pid)) {
      return false;
    }

    this._trackedPids.add(pid);
    await this._persistTrackedPids();
    this._onDidChangeTreeData.fire();
    return true;
  }

  async removeTrackedPid(pid: number): Promise<boolean> {
    if (!this._trackedPids.delete(pid)) {
      return false;
    }

    await this._persistTrackedPids();
    this._onDidChangeTreeData.fire();
    return true;
  }

  getPidForElement(element: ProcessTreeElement): number | undefined {
    if (element.kind === 'trackedPid') {
      return element.pid;
    }

    return this._nodes.get(element.sessionId)?.pid;
  }

  getSessionForElement(element: ProcessTreeElement): vscode.DebugSession | undefined {
    if (element.kind !== 'session') {
      return undefined;
    }

    return this._nodes.get(element.sessionId)?.session;
  }

  getTreeItem(element: ProcessTreeElement): vscode.TreeItem {
    if (element.kind === 'trackedPid') {
      return this._getTrackedPidTreeItem(element.pid);
    }

    const node = this._nodes.get(element.sessionId);
    if (!node) {
      return new vscode.TreeItem(element.sessionId, vscode.TreeItemCollapsibleState.None);
    }

    const hasChildren = this._getChildIds(element.sessionId).length > 0;
    const label = node.processName || node.session.name || 'Dapper Session';
    const item = new vscode.TreeItem(
      label,
      hasChildren ? vscode.TreeItemCollapsibleState.Expanded : vscode.TreeItemCollapsibleState.None,
    );

    const descriptionParts: string[] = [];
    if (node.processName && node.session.name && node.processName !== node.session.name) {
      descriptionParts.push(node.session.name);
    }
    if (node.pid != null) {
      descriptionParts.push(`pid ${node.pid}`);
      if (this._trackedPids.has(node.pid)) {
        descriptionParts.push('tracked');
      }
    }
    item.description = descriptionParts.length > 0 ? descriptionParts.join(' • ') : undefined;

    const tooltipParts = [
      node.session.name ? `Session: ${node.session.name}` : undefined,
      node.processName ? `Process: ${node.processName}` : undefined,
      node.pid != null ? `PID: ${node.pid}` : undefined,
      node.startMethod ? `Start: ${node.startMethod}` : undefined,
      `Debug session: ${node.session.id}`,
      node.parentSessionId ? `Parent session: ${node.parentSessionId}` : undefined,
    ].filter((value): value is string => Boolean(value));
    item.tooltip = tooltipParts.join('\n');
    item.contextValue = 'dapperProcessSession';
    item.iconPath = new vscode.ThemeIcon('debug-alt');
    return item;
  }

  getChildren(element?: ProcessTreeElement): ProcessTreeElement[] {
    if (element?.kind === 'trackedPid') {
      return [];
    }

    if (element?.kind === 'session') {
      return this._getChildIds(element.sessionId).map((sessionId) => ({ kind: 'session', sessionId }));
    }

    return [
      ...this._getRootIds().map((sessionId) => ({ kind: 'session', sessionId }) satisfies SessionTreeElement),
      ...this._getTrackedPidElements(),
    ];
  }

  getParent(element: ProcessTreeElement): ProcessTreeElement | undefined {
    if (element.kind !== 'session') {
      return undefined;
    }

    const node = this._nodes.get(element.sessionId);
    if (!node?.parentSessionId || !this._nodes.has(node.parentSessionId)) {
      return undefined;
    }
    return { kind: 'session', sessionId: node.parentSessionId };
  }

  dispose(): void {
    this._onDidChangeTreeData.dispose();
    for (const disposable of this._disposables) {
      disposable.dispose();
    }
    this._disposables.length = 0;
    this._nodes.clear();
    this._trackedPids.clear();
  }

  private _getTrackedPidTreeItem(pid: number): vscode.TreeItem {
    const attachedNode = this._findSessionByPid(pid);
    const item = new vscode.TreeItem(`Tracked PID ${pid}`, vscode.TreeItemCollapsibleState.None);
    item.description = attachedNode
      ? `${attachedNode.processName || attachedNode.session.name || attachedNode.session.id} • attached`
      : 'manual target';
    item.tooltip = attachedNode
      ? `Tracked PID: ${pid}\nAttached session: ${attachedNode.session.id}`
      : `Tracked PID: ${pid}\nManual process target for future debug controls`;
    item.contextValue = attachedNode ? 'dapperTrackedPidAttached' : 'dapperTrackedPid';
    item.iconPath = new vscode.ThemeIcon(attachedNode ? 'debug-disconnect' : 'pin');
    return item;
  }

  private _upsertSession(session: vscode.DebugSession): void {
    const existing = this._nodes.get(session.id);
    const parentSessionId = this._resolveParentSessionId(session);
    this._nodes.set(session.id, {
      session,
      parentSessionId,
      processName: existing?.processName,
      pid: existing?.pid,
      startMethod: existing?.startMethod,
    });
    this._onDidChangeTreeData.fire();
  }

  private _removeSession(sessionId: string): void {
    if (!this._nodes.delete(sessionId)) {
      return;
    }

    for (const node of this._nodes.values()) {
      if (node.parentSessionId === sessionId) {
        node.parentSessionId = undefined;
      }
    }
    this._onDidChangeTreeData.fire();
  }

  private _updateProcessEvent(session: vscode.DebugSession, body: Record<string, unknown>): void {
    const existing = this._nodes.get(session.id);
    if (!existing) {
      this._upsertSession(session);
    }

    const node = this._nodes.get(session.id);
    if (!node) {
      return;
    }

    node.processName = typeof body.name === 'string' && body.name.length > 0 ? body.name : node.processName;
    node.pid = typeof body.systemProcessId === 'number' ? body.systemProcessId : node.pid;
    node.startMethod = typeof body.startMethod === 'string' ? body.startMethod : node.startMethod;
    this._onDidChangeTreeData.fire({ kind: 'session', sessionId: session.id });
    if (node.pid != null && this._trackedPids.has(node.pid)) {
      this._onDidChangeTreeData.fire({ kind: 'trackedPid', pid: node.pid });
    }
  }

  private _resolveParentSessionId(session: vscode.DebugSession): string | undefined {
    if (session.parentSession?.id) {
      return session.parentSession.id;
    }

    const configuration = session.configuration as Record<string, unknown>;
    return typeof configuration.__dapperParentDebugSessionId === 'string'
      ? configuration.__dapperParentDebugSessionId
      : undefined;
  }

  private _getRootIds(): string[] {
    return [...this._nodes.entries()]
      .filter(([, node]) => !node.parentSessionId || !this._nodes.has(node.parentSessionId))
      .sort((left, right) => this._compareNodes(left[1], right[1]))
      .map(([sessionId]) => sessionId);
  }

  private _getChildIds(parentSessionId: string): string[] {
    return [...this._nodes.entries()]
      .filter(([, node]) => node.parentSessionId === parentSessionId)
      .sort((left, right) => this._compareNodes(left[1], right[1]))
      .map(([sessionId]) => sessionId);
  }

  private _getTrackedPidElements(): TrackedPidTreeElement[] {
    return [...this._trackedPids]
      .sort((left, right) => left - right)
      .map((pid) => ({ kind: 'trackedPid', pid }));
  }

  private _findSessionByPid(pid: number): ProcessSessionNode | undefined {
    for (const node of this._nodes.values()) {
      if (node.pid === pid) {
        return node;
      }
    }
    return undefined;
  }

  private _compareNodes(left: ProcessSessionNode, right: ProcessSessionNode): number {
    const leftLabel = (left.processName || left.session.name || left.session.id).toLocaleLowerCase();
    const rightLabel = (right.processName || right.session.name || right.session.id).toLocaleLowerCase();
    return leftLabel.localeCompare(rightLabel);
  }

  private _loadTrackedPids(): number[] {
    const raw = this._state?.get<unknown>(TRACKED_PID_STATE_KEY);
    if (!Array.isArray(raw)) {
      return [];
    }

    return raw
      .map((value) => (typeof value === 'number' ? value : Number.NaN))
      .filter((value) => Number.isInteger(value) && value > 0);
  }

  private async _persistTrackedPids(): Promise<void> {
    await this._state?.update(TRACKED_PID_STATE_KEY, [...this._trackedPids].sort((left, right) => left - right));
  }
}

export class DapperProcessTreeView implements vscode.Disposable {
  private readonly _provider: DapperProcessTreeProvider;
  private readonly _treeView: vscode.TreeView<ProcessTreeElement>;
  private readonly _disposables: vscode.Disposable[] = [];

  constructor(state?: vscode.Memento) {
    this._provider = new DapperProcessTreeProvider(state);
    this._treeView = vscode.window.createTreeView('dapperProcessTree', {
      treeDataProvider: this._provider,
      showCollapseAll: true,
    });

    this._treeView.title = 'Dapper Processes';
    this._treeView.description = 'Sessions and tracked PIDs';
    this._updateViewState();

    this._disposables.push(
      this._provider,
      this._treeView,
      this._provider.onDidChangeTreeData(() => {
        this._updateViewState();
      }),
    );
  }

  refresh(): void {
    this._provider.refresh();
    this._updateViewState();
  }

  async addTrackedPid(): Promise<void> {
    const input = await vscode.window.showInputBox({
      prompt: 'Add a PID to keep visible in the Dapper process tree',
      placeHolder: '12345',
      validateInput: (value) => {
        const trimmed = value.trim();
        const pid = Number(trimmed);
        if (!trimmed) {
          return 'Enter a PID.';
        }
        if (!Number.isInteger(pid) || pid <= 0) {
          return 'PID must be a positive integer.';
        }
        return undefined;
      },
    });
    if (!input) {
      return;
    }

    const pid = Number(input.trim());
    const added = await this._provider.addTrackedPid(pid);
    if (!added) {
      vscode.window.showInformationMessage(`PID ${pid} is already tracked.`);
      return;
    }

    this._updateViewState();
    void this._treeView.reveal({ kind: 'trackedPid', pid }, { select: true, focus: false });
  }

  async removeTrackedPid(element: ProcessTreeElement): Promise<void> {
    const pid = this._provider.getPidForElement(element);
    if (pid == null) {
      return;
    }

    await this._provider.removeTrackedPid(pid);
    this._updateViewState();
  }

  async copyPid(element: ProcessTreeElement): Promise<void> {
    const pid = this._provider.getPidForElement(element);
    if (pid == null) {
      vscode.window.showInformationMessage('No PID is available for the selected item yet.');
      return;
    }

    await vscode.env.clipboard.writeText(String(pid));
    vscode.window.showInformationMessage(`Copied PID ${pid}.`);
  }

  async stopSession(element: ProcessTreeElement): Promise<void> {
    const session = this._provider.getSessionForElement(element);
    if (!session) {
      return;
    }

    await vscode.debug.stopDebugging(session);
  }

  dispose(): void {
    for (const disposable of this._disposables) {
      disposable.dispose();
    }
    this._disposables.length = 0;
  }

  private _updateViewState(): void {
    const { sessionCount, trackedPidCount } = this._provider.state;
    this._treeView.message = sessionCount === 0 && trackedPidCount === 0
      ? 'No active Dapper sessions or tracked PIDs.'
      : undefined;
    this._treeView.badge = sessionCount > 0 || trackedPidCount > 0
      ? {
          value: sessionCount + trackedPidCount,
          tooltip: `${sessionCount} session${sessionCount === 1 ? '' : 's'}, ${trackedPidCount} tracked PID${trackedPidCount === 1 ? '' : 's'}`,
        }
      : undefined;
  }
}

export type { ProcessTreeElement };