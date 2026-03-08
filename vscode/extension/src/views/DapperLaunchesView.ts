import * as vscode from 'vscode';
import { basename } from 'path';

const DEBUGGER_LOG_LEVELS = ['TRACE', 'DEBUG', 'INFO', 'WARNING', 'ERROR'] as const;
type DebuggerLogLevel = typeof DEBUGGER_LOG_LEVELS[number];

export interface LaunchRecord {
  launchToken: string;
  sessionName: string;
  targetLabel: string;
  noDebug: boolean;
  startedAt: number;
  endedAt?: number;
  sessionId?: string;
  processName?: string;
  pid?: number;
  startMethod?: string;
  exitCode?: number;
  logFile?: string;
  error?: string;
  status: 'launching' | 'running' | 'exited' | 'terminated' | 'failed';
}

export interface LaunchRegistration {
  launchToken: string;
  sessionName: string;
  targetLabel: string;
  noDebug: boolean;
}

interface LaunchTreeElement {
  kind: 'launch';
  launchToken: string;
}

export class DapperLaunchHistoryService implements vscode.Disposable {
  private readonly _records = new Map<string, LaunchRecord>();
  private readonly _launchTokenBySessionId = new Map<string, string>();
  private readonly _terminalsByLaunchToken = new Map<string, vscode.Terminal>();
  private readonly _onDidChange = new vscode.EventEmitter<void>();
  private readonly _disposables: vscode.Disposable[] = [];

  public readonly onDidChange = this._onDidChange.event;

  public constructor() {
    this._disposables.push(
      vscode.debug.onDidStartDebugSession((session) => {
        if (session.type !== 'dapper') {
          return;
        }
        const launchToken = this._getLaunchToken(session.configuration);
        if (!launchToken) {
          return;
        }
        this.attachSession(launchToken, session);
      }),
      vscode.debug.onDidTerminateDebugSession((session) => {
        if (session.type !== 'dapper') {
          return;
        }
        this.markSessionTerminated(session.id);
      }),
      vscode.debug.onDidReceiveDebugSessionCustomEvent((event) => {
        if (event.session.type !== 'dapper') {
          return;
        }
        if (event.event === 'process') {
          this.updateProcess(event.session.id, event.body ?? {});
        } else if (event.event === 'exited') {
          const exitCode = typeof event.body?.exitCode === 'number' ? event.body.exitCode : undefined;
          this.markSessionExited(event.session.id, exitCode);
        }
      }),
    );
  }

  public get records(): LaunchRecord[] {
    return [...this._records.values()].sort((left, right) => right.startedAt - left.startedAt);
  }

  public beginLaunch(registration: LaunchRegistration): void {
    this._records.set(registration.launchToken, {
      launchToken: registration.launchToken,
      sessionName: registration.sessionName,
      targetLabel: registration.targetLabel,
      noDebug: registration.noDebug,
      startedAt: Date.now(),
      status: 'launching',
    });
    this._onDidChange.fire();
  }

  public markLaunchStarted(launchToken: string): void {
    const record = this._records.get(launchToken);
    if (!record) {
      return;
    }
    if (record.status === 'launching') {
      record.status = 'running';
      this._onDidChange.fire();
    }
  }

  public markLaunchFailed(launchToken: string, error: string): void {
    const record = this._records.get(launchToken);
    if (!record) {
      return;
    }
    record.status = 'failed';
    record.error = error;
    record.endedAt = Date.now();
    this._onDidChange.fire();
  }

  public attachSession(launchToken: string, session: vscode.DebugSession): void {
    const record = this._records.get(launchToken);
    if (!record) {
      return;
    }
    record.sessionId = session.id;
    record.sessionName = session.name || record.sessionName;
    record.status = 'running';
    this._launchTokenBySessionId.set(session.id, launchToken);
    this._onDidChange.fire();
  }

  public updateLogFile(launchToken: string, logFile: string): void {
    const record = this._records.get(launchToken);
    if (!record) {
      return;
    }
    record.logFile = logFile;
    this._onDidChange.fire();
  }

