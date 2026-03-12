import { beforeEach, describe, expect, it, vi } from 'vitest';

const vscode = await import('vscode');
const { LaunchService } = await import('../src/debugAdapter/launchService.ts');

describe('Dapper sticky run menu actions', () => {
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
    vscode.workspace.onDidChangeConfiguration = vi.fn(() => new vscode.Disposable(() => {}));
    vscode.window.setStatusBarMessage = vi.fn();
    vscode.window.registerWebviewPanelSerializer = undefined;
    vscode.window.activeTextEditor = {
      viewColumn: vscode.ViewColumn.One,
      document: {
        languageId: 'python',
        isUntitled: false,
        uri: { scheme: 'file', fsPath: '/tmp/example.py' },
      },
    };
  });

  it('initializes sticky menu contexts from workspace state defaults', async () => {
    const registeredCommands = new Map();
    vscode.commands.registerCommand = vi.fn((command, callback) => {
      registeredCommands.set(command, callback);
      return new vscode.Disposable(() => registeredCommands.delete(command));
    });
    vscode.commands.executeCommand = vi.fn(() => Promise.resolve());

    const { register } = await import('../src/extension.ts');

    const context = {
      extensionUri: vscode.Uri.file('/tmp/dapper-extension'),
      extension: {
        packageJSON: { version: '0.9.1' },
      },
      globalStorageUri: { fsPath: '/tmp/dapper-storage' },
      workspaceState: {
        get: vi.fn(() => undefined),
        update: vi.fn(async () => {}),
        keys: () => [],
      },
      subscriptions: [],
    };

    const disposable = register(context);
    await Promise.resolve();

    expect(vscode.commands.executeCommand).toHaveBeenCalledWith('setContext', 'dapper.runStickyIsRun', true);
    expect(vscode.commands.executeCommand).toHaveBeenCalledWith('setContext', 'dapper.runStickyIsRunPickEnvironment', false);
    expect(vscode.commands.executeCommand).toHaveBeenCalledWith('setContext', 'dapper.debugStickyIsDebug', true);
    expect(vscode.commands.executeCommand).toHaveBeenCalledWith('setContext', 'dapper.debugStickyIsDebugPickEnvironment', false);
    expect(vscode.commands.executeCommand).toHaveBeenCalledWith('setContext', 'dapper.debugStickyIsDebugStopOnEntry', false);

    disposable.dispose();
  });

  it('updates sticky state and launch options when a non-default variant runs', async () => {
    const registeredCommands = new Map();
    vscode.commands.registerCommand = vi.fn((command, callback) => {
      registeredCommands.set(command, callback);
      return new vscode.Disposable(() => registeredCommands.delete(command));
    });
    vscode.commands.executeCommand = vi.fn(() => Promise.resolve());
    const workspaceStateUpdate = vi.fn(async () => {});
    const launchSpy = vi.spyOn(LaunchService.prototype, 'launch').mockResolvedValue({
      started: true,
      waitedForStop: false,
      stopped: false,
      resolvedTarget: { kind: 'file', value: '/tmp/example.py' },
      configuration: { type: 'dapper', request: 'launch', name: 'Test' },
    });

    const { register } = await import('../src/extension.ts');

    const context = {
      extensionUri: vscode.Uri.file('/tmp/dapper-extension'),
      extension: {
        packageJSON: { version: '0.9.1' },
      },
      globalStorageUri: { fsPath: '/tmp/dapper-storage' },
      workspaceState: {
        get: vi.fn((key) => {
          if (key === 'dapper.runStickyAction') return 'run';
          if (key === 'dapper.debugStickyAction') return 'debug';
          return undefined;
        }),
        update: workspaceStateUpdate,
        keys: () => [],
      },
      subscriptions: [],
    };

    const disposable = register(context);
    const runPickEnvironment = registeredCommands.get('dapper.runCurrentFilePickEnvironment');
    const debugStopOnEntry = registeredCommands.get('dapper.startDebuggingStopOnEntry');

    expect(runPickEnvironment).toBeTypeOf('function');
    expect(debugStopOnEntry).toBeTypeOf('function');

    await runPickEnvironment();
    await debugStopOnEntry();

    expect(workspaceStateUpdate).toHaveBeenCalledWith('dapper.runStickyAction', 'runPickEnvironment');
    expect(workspaceStateUpdate).toHaveBeenCalledWith('dapper.debugStickyAction', 'debugStopOnEntry');
    expect(vscode.commands.executeCommand).toHaveBeenCalledWith('setContext', 'dapper.runStickyIsRunPickEnvironment', true);
    expect(vscode.commands.executeCommand).toHaveBeenCalledWith('setContext', 'dapper.debugStickyIsDebugStopOnEntry', true);
    expect(launchSpy).toHaveBeenNthCalledWith(1, expect.objectContaining({ noDebug: true, pickEnvironment: true }));
    expect(launchSpy).toHaveBeenNthCalledWith(2, expect.objectContaining({ noDebug: false, stopOnEntry: true }));

    launchSpy.mockRestore();
    disposable.dispose();
  });
});