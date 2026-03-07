import { beforeEach, describe, expect, it, vi } from 'vitest';

const vscode = await import('vscode');

describe('Dapper extension dynamic picker registration', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    vscode.DebugConfigurationProviderTriggerKind = {
      Initial: 1,
      Dynamic: 2,
    };

    vscode.debug.registerDebugConfigurationProvider = vi.fn(() => new vscode.Disposable(() => {}));
    vscode.debug.registerDebugAdapterDescriptorFactory = vi.fn(() => new vscode.Disposable(() => {}));
    vscode.debug.registerDebugAdapterTrackerFactory = vi.fn(() => new vscode.Disposable(() => {}));
    vscode.workspace.onDidSaveTextDocument = vi.fn(() => new vscode.Disposable(() => {}));
    vscode.window.setStatusBarMessage = vi.fn();
    vscode.window.registerWebviewPanelSerializer = undefined;
  });

  it('registers a dynamic Dapper provider that offers attach-by-pid in the picker', async () => {
    const { register } = await import('../src/extension.ts');

    const context = {
      extensionUri: vscode.Uri.file('/tmp/dapper-extension'),
      extension: {
        packageJSON: { version: '0.9.1' },
      },
      globalStorageUri: { fsPath: '/tmp/dapper-storage' },
      workspaceState: {
        get: () => undefined,
        update: async () => {},
        keys: () => [],
      },
      subscriptions: [],
    };

    const disposable = register(context);

    const providerRegistrations = vscode.debug.registerDebugConfigurationProvider.mock.calls;
    expect(providerRegistrations).toHaveLength(2);

    const dynamicRegistration = providerRegistrations.find((call) => call[2] === vscode.DebugConfigurationProviderTriggerKind.Dynamic);
    expect(dynamicRegistration).toBeDefined();
    expect(dynamicRegistration[0]).toBe('dapper');

    const dynamicProvider = dynamicRegistration[1];
    const configs = await dynamicProvider.provideDebugConfigurations(undefined);

    expect(configs).toEqual(expect.arrayContaining([
      expect.objectContaining({
        type: 'dapper',
        request: 'launch',
        program: '${file}',
      }),
      expect.objectContaining({
        type: 'dapper',
        request: 'attach',
        processId: '${command:pickProcess}',
      }),
      expect.objectContaining({
        type: 'dapper',
        name: 'Dapper: Configure via Wizard',
        __dapperUseWizard: true,
      }),
    ]));

    disposable.dispose();
  });
});