  public updateProcess(sessionId: string, body: Record<string, unknown>): void {
    const record = this._getRecordBySessionId(sessionId);
    if (!record) {
      return;
    }
    record.processName = typeof body.name === 'string' && body.name.length > 0 ? body.name : record.processName;
    record.pid = typeof body.systemProcessId === 'number' ? body.systemProcessId : record.pid;
    record.startMethod = typeof body.startMethod === 'string' ? body.startMethod : record.startMethod;
    this._onDidChange.fire();
  }

  public updateProcessForLaunch(launchToken: string, body: Record<string, unknown>): void {
    const record = this._records.get(launchToken);
    if (!record) {
      return;
    }
    record.processName = typeof body.name === 'string' && body.name.length > 0 ? body.name : record.processName;
    record.pid = typeof body.systemProcessId === 'number' ? body.systemProcessId : record.pid;
    record.startMethod = typeof body.startMethod === 'string' ? body.startMethod : record.startMethod;
    this._onDidChange.fire();
  }

  public markSessionExited(sessionId: string, exitCode?: number): void {
    const record = this._getRecordBySessionId(sessionId);
    if (!record) {
      return;
    }
    record.status = 'exited';
    record.exitCode = exitCode;
    record.endedAt = Date.now();
    this._onDidChange.fire();
  }

  public markLaunchExited(launchToken: string, exitCode?: number): void {
    const record = this._records.get(launchToken);
    if (!record) {
      return;
    }
    record.status = 'exited';
    record.exitCode = exitCode;
    record.endedAt = Date.now();
    this._onDidChange.fire();
  }

  public markSessionTerminated(sessionId: string): void {
    const record = this._getRecordBySessionId(sessionId);
    if (!record) {
      return;
    }
    if (record.status === 'exited' || record.status === 'failed') {
      return;
    }
    record.status = 'terminated';
    record.endedAt = Date.now();
    this._onDidChange.fire();
  }

  public markTerminalExited(launchToken: string, exitCode?: number): void {
    const record = this._records.get(launchToken);
    if (!record) {
      return;
    }
    record.status = 'exited';
    record.exitCode = exitCode;
    record.endedAt = Date.now();
    this._onDidChange.fire();
  }

  public getLogFile(launchToken: string): string | undefined {
    return this._records.get(launchToken)?.logFile;
  }

  public attachTerminal(launchToken: string, terminal: vscode.Terminal): void {
    if (!this._records.has(launchToken)) {
      return;
    }
    this._terminalsByLaunchToken.set(launchToken, terminal);
    this._onDidChange.fire();
  }

  public detachTerminal(launchToken: string): void {
    if (!this._terminalsByLaunchToken.delete(launchToken)) {
      return;
    }
    this._onDidChange.fire();
  }

  public focusTerminal(launchToken: string): boolean {
    const terminal = this._terminalsByLaunchToken.get(launchToken);
    if (!terminal) {
      return false;
    }
    terminal.show(false);
    return true;
  }

  public hasTerminal(launchToken: string): boolean {
    return this._terminalsByLaunchToken.has(launchToken);
  }

  public deleteLaunch(launchToken: string): boolean {
    const record = this._records.get(launchToken);
    if (!record) {
      return false;
    }
    if (record.sessionId) {
      this._launchTokenBySessionId.delete(record.sessionId);
    }
    this._terminalsByLaunchToken.delete(launchToken);
    this._records.delete(launchToken);
    this._onDidChange.fire();
    return true;
  }

  public clear(): void {
    if (this._records.size === 0) {
      return;
    }
    this._records.clear();
    this._launchTokenBySessionId.clear();
    this._terminalsByLaunchToken.clear();
    this._onDidChange.fire();
  }

  public dispose(): void {
    this._onDidChange.dispose();
    for (const disposable of this._disposables) {
      disposable.dispose();
    }
    this._disposables.length = 0;
    this._records.clear();
    this._launchTokenBySessionId.clear();
    this._terminalsByLaunchToken.clear();
  }

