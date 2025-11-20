import { describe, it, expect, beforeEach, vi } from 'vitest';

const vscode = await import('vscode');
vscode.workspace.getConfiguration = vi.fn().mockReturnValue({ get: () => undefined, update: () => Promise.resolve() });

// Import the source DapperWebview directly
const { DapperWebview } = await import('../src/webview/DapperWebview.ts');

describe('DapperWebview message handlers', () => {
  beforeEach(() => {
    // Reset mock calls
    vi.clearAllMocks();
    vscode.commands.executeCommand = vi.fn();
    vscode.debug.startDebugging = vi.fn();
    // Clear panels list for clean state
    vscode.panelsList.length = 0;
    // Ensure DapperWebview recreates panel each test
    if (DapperWebview && DapperWebview.currentPanel) DapperWebview.currentPanel = undefined;
  });

  it('should respond to requestConfig with saved configuration', async () => {
    const saved = { type: 'dapper', request: 'launch', name: 'Saved Config' };
    vscode.workspace.getConfiguration = vi.fn().mockReturnValue({ get: () => saved });

    await DapperWebview.createOrShow(vscode.Uri.file('/dummy'), 'config');
    const panels = vscode.panelsList;
    expect(panels.length).toBeGreaterThan(0);
    const panel = panels[panels.length - 1];
    expect(panel).toBeDefined();
    const webview = panel.webview;
    // Spy on postMessage
    webview.postMessage = vi.fn();

    // Simulate receiving a requestConfig message
    expect(webview._messageHandler).toBeDefined();

    await webview._messageHandler({ command: 'requestConfig' });

    // The webview should have been posted the saved config
    expect(webview.postMessage).toHaveBeenCalledWith({ command: 'updateConfig', config: saved });
  });

  it('should call insertLaunchConfiguration on saveAndInsert and post status', async () => {
    const saved = { type: 'dapper', request: 'launch', name: 'Saved Config' };
    const updateMock = vi.fn().mockResolvedValue(undefined);
    vscode.workspace.getConfiguration = vi.fn().mockReturnValue({ get: () => saved, update: updateMock });
    // Simulate missing launch.json so insertLaunchConfiguration will create a new one
    vscode.workspace.fs.readFile = vi.fn().mockRejectedValueOnce(new Error('FileNotFound'));
    vscode.workspace.fs.writeFile = vi.fn().mockResolvedValueOnce(undefined);

    await DapperWebview.createOrShow(vscode.Uri.file('/dummy'), 'config');
    const panels = vscode.panelsList;
    expect(panels.length).toBeGreaterThan(0);
    const panel = panels[panels.length - 1];
    expect(panel).toBeDefined();
    const webview = panel.webview;

    // Ensure we can spy on postMessage
    webview.postMessage = vi.fn();
    expect(webview._messageHandler).toBeDefined();
    await webview._messageHandler({ command: 'saveAndInsert', config: saved });
    expect(updateMock).toHaveBeenCalled();

    // Should have posted status update confirming insert
    expect(webview.postMessage).toHaveBeenCalledWith({ command: 'updateStatus', text: 'Configuration inserted into launch.json' });
  });

  it('should call startDebugging on startDebug message', async () => {
    const cfg = { type: 'dapper', request: 'launch', name: 'Run Now', program: '${file}' };
    await DapperWebview.createOrShow(vscode.Uri.file('/dummy'), 'config');
    const panel = vscode.panelsList[vscode.panelsList.length - 1];
    expect(panel).toBeDefined();
    const webview = panel.webview;

    expect(webview._messageHandler).toBeDefined();
    
    await webview._messageHandler({ command: 'startDebug', config: cfg });

    expect(vscode.debug.startDebugging).toHaveBeenCalledWith(undefined, cfg);
  });
});
