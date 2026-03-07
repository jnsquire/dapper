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

  it('focuses the associated terminal when a launch record is activated', () => {
    history.beginLaunch({
      launchToken: 'launch-1',
      sessionName: 'Run app.py',
      targetLabel: 'app.py',
      noDebug: true,
    });
    const show = vi.fn();
    history.attachTerminal('launch-1', { show } as any);

    const item = (view as any)._provider.getTreeItem({ kind: 'launch', launchToken: 'launch-1' });
    expect(item.command).toMatchObject({
      command: 'dapper.launches.focusTerminal',
      arguments: [{ kind: 'launch', launchToken: 'launch-1' }],
    });

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
});