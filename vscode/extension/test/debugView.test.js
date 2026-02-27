import { describe, it, expect, beforeEach, vi } from 'vitest';

const vscode = await import('vscode');
const { fireDebugEvent, resetDebugListeners } = await import('./__mocks__/vscode.mjs');
const { DapperWebview } = await import('../src/webview/DapperWebview.ts');

describe('DebugView — panel creation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vscode.panelsList.length = 0;
    if (DapperWebview.currentPanel) DapperWebview.currentPanel = undefined;
    resetDebugListeners();
  });

  it('creates a debug panel (not config fallback)', async () => {
    await DapperWebview.createOrShow(vscode.Uri.file('/dummy'), 'debug');
    const panels = vscode.panelsList;
    expect(panels.length).toBeGreaterThan(0);
    const panel = panels[panels.length - 1];
    expect(panel.webview.html ?? '').toContain('vscode-toolbar-container');
  });

  it('panel HTML contains vscode-elements script', async () => {
    await DapperWebview.createOrShow(vscode.Uri.file('/dummy'), 'debug');
    const panel = vscode.panelsList[vscode.panelsList.length - 1];
    expect(panel.webview.html ?? '').toContain('@vscode-elements');
  });

  it('panel HTML contains thread selector', async () => {
    await DapperWebview.createOrShow(vscode.Uri.file('/dummy'), 'debug');
    const panel = vscode.panelsList[vscode.panelsList.length - 1];
    expect(panel.webview.html ?? '').toContain('vscode-single-select');
  });

  it('panel HTML contains stack tree', async () => {
    await DapperWebview.createOrShow(vscode.Uri.file('/dummy'), 'debug');
    const panel = vscode.panelsList[vscode.panelsList.length - 1];
    expect(panel.webview.html ?? '').toContain('vscode-tree');
  });

  it('panel HTML contains variables table', async () => {
    await DapperWebview.createOrShow(vscode.Uri.file('/dummy'), 'debug');
    const panel = vscode.panelsList[vscode.panelsList.length - 1];
    expect(panel.webview.html ?? '').toContain('vscode-table');
  });
});

describe('DebugView — toolbar commands', () => {
  let panel;
  let webview;

  beforeEach(async () => {
    vi.clearAllMocks();
    vscode.panelsList.length = 0;
    if (DapperWebview.currentPanel) DapperWebview.currentPanel = undefined;
    resetDebugListeners();
    vscode.commands.executeCommand = vi.fn();
    await DapperWebview.createOrShow(vscode.Uri.file('/dummy'), 'debug');
    panel = vscode.panelsList[vscode.panelsList.length - 1];
    webview = panel.webview;
  });

  it('continue command calls workbench.action.debug.continue', async () => {
    expect(webview._messageHandler).toBeDefined();
    await webview._messageHandler({ command: 'continue' });
    expect(vscode.commands.executeCommand).toHaveBeenCalledWith('workbench.action.debug.continue');
  });

  it('pause command calls workbench.action.debug.pause', async () => {
    await webview._messageHandler({ command: 'pause' });
    expect(vscode.commands.executeCommand).toHaveBeenCalledWith('workbench.action.debug.pause');
  });

  it('stepOver command calls workbench.action.debug.stepOver', async () => {
    await webview._messageHandler({ command: 'stepOver' });
    expect(vscode.commands.executeCommand).toHaveBeenCalledWith('workbench.action.debug.stepOver');
  });

  it('stepInto command calls workbench.action.debug.stepInto', async () => {
    await webview._messageHandler({ command: 'stepInto' });
    expect(vscode.commands.executeCommand).toHaveBeenCalledWith('workbench.action.debug.stepInto');
  });

  it('stepOut command calls workbench.action.debug.stepOut', async () => {
    await webview._messageHandler({ command: 'stepOut' });
    expect(vscode.commands.executeCommand).toHaveBeenCalledWith('workbench.action.debug.stepOut');
  });
});

describe('DebugView — session watcher events', () => {
  let panel;
  let webview;

  beforeEach(async () => {
    vi.clearAllMocks();
    vscode.panelsList.length = 0;
    if (DapperWebview.currentPanel) DapperWebview.currentPanel = undefined;
    resetDebugListeners();
    await DapperWebview.createOrShow(vscode.Uri.file('/dummy'), 'debug');
    panel = vscode.panelsList[vscode.panelsList.length - 1];
    webview = panel.webview;
    webview.postMessage = vi.fn().mockResolvedValue(true);
  });

  it('session start posts sessionState: running', async () => {
    fireDebugEvent('onDidStartDebugSession', {});
    // Give async microtasks a chance to settle
    await Promise.resolve();
    expect(webview.postMessage).toHaveBeenCalledWith(
      expect.objectContaining({ command: 'sessionState', state: 'running' })
    );
  });

  it('session terminate posts clearStack then sessionState: stopped', async () => {
    fireDebugEvent('onDidTerminateDebugSession', {});
    await Promise.resolve();
    const calls = webview.postMessage.mock.calls.map(c => c[0]);
    expect(calls.some(m => m.command === 'clearStack')).toBe(true);
    expect(calls.some(m => m.command === 'sessionState' && m.state === 'stopped')).toBe(true);
  });
});

describe('DebugView — selectFrame stub', () => {
  let panel;
  let webview;

  beforeEach(async () => {
    vi.clearAllMocks();
    vscode.panelsList.length = 0;
    if (DapperWebview.currentPanel) DapperWebview.currentPanel = undefined;
    resetDebugListeners();
    await DapperWebview.createOrShow(vscode.Uri.file('/dummy'), 'debug');
    panel = vscode.panelsList[vscode.panelsList.length - 1];
    webview = panel.webview;
  });

  it('selectFrame does not throw when no debug session is active', () => {
    vscode.debug.activeDebugSession = null;
    expect(() => webview._messageHandler({ command: 'selectFrame', frameId: 1 })).not.toThrow();
  });

  it('filterStack does not throw', () => {
    expect(() => webview._messageHandler({ command: 'filterStack', query: 'main' })).not.toThrow();
  });
});

describe('DebugView — dispose', () => {
  it('dispose cleans up the panel and watcher', async () => {
    vi.clearAllMocks();
    vscode.panelsList.length = 0;
    if (DapperWebview.currentPanel) DapperWebview.currentPanel = undefined;
    resetDebugListeners();
    await DapperWebview.createOrShow(vscode.Uri.file('/dummy'), 'debug');
    const cp = DapperWebview.currentPanel;
    expect(cp).toBeDefined();
    cp.dispose();
    expect(DapperWebview.currentPanel).toBeUndefined();
  });
});
