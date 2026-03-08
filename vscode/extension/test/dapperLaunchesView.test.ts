import * as vscode from 'vscode';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DapperLaunchHistoryService, DapperLaunchesView } from '../src/views/DapperLaunchesView.js';
import { resetDebugListeners } from './__mocks__/vscode.mjs';

describe('DapperLaunchesView', () => {
  let history: DapperLaunchHistoryService;
  let view: DapperLaunchesView;

  beforeEach(() => {
    resetDebugListeners();
    history = new DapperLaunchHistoryService();
    view = new DapperLaunchesView(history);
  });

  afterEach(() => {
    view.dispose();
    vi.restoreAllMocks();
    resetDebugListeners();
  });

  it('deletes an individual launch record from the view', () => {
    history.beginLaunch({
      launchToken: 'launch-1',
      sessionName: 'Run app.py',
      targetLabel: 'app.py',
      noDebug: true,
    });
    history.beginLaunch({
      launchToken: 'launch-2',
      sessionName: 'Debug worker.py',
      targetLabel: 'worker.py',
      noDebug: false,
    });

    view.deleteLaunch({ kind: 'launch', launchToken: 'launch-1' } as any);

    expect(history.records.map((record) => record.launchToken)).toEqual(['launch-2']);

    const providerChildren = (view as any)._provider.getChildren();
    expect(providerChildren).toEqual([{ kind: 'launch', launchToken: 'launch-2' }]);
    expect((view as any)._treeView.badge?.value).toBe(1);
  });

  it('exposes terminal focus as an inline action instead of row activation', () => {
    history.beginLaunch({
      launchToken: 'launch-1',
      sessionName: 'Run app.py',
      targetLabel: 'app.py',
      noDebug: true,
    });
    const show = vi.fn();
    history.attachTerminal('launch-1', { show } as any);

    const item = (view as any)._provider.getTreeItem({ kind: 'launch', launchToken: 'launch-1' });
    expect(item.command).toBeUndefined();
    expect(item.contextValue).toContain('withTerminal');

    view.focusTerminal({ kind: 'launch', launchToken: 'launch-1' } as any);

    expect(show).toHaveBeenCalledWith(false);
  });

  it('clears all launch records and restores the empty-state message', () => {
    history.beginLaunch({
      launchToken: 'launch-1',
      sessionName: 'Run app.py',
      targetLabel: 'app.py',
      noDebug: true,
    });
    history.beginLaunch({
      launchToken: 'launch-2',
      sessionName: 'Debug worker.py',
      targetLabel: 'worker.py',
      noDebug: false,
    });

    view.clearHistory();

    expect(history.records).toEqual([]);
    expect((view as any)._provider.getChildren()).toEqual([]);
    expect((view as any)._treeView.message).toBe('No Dapper launches recorded in this window.');
    expect((view as any)._treeView.badge).toBeUndefined();
  });

  it('lets the launches view select the debugger log level', async () => {
    let configuredLevel = 'DEBUG';
    const update = vi.fn(async (..._args: unknown[]) => undefined);
    vi.spyOn(vscode.workspace, 'getConfiguration').mockReturnValue({
      get: vi.fn(() => configuredLevel),
      update: vi.fn(async (_section: string, value: string, target: vscode.ConfigurationTarget) => {
        configuredLevel = value;
        await update(_section, value, target);
      }),
    } as any);
    vi.spyOn(vscode.window, 'showQuickPick').mockResolvedValue({ label: 'TRACE' } as any);
    const showInformationMessage = vi.spyOn(vscode.window, 'showInformationMessage').mockImplementation(() => undefined as any);

    await view.selectLogLevel();

    expect(update).toHaveBeenCalledWith('logLevel', 'TRACE', vscode.ConfigurationTarget.Workspace);
    expect(showInformationMessage).toHaveBeenCalledWith('Dapper launch log level set to TRACE.');
    expect((view as any)._treeView.description).toContain('log TRACE');
  });

  it('shows the log filename basename in the launch tooltip', () => {
    history.beginLaunch({
      launchToken: 'launch-1',
      sessionName: 'Debug app.py',
      targetLabel: 'app.py',
      noDebug: false,
    });
    history.updateLogFile('launch-1', '/tmp/dapper-debug-20260307-184527-012-session-123.log');

    const item = (view as any)._provider.getTreeItem({ kind: 'launch', launchToken: 'launch-1' });

    expect(item.tooltip).toContain('Log name: dapper-debug-20260307-184527-012-session-123.log');
    expect(item.tooltip).toContain('Log file: /tmp/dapper-debug-20260307-184527-012-session-123.log');
  });
});