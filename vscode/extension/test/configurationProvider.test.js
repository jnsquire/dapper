import { describe, it, expect, vi } from 'vitest';

const vscode = await import('vscode');
vscode.workspace.getConfiguration = vi.fn().mockReturnValue({ get: () => undefined });
const { DapperConfigurationProvider, DapperDynamicConfigurationProvider } = await import('../src/debugAdapter/configurationProvider.ts');

const extensionUri = vscode.Uri.file('/tmp/dapper-extension');

describe('DapperConfigurationProvider', () => {
  it('should provide a default configuration when none saved', async () => {
    const provider = new DapperConfigurationProvider(extensionUri);
    const configs = await provider.provideDebugConfigurations(undefined);
    expect(Array.isArray(configs)).toBe(true);
    expect(configs && configs[0]).toHaveProperty('type', 'dapper');
    expect(configs && configs[1]).toMatchObject({
      type: 'dapper',
      request: 'attach',
      processId: '${command:pickProcess}',
    });
  });

  it('should merge saved settings into launched configuration', async () => {
    // Mock saved settings to include stopOnEntry=false
    vscode.workspace.getConfiguration.mockReturnValue({ get: () => ({ stopOnEntry: false, console: 'integratedTerminal' }) });
    const provider = new DapperConfigurationProvider(extensionUri);
    const config = { type: 'dapper', request: 'launch', name: 'Test', program: '${file}' };
    const res = await provider.resolveDebugConfigurationWithSubstitutedVariables(undefined, config, undefined);
    expect(res).toBeDefined();
    expect(res.stopOnEntry).toBe(false);
    expect(res.console).toBe('integratedTerminal');
  });

  it('should not merge a saved module into the current-file launch configuration', async () => {
    vscode.workspace.getConfiguration.mockReturnValue({ get: () => ({ module: 'pkg.main', stopOnEntry: false }) });
    const provider = new DapperConfigurationProvider(extensionUri);
    const config = { type: 'dapper', request: 'launch', name: 'Dapper: Launch ${fileBasename}', program: '${file}' };

    const res = await provider.resolveDebugConfigurationWithSubstitutedVariables(undefined, config, undefined);

    expect(res).toBeDefined();
    expect(res.program).toBe('${file}');
    expect(res.module).toBeUndefined();
    expect(res.stopOnEntry).toBe(false);
  });

  it('should allow launch when module is provided without program', async () => {
    const provider = new DapperConfigurationProvider(extensionUri);
    const config = { type: 'dapper', request: 'launch', name: 'Module Launch', module: 'pkg.main' };
    const res = await provider.resolveDebugConfigurationWithSubstitutedVariables(undefined, config, undefined);
    expect(res).toBeDefined();
    expect(res?.module).toBe('pkg.main');
  });

  it('should reject launch when both program and module are provided', async () => {
    const provider = new DapperConfigurationProvider(extensionUri);
    vscode.window.showInformationMessage = vi.fn();

    const res = await provider.resolveDebugConfigurationWithSubstitutedVariables(undefined, {
      type: 'dapper',
      request: 'launch',
      name: 'Invalid Launch',
      program: '${file}',
      module: 'pkg.main',
    }, undefined);

    expect(res).toBeUndefined();
    expect(vscode.window.showInformationMessage).toHaveBeenCalledWith('Provide exactly one launch target: program or module.');
  });

  it('should reject launch when host/port is provided instead of a launch target', async () => {
    const provider = new DapperConfigurationProvider(extensionUri);
    vscode.window.showInformationMessage = vi.fn();

    const res = await provider.resolveDebugConfigurationWithSubstitutedVariables(undefined, {
      type: 'dapper',
      request: 'launch',
      name: 'Invalid Host Launch',
      host: 'localhost',
      port: 5678,
    }, undefined);

    expect(res).toBeUndefined();
    expect(vscode.window.showInformationMessage).toHaveBeenCalledWith('Provide exactly one launch target: program or module.');
  });

  it('should allow attach when host and port are provided', async () => {
    const provider = new DapperConfigurationProvider(extensionUri);
    const config = { type: 'dapper', request: 'attach', name: 'Host Attach', host: 'localhost', port: 5678 };
    const res = await provider.resolveDebugConfigurationWithSubstitutedVariables(undefined, config, undefined);
    expect(res).toBeDefined();
    expect(res?.host).toBe('localhost');
    expect(res?.port).toBe(5678);
  });

  it('should reject attach when both processId and host/port are provided', async () => {
    const provider = new DapperConfigurationProvider(extensionUri);
    vscode.window.showInformationMessage = vi.fn();

    const res = await provider.resolveDebugConfigurationWithSubstitutedVariables(undefined, {
      type: 'dapper',
      request: 'attach',
      name: 'Invalid Attach',
      processId: '${command:pickProcess}',
      host: 'localhost',
      port: 5678,
    }, undefined);

    expect(res).toBeUndefined();
    expect(vscode.window.showInformationMessage).toHaveBeenCalledWith('Provide exactly one attach target: processId or host/port.');
  });

  it('should abort launch when no target can be determined and active editor is not a python file', async () => {
    const provider = new DapperConfigurationProvider(extensionUri);
    const config = { type: 'dapper', request: 'launch', name: 'No Program' };
    // Ensure no active editor
    vscode.window.activeTextEditor = undefined;
    // Mock showInformationMessage
    vscode.window.showInformationMessage = vi.fn();
    const res = await provider.resolveDebugConfigurationWithSubstitutedVariables(undefined, config, undefined);
    expect(res).toBeUndefined();
    expect(vscode.window.showInformationMessage).toHaveBeenCalled();
  });

  it('should resolve the wizard placeholder configuration through the webview helper', async () => {
    const provider = new DapperConfigurationProvider(extensionUri);
    const { DapperWebview } = await import('../src/webview/DapperWebview.js');
    vi.spyOn(DapperWebview, 'showAndWaitForConfig').mockResolvedValue({
      type: 'dapper',
      request: 'attach',
      name: 'Wizard Config',
      processId: '${command:pickProcess}',
    });

    const result = await provider.resolveDebugConfigurationWithSubstitutedVariables(undefined, {
      type: 'dapper',
      request: 'launch',
      name: 'Dapper: Configure via Wizard',
      __dapperUseWizard: true,
    }, undefined);

    expect(DapperWebview.showAndWaitForConfig).toHaveBeenCalledWith(extensionUri);
    expect(result).toMatchObject({
      request: 'attach',
      processId: '${command:pickProcess}',
    });
  });
});

describe('DapperDynamicConfigurationProvider', () => {
  it('should return explicit launch and attach-by-pid configurations for the debug picker', async () => {
    const provider = new DapperDynamicConfigurationProvider();
    const configs = await provider.provideDebugConfigurations(undefined);

    expect(configs).toEqual(expect.arrayContaining([
      expect.objectContaining({
        type: 'dapper',
        request: 'launch',
        name: 'Dapper: Launch ${fileBasename}',
        program: '${file}',
      }),
      expect.objectContaining({
        type: 'dapper',
        request: 'attach',
        processId: '${command:pickProcess}',
      }),
      expect.objectContaining({
        type: 'dapper',
        request: 'attach',
        host: 'localhost',
        port: 5678,
      }),
      expect.objectContaining({
        type: 'dapper',
        name: 'Dapper: Configure via Wizard',
        __dapperUseWizard: true,
      }),
    ]));
  });
});