  private _getRecordBySessionId(sessionId: string): LaunchRecord | undefined {
    const launchToken = this._launchTokenBySessionId.get(sessionId);
    return launchToken ? this._records.get(launchToken) : undefined;
  }

  private _getLaunchToken(configuration: vscode.DebugConfiguration): string | undefined {
    const candidate = configuration as Record<string, unknown>;
    return typeof candidate.__dapperLaunchToken === 'string' ? candidate.__dapperLaunchToken : undefined;
  }
}

class DapperLaunchesProvider implements vscode.TreeDataProvider<LaunchTreeElement> {
  private readonly _onDidChangeTreeData = new vscode.EventEmitter<LaunchTreeElement | undefined | void>();

  public readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  public constructor(private readonly _history: DapperLaunchHistoryService) {
    this._history.onDidChange(() => {
      this._onDidChangeTreeData.fire();
    });
  }

  public refresh(): void {
    this._onDidChangeTreeData.fire();
  }

  public getTreeItem(element: LaunchTreeElement): vscode.TreeItem {
    const record = this._history.records.find((entry) => entry.launchToken === element.launchToken);
    if (!record) {
      return new vscode.TreeItem(element.launchToken, vscode.TreeItemCollapsibleState.None);
    }

    const label = record.processName || record.sessionName;
    const item = new vscode.TreeItem(label, vscode.TreeItemCollapsibleState.None);
    item.description = this._describe(record);
    item.tooltip = this._tooltip(record);
    item.iconPath = new vscode.ThemeIcon(this._icon(record));
    item.contextValue = this._contextValue(record);
    return item;
  }

  public getChildren(element?: LaunchTreeElement): LaunchTreeElement[] {
    if (element) {
      return [];
    }
    return this._history.records.map((record) => ({ kind: 'launch', launchToken: record.launchToken }));
  }

  private _describe(record: LaunchRecord): string {
    const parts = [record.noDebug ? 'run' : 'debug', record.status];
    if (record.pid != null) {
      parts.push(`pid ${record.pid}`);
    }
    if (record.status === 'exited' && record.exitCode != null) {
      parts.push(`exit ${record.exitCode}`);
    }
    return parts.join(' • ');
  }

  private _tooltip(record: LaunchRecord): string {
    return [
      `Target: ${record.targetLabel}`,
      `Mode: ${record.noDebug ? 'Run' : 'Debug'}`,
      `Status: ${record.status}`,
      record.pid != null ? `PID: ${record.pid}` : undefined,
      record.startMethod ? `Start: ${record.startMethod}` : undefined,
      record.exitCode != null ? `Exit code: ${record.exitCode}` : undefined,
      record.logFile ? `Log name: ${basename(record.logFile)}` : undefined,
      record.logFile ? `Log file: ${record.logFile}` : undefined,
      record.error ? `Error: ${record.error}` : undefined,
    ].filter((value): value is string => Boolean(value)).join('\n');
  }

  private _icon(record: LaunchRecord): string {
    switch (record.status) {
      case 'launching':
        return 'sync';
      case 'running':
        return record.noDebug ? 'play' : 'debug-alt';
      case 'exited':
        return record.exitCode && record.exitCode !== 0 ? 'error' : 'pass';
      case 'failed':
        return 'error';
      case 'terminated':
        return 'debug-stop';
    }
  }

  private _contextValue(record: LaunchRecord): string {
    const parts = ['dapperLaunchRecord'];
    if (record.logFile) {
      parts.push('withLog');
    }
    if (this._history.hasTerminal(record.launchToken)) {
      parts.push('withTerminal');
    }
    return parts.join(' ');
  }
}

export class DapperLaunchesView implements vscode.Disposable {
  private readonly _provider: DapperLaunchesProvider;
  private readonly _treeView: vscode.TreeView<LaunchTreeElement>;
  private readonly _disposables: vscode.Disposable[] = [];

