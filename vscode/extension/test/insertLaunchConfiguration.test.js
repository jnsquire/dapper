import { describe, it, expect, vi } from 'vitest';

const vscode = await import('vscode');
// Ensure we have mock functions assigned for fs operations
vscode.workspace.fs.readFile = vi.fn();
vscode.workspace.fs.writeFile = vi.fn();
vscode.workspace.fs.createDirectory = vi.fn();
const { insertLaunchConfiguration } = await import('../src/utils/insertLaunchConfiguration.ts');

describe('insertLaunchConfiguration helper', () => {
-  beforeEach(() => {
    vi.clearAllMocks();
    vscode.workspace.fs.readFile = vi.fn();
    vscode.workspace.fs.writeFile = vi.fn();
    vscode.workspace.fs.createDirectory = vi.fn();
    vscode.window.showWarningMessage = vi.fn();
    vscode.window.showInformationMessage = vi.fn();
    vscode.window.showErrorMessage = vi.fn();
    vscode.workspace.openTextDocument = vi.fn();
    vscode.window.showTextDocument = vi.fn();
    vscode.window.showQuickPick = vi.fn();
  });
  it('should create a new launch.json when none exists', async () => {
    const tmpDir = '/tmp/dapper-test';
    const folder = { name: 'dapper-test', uri: { fsPath: tmpDir } };

    // Adjust workspaceMocks
    vscode.workspace.workspaceFolders = [folder];

    const config = {
      type: 'dapper',
      request: 'launch',
      name: 'Test Config',
      program: '${file}',
      console: 'integratedTerminal'
    };

    // Make readFile throw to simulate file not found
    vscode.workspace.fs.readFile.mockRejectedValueOnce(new Error('FileNotFound'));
    vscode.workspace.fs.writeFile.mockResolvedValueOnce(undefined);

    const ok = await insertLaunchConfiguration(config, folder);

    expect(ok).toBe(true);
    expect(vscode.workspace.fs.writeFile).toHaveBeenCalled();
  });

  it('should return false and open launch.json when existing launch.json contains invalid JSON', async () => {
    const tmpDir = '/tmp/dapper-test2';
    const folder = { name: 'dapper-test2', uri: { fsPath: tmpDir } };
    vscode.workspace.workspaceFolders = [folder];

    const config = { type: 'dapper', request: 'launch', name: 'Test Config', program: '${file}' };

    vscode.workspace.fs.readFile.mockResolvedValueOnce(Buffer.from('not-a-json'));
    // Mock showWarningMessage to return 'Open launch.json' indicating user wants to open
    vscode.window.showWarningMessage = vi.fn().mockResolvedValue('Open launch.json');
    vscode.workspace.openTextDocument = vi.fn().mockResolvedValue({});
    vscode.window.showTextDocument = vi.fn().mockResolvedValue({});

    const ok = await insertLaunchConfiguration(config, folder);

    expect(ok).toBe(false);
    expect(vscode.window.showWarningMessage).toHaveBeenCalled();
    expect(vscode.workspace.openTextDocument).toHaveBeenCalled();
  });

  it('should replace an existing config when user chooses Replace', async () => {
    const tmpDir = '/tmp/dapper-test3';
    const folder = { name: 'dapper-test3', uri: { fsPath: tmpDir } };
    vscode.workspace.workspaceFolders = [folder];

    const config = { type: 'dapper', request: 'launch', name: 'Replace Me', program: '${file}', console: 'internalConsole' };

    const existingJson = {
      version: '0.2.0',
      configurations: [
        { type: 'dapper', request: 'launch', name: 'Replace Me', program: '${file}', console: 'externalTerminal' }
      ]
    };
    vscode.workspace.fs.readFile.mockResolvedValueOnce(Buffer.from(JSON.stringify(existingJson)));
    // showInformationMessage returns 'Replace existing'
    vscode.window.showInformationMessage = vi.fn().mockResolvedValue('Replace existing');

    const ok = await insertLaunchConfiguration(config, folder);

    expect(ok).toBe(true);
    expect(vscode.workspace.fs.writeFile).toHaveBeenCalled();
  });
  
  it('should add a duplicate when user chooses Add duplicate', async () => {
    const tmpDir = '/tmp/dapper-test4';
    const folder = { name: 'dapper-test4', uri: { fsPath: tmpDir } };
    vscode.workspace.workspaceFolders = [folder];

    const config = { type: 'dapper', request: 'launch', name: 'Duplicate Me', program: '${file}', console: 'internalConsole' };

    const existingJson = {
      version: '0.2.0',
      configurations: [
        { type: 'dapper', request: 'launch', name: 'Duplicate Me', program: '${file}', console: 'externalTerminal' }
      ]
    };
    vscode.workspace.fs.readFile.mockResolvedValueOnce(Buffer.from(JSON.stringify(existingJson)));
    // showInformationMessage returns 'Add duplicate'
    vscode.window.showInformationMessage = vi.fn().mockResolvedValue('Add duplicate');

    const ok = await insertLaunchConfiguration(config, folder);

    expect(ok).toBe(true);
    expect(vscode.workspace.fs.writeFile).toHaveBeenCalled();
  });

  it('should abort on duplicate when user cancels', async () => {
    const tmpDir = '/tmp/dapper-test5';
    const folder = { name: 'dapper-test5', uri: { fsPath: tmpDir } };
    vscode.workspace.workspaceFolders = [folder];

    const config = { type: 'dapper', request: 'launch', name: 'Duplicate Me', program: '${file}', console: 'internalConsole' };

    const existingJson = {
      version: '0.2.0',
      configurations: [
        { type: 'dapper', request: 'launch', name: 'Duplicate Me', program: '${file}', console: 'externalTerminal' }
      ]
    };
    vscode.workspace.fs.readFile.mockResolvedValueOnce(Buffer.from(JSON.stringify(existingJson)));
    // showInformationMessage returns undefined for cancel
    vscode.window.showInformationMessage = vi.fn().mockResolvedValue(undefined);

    const ok = await insertLaunchConfiguration(config, folder);

    expect(ok).toBe(false);
    // Should not have written any file
    expect(vscode.workspace.fs.writeFile).not.toHaveBeenCalled();
  });

  it('should return false when write fails', async () => {
    const tmpDir = '/tmp/dapper-test6';
    const folder = { name: 'dapper-test6', uri: { fsPath: tmpDir } };
    vscode.workspace.workspaceFolders = [folder];

    const config = { type: 'dapper', request: 'launch', name: 'FileFail', program: '${file}' };

    // Simulate no file exists
    vscode.workspace.fs.readFile.mockRejectedValueOnce(new Error('FileNotFound'));
    // Simulate write failure
    vscode.workspace.fs.writeFile.mockRejectedValueOnce(new Error('WriteFailed'));

    const ok = await insertLaunchConfiguration(config, folder);

    expect(ok).toBe(false);
    expect(vscode.window.showErrorMessage).toHaveBeenCalled();
  });
  
  it('should prompt to choose folder when multiple workspace folders and handle selection', async () => {
    const tmp1 = '/tmp/dapper-workspace1';
    const tmp2 = '/tmp/dapper-workspace2';
    const folder1 = { name: 'wp1', uri: { fsPath: tmp1 } };
    const folder2 = { name: 'wp2', uri: { fsPath: tmp2 } };
    vscode.workspace.workspaceFolders = [folder1, folder2];

    const config = { type: 'dapper', request: 'launch', name: 'Test Config', program: '${file}' };

    // Simulate user picking the second workspace folder
    vscode.window.showQuickPick = vi.fn().mockResolvedValue('wp2');
    vscode.workspace.fs.readFile.mockRejectedValueOnce(new Error('FileNotFound'));
    vscode.workspace.fs.writeFile.mockResolvedValueOnce(undefined);

    const ok = await insertLaunchConfiguration(config);
    expect(ok).toBe(true);
    expect(vscode.window.showQuickPick).toHaveBeenCalled();
  });
});
