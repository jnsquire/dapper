import { describe, it, expect, vi } from 'vitest';

const vscode = await import('vscode');
vscode.workspace.getConfiguration = vi.fn().mockReturnValue({ get: () => undefined });
const { DapperConfigurationProvider } = await import('../src/debugAdapter/configurationProvider.ts');

describe('DapperConfigurationProvider', () => {
  it('should provide a default configuration when none saved', async () => {
    const provider = new DapperConfigurationProvider();
    const configs = await provider.provideDebugConfigurations(undefined);
    expect(Array.isArray(configs)).toBe(true);
    expect(configs && configs[0]).toHaveProperty('type', 'dapper');
  });

  it('should merge saved settings into launched configuration', async () => {
    // Mock saved settings to include stopOnEntry=false
    vscode.workspace.getConfiguration.mockReturnValue({ get: () => ({ stopOnEntry: false, console: 'integratedTerminal' }) });
    const provider = new DapperConfigurationProvider();
    const config = { type: 'dapper', request: 'launch', name: 'Test', program: '${file}' };
    const res = await provider.resolveDebugConfigurationWithSubstitutedVariables(undefined, config, undefined);
    expect(res).toBeDefined();
    expect(res.stopOnEntry).toBe(false);
    expect(res.console).toBe('integratedTerminal');
  });

  it('should abort launch when no program can be determined and active editor is not a python file', async () => {
    const provider = new DapperConfigurationProvider();
    const config = { type: 'dapper', request: 'launch', name: 'No Program' };
    // Ensure no active editor
    vscode.window.activeTextEditor = undefined;
    // Mock showInformationMessage
    vscode.window.showInformationMessage = vi.fn();
    const res = await provider.resolveDebugConfigurationWithSubstitutedVariables(undefined, config, undefined);
    expect(res).toBeUndefined();
    expect(vscode.window.showInformationMessage).toHaveBeenCalled();
  });
});