  public constructor(private readonly _history: DapperLaunchHistoryService) {
    this._provider = new DapperLaunchesProvider(_history);
    this._treeView = vscode.window.createTreeView('dapperLaunches', {
      treeDataProvider: this._provider,
      showCollapseAll: false,
    });
    this._treeView.title = 'Dapper Launches';
    this._treeView.description = 'Recent runs and debug launches';
    this._updateViewState();

    this._disposables.push(
      this._treeView,
      this._history,
      vscode.workspace.onDidChangeConfiguration((event) => {
        if (event.affectsConfiguration('dapper.debugger.logLevel')) {
          this._updateViewState();
        }
      }),
      this._history.onDidChange(() => {
        this._updateViewState();
      }),
    );
  }

  public refresh(): void {
    this._provider.refresh();
    this._updateViewState();
  }

  public async openLog(element?: LaunchTreeElement): Promise<void> {
    if (!element) {
      vscode.window.showInformationMessage('Select a launch record first.');
      return;
    }
    const logFile = this._history.getLogFile(element.launchToken);
    if (!logFile) {
      vscode.window.showInformationMessage('No log file is available for this launch.');
      return;
    }

    const document = await vscode.workspace.openTextDocument(vscode.Uri.file(logFile));
    await vscode.window.showTextDocument(document);
  }

  public deleteLaunch(element?: LaunchTreeElement): void {
    if (!element) {
      vscode.window.showInformationMessage('Select a launch record first.');
      return;
    }
    if (!this._history.deleteLaunch(element.launchToken)) {
      vscode.window.showInformationMessage('That launch record is no longer available.');
      return;
    }
    this._provider.refresh();
    this._updateViewState();
  }

  public focusTerminal(element?: LaunchTreeElement): void {
    if (!element) {
      vscode.window.showInformationMessage('Select a launch record first.');
      return;
    }
    if (!this._history.focusTerminal(element.launchToken)) {
      vscode.window.showInformationMessage('No active terminal is associated with this launch.');
    }
  }

  public clearHistory(): void {
    this._history.clear();
    this._provider.refresh();
    this._updateViewState();
  }

  public async selectLogLevel(): Promise<void> {
    const debuggerConfig = vscode.workspace.getConfiguration('dapper.debugger');
    const currentLevel = this._getCurrentLogLevel(debuggerConfig);
    const picked = await vscode.window.showQuickPick(
      DEBUGGER_LOG_LEVELS.map((level) => ({
        label: level,
        description: level === currentLevel ? 'Current' : undefined,
      })),
      {
        title: 'Dapper Launch Log Level',
        placeHolder: 'Choose the log level for future Dapper launch logs.',
      },
    );
    if (!picked || picked.label === currentLevel) {
      return;
    }

    await debuggerConfig.update('logLevel', picked.label, vscode.ConfigurationTarget.Workspace);
    this._updateViewState();
    vscode.window.showInformationMessage(`Dapper launch log level set to ${picked.label}.`);
  }

  public dispose(): void {
    for (const disposable of this._disposables) {
      disposable.dispose();
    }
    this._disposables.length = 0;
  }

  private _updateViewState(): void {
    const count = this._history.records.length;
    const currentLevel = this._getCurrentLogLevel(vscode.workspace.getConfiguration('dapper.debugger'));
    this._treeView.message = count === 0 ? 'No Dapper launches recorded in this window.' : undefined;
    this._treeView.badge = count > 0 ? { value: count, tooltip: `${count} recorded launch${count === 1 ? '' : 'es'}` } : undefined;
    this._treeView.description = `Recent runs and debug launches • log ${currentLevel}`;
  }

  private _getCurrentLogLevel(configuration: vscode.WorkspaceConfiguration): DebuggerLogLevel {
    const rawLevel = (configuration.get<string>('logLevel', 'DEBUG') || 'DEBUG').toUpperCase();
    return DEBUGGER_LOG_LEVELS.find((level) => level === rawLevel) ?? 'DEBUG';
  }
}

export type { LaunchTreeElement };