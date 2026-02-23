import * as vscode from 'vscode';
import { DapperDebugAdapterDescriptorFactory } from './debugAdapter/dapperDebugAdapter.js';
import { DapperConfigurationProvider } from './debugAdapter/configurationProvider.js';
import { DapperWebview } from './webview/DapperWebview.js';
import { logger, registerLoggerCommands } from './utils/logger.js';
import { insertLaunchConfiguration } from './utils/insertLaunchConfiguration.js';

function normalizeFsPath(path: string): string {
  return process.platform === 'win32' ? path.toLowerCase() : path;
}

function* registerCommands(context: vscode.ExtensionContext): Iterable<vscode.Disposable> {
  logger.log('Registering Dapper Debugger commands');
  const stoppedSessions = new Set<string>();
  const pendingReloads = new Set<string>();
  const autoReloadStatusThrottleMs = 1500;
  let lastAutoReloadStatusAt = 0;

  const showAutoReloadStatus = (document: vscode.TextDocument): void => {
    const now = Date.now();
    if (now - lastAutoReloadStatusAt < autoReloadStatusThrottleMs) {
      return;
    }
    lastAutoReloadStatusAt = now;

    const displayPath = vscode.workspace.asRelativePath(document.uri, false);
    vscode.window.setStatusBarMessage(`Dapper: Auto reloaded ${displayPath}`, 2500);
  };

  const tryAutoHotReload = async (document: vscode.TextDocument): Promise<void> => {
    const enabled = vscode.workspace.getConfiguration('dapper').get<boolean>('hotReload.autoOnSave', true);
    if (!enabled || document.languageId !== 'python' || document.isUntitled) {
      return;
    }

    const session = vscode.debug.activeDebugSession;
    if (!session || session.type !== 'dapper') {
      return;
    }

    if (!stoppedSessions.has(session.id)) {
      return;
    }

    const sourcePath = document.uri.fsPath;
    const pendingKey = `${session.id}:${sourcePath}`;
    if (pendingReloads.has(pendingKey)) {
      return;
    }

    try {
      const loadedSourcesResult = await session.customRequest('loadedSources', {});
      const loadedSources = Array.isArray(loadedSourcesResult?.sources) ? loadedSourcesResult.sources : [];
      const normalizedSourcePath = normalizeFsPath(sourcePath);
      const inSession = loadedSources.some((source: { path?: string }) => {
        const path = source?.path;
        return typeof path === 'string' && normalizeFsPath(path) === normalizedSourcePath;
      });
      if (!inSession) {
        return;
      }

      pendingReloads.add(pendingKey);
      await session.customRequest('dapper/hotReload', {
        source: {
          path: sourcePath,
        },
      });
      logger.log(`Auto hot reload sent for ${sourcePath}`);
      showAutoReloadStatus(document);
    } catch (error) {
      logger.debug('Auto hot reload skipped/failed', { error: String(error) });
    } finally {
      pendingReloads.delete(pendingKey);
    }
  };

  yield vscode.debug.onDidReceiveDebugSessionCustomEvent((event) => {
    if (event.session.type !== 'dapper') {
      return;
    }

    if (event.event === 'stopped') {
      stoppedSessions.add(event.session.id);
      return;
    }

    if (event.event === 'continued' || event.event === 'terminated') {
      stoppedSessions.delete(event.session.id);
    }
  });

  yield vscode.debug.onDidTerminateDebugSession((session) => {
    stoppedSessions.delete(session.id);
  });

  yield vscode.workspace.onDidSaveTextDocument((document) => {
    void tryAutoHotReload(document);
  });

  // Show Debug Panel Command
  yield vscode.commands.registerCommand('dapper.showDebugPanel', async () => {
    logger.log('Executing command: dapper.showDebugPanel');
    try {
      await DapperWebview.createOrShow(context.extensionUri);
      logger.log('Debug panel opened successfully');
    } catch (error) {
      logger.error('Failed to open debug panel', error as Error);
      vscode.window.showErrorMessage('Failed to open debug panel. Check the Dapper Debugger output for details.');
    }
  });

  // Show Variable Inspector Command
  yield vscode.commands.registerCommand('dapper.showVariableInspector', async () => {
    await DapperWebview.createOrShow(context.extensionUri);
    vscode.window.showInformationMessage('Variable inspector is now active');
  });

  // Start Debugging Command
  yield vscode.commands.registerCommand('dapper.startDebugging', async () => {
    const activeEditor = vscode.window.activeTextEditor;
    if (!activeEditor) {
      vscode.window.showErrorMessage('No active editor');
      return;
    }

    const document = activeEditor.document;
    if (document.languageId !== 'python') {
      vscode.window.showErrorMessage('Active document is not a Python file');
      return;
    }

    try {
      await vscode.debug.startDebugging(undefined, {
        type: 'dapper',
        name: 'Dapper Debug',
        request: 'launch',
        program: '${file}',
        cwd: '${workspaceFolder}',
        pythonPath: vscode.workspace.getConfiguration('python').get('pythonPath', 'python'),
        console: 'integratedTerminal',
        stopOnEntry: true
      });
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to start debugging: ${error}`);
    }
  });

  // Launch Configuration Wizard Command
  const openLaunchWizard = async () => {
    try {
      // Get the current workspace folder
      const workspaceFolders = vscode.workspace.workspaceFolders;
      if (!workspaceFolders || workspaceFolders.length === 0) {
        vscode.window.showErrorMessage('No workspace folder is open');
        return;
      }

      // Create or show the webview with configuration wizard
      await DapperWebview.createOrShow(context.extensionUri, 'config');
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to open launch configuration wizard: ${error}`);
    }
  };

  yield vscode.commands.registerCommand('dapper.openLaunchWizard', openLaunchWizard);

  // Backward-compatible alias
  yield vscode.commands.registerCommand('dapper.configureSettings', openLaunchWizard);

  // Toggle Breakpoint Command
    // Add Debug Configuration Command (insert last saved config into launch.json)
    yield vscode.commands.registerCommand('dapper.addDebugConfiguration', async () => {
      try {
        const saved = vscode.workspace.getConfiguration('dapper').get('debug');
        if (!saved) {
          vscode.window.showInformationMessage('No saved configuration found. Use Dapper: Open Launch Configuration Wizard to create one.');
          return;
        }
        const ok = await insertLaunchConfiguration(saved as any);
        if (ok) vscode.window.showInformationMessage('Configuration added to launch.json');
        else vscode.window.showErrorMessage('Failed to insert configuration into launch.json');
      } catch (error) {
        vscode.window.showErrorMessage(`Failed to add debug configuration: ${error}`);
      }
    });

  // Toggle Breakpoint Command
  yield vscode.commands.registerCommand('dapper.toggleBreakpoint', async (file: string, line: number) => {
    try {
      const uri = vscode.Uri.file(file);
      const document = await vscode.workspace.openTextDocument(uri);
      const position = new vscode.Position(line - 1, 0);
      const range = new vscode.Range(position, position);
      
      const existingBreakpoints = vscode.debug.breakpoints.filter((bp: vscode.Breakpoint) => {
        const bpLocation = (bp as vscode.SourceBreakpoint).location;
        return bpLocation && 
               bpLocation.uri.toString() === uri.toString() && 
               bpLocation.range.start.line === position.line;
      });

      if (existingBreakpoints.length > 0) {
        vscode.debug.removeBreakpoints(existingBreakpoints);
      } else {
        const breakpoint = new vscode.SourceBreakpoint(
          new vscode.Location(uri, range)
        );
        vscode.debug.addBreakpoints([breakpoint]);
      }
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to toggle breakpoint: ${error}`);
    }
  });

  // Start Debugging with Saved Config
  yield vscode.commands.registerCommand('dapper.startDebugWithSavedConfig', async () => {
    try {
      const saved = vscode.workspace.getConfiguration('dapper').get('debug');
      if (!saved) {
        vscode.window.showInformationMessage('No saved configuration found. Use Dapper: Open Launch Configuration Wizard to create one.');
        return;
      }
      await vscode.debug.startDebugging(undefined, saved as any);
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to start debug session from saved config: ${error}`);
    }
  });

  // Inspect Variable Command
  yield vscode.commands.registerCommand('dapper.inspectVariable', async (variableName: string) => {
    try {
      if (!vscode.debug.activeDebugSession) {
        vscode.window.showErrorMessage('No active debug session');
        return;
      }
      
      const result = await vscode.debug.activeDebugSession.customRequest('inspectVariable', { name: variableName });
      if (result) {
        vscode.window.showInformationMessage(`${variableName} = ${JSON.stringify(result.value)}`);
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      vscode.window.showErrorMessage(`Failed to inspect variable: ${errorMessage}`);
    }
  });

  // Hot Reload Current File Command
  yield vscode.commands.registerCommand('dapper.hotReload', async () => {
    try {
      const session = vscode.debug.activeDebugSession;
      if (!session) {
        vscode.window.showErrorMessage('No active debug session');
        return;
      }

      if (session.type !== 'dapper') {
        vscode.window.showErrorMessage('Active debug session is not a Dapper session');
        return;
      }

      const editor = vscode.window.activeTextEditor;
      if (!editor) {
        vscode.window.showErrorMessage('No active editor');
        return;
      }

      const document = editor.document;
      if (document.languageId !== 'python' || document.isUntitled) {
        vscode.window.showErrorMessage('Hot reload requires a saved Python file');
        return;
      }

      await document.save();

      const response = await session.customRequest('dapper/hotReload', {
        source: {
          path: document.uri.fsPath,
        },
      });

      const moduleName = response?.reloadedModule ?? document.fileName;
      const reboundFrames = response?.reboundFrames ?? 0;
      const updatedFrameCodes = response?.updatedFrameCodes ?? 0;
      vscode.window.showInformationMessage(
        `Dapper hot reload applied: ${moduleName} (reboundFrames=${reboundFrames}, updatedFrameCodes=${updatedFrameCodes})`,
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      vscode.window.showErrorMessage(`Dapper hot reload failed: ${message}`);
    }
  });
}

function* registerDebugAdapters(context: vscode.ExtensionContext): Iterable<vscode.Disposable> {
  // Register debug configuration provider
  const provider = new DapperConfigurationProvider();
  yield vscode.debug.registerDebugConfigurationProvider('dapper', provider);

  // Register debug adapter descriptor factory
  const factory = new DapperDebugAdapterDescriptorFactory(context);
  yield vscode.debug.registerDebugAdapterDescriptorFactory('dapper', factory);
  yield factory;
}

function* registerWebview(context: vscode.ExtensionContext): Iterable<vscode.Disposable> {
  if (vscode.window.registerWebviewPanelSerializer) {
    yield vscode.window.registerWebviewPanelSerializer('dapperWebview', {
      async deserializeWebviewPanel(webviewPanel: vscode.WebviewPanel) {
        DapperWebview.revive(webviewPanel, context.extensionUri);
      }
    });
  }
}

/**
 * Register all extension disposables and return a single composite Disposable.
 * This aggregates the commands, debug adapters, webview handlers and logger
 * cleanup into one `vscode.Disposable` so the extension host can clean up
 * the entire registration easily.
 */
export function register(context: vscode.ExtensionContext): vscode.Disposable {
  // Collect all disposables that would normally be pushed to context.subscriptions
  const allDisposables: vscode.Disposable[] = [];

  // Logger commands (returns a Disposable)
  const loggerCommandDisposable = registerLoggerCommands(context);
  allDisposables.push(loggerCommandDisposable);

  // Commands
  const commandDisposables = Array.from(registerCommands(context));
  allDisposables.push(...commandDisposables);

  // Debug Adapters
  const debugDisposables = Array.from(registerDebugAdapters(context));
  allDisposables.push(...debugDisposables);

  // Webview serializers / handlers
  const webviewDisposables = Array.from(registerWebview(context));
  allDisposables.push(...webviewDisposables);

  // Add a cleanup disposable (equivalent of the inline object previously pushed)
  const cleanupDisposable = new vscode.Disposable(() => {
    logger.log('Dapper Debugger extension is deactivating...');
    const subscriptionCount = context.subscriptions.length;
    logger.log(`Cleaning up ${subscriptionCount} subscriptions...`);
    logger.dispose();
  });
  allDisposables.push(cleanupDisposable);

  // Return a single composite disposable that encapsulates all the pieces
  return vscode.Disposable.from(...allDisposables);
}

export function activate(context: vscode.ExtensionContext) {
  logger.log('Dapper Debugger extension is activating...');
  logger.log(`Extension version: ${context.extension.packageJSON.version}`);
  logger.log(`VS Code version: ${vscode.version}`);
  logger.log(`Node.js version: ${process.version}`);
  logger.log(`Platform: ${process.platform} ${process.arch}`);
  logger.log(`Extension mode: ${vscode.ExtensionMode[context.extensionMode]}`);
  logger.log(`Extension path: ${context.extension.extensionPath}`);
  logger.log(`Global storage path: ${context.globalStorageUri.fsPath}`);

  try {
    logger.debug('Starting extension initialization...');
    
    // Register everything and put the composite disposable into context.subscriptions
    logger.debug('Registering extension components...');
    const mainDisposable = register(context);
    context.subscriptions.push(mainDisposable);
    logger.log('Extension components registered');

    // Show the output channel on first activation in development
    const isDevelopment = context.extensionMode === vscode.ExtensionMode.Development;
    const isUI = context.extension.extensionKind === vscode.ExtensionKind.UI;
    
    if (isDevelopment && isUI) {
      logger.log('Development mode: Enabling debug logging and showing output channel');
      logger.show();
      
      // Log environment information
      logger.debug('Environment variables:', process.env);
      logger.debug('Extension context:', {
        extensionPath: context.extensionPath,
        globalState: context.globalState.keys(),
        workspaceState: context.workspaceState.keys(),
        storagePath: context.storageUri?.fsPath || 'none',
        logPath: context.logUri.fsPath
      });
    }

    logger.log('Dapper Debugger extension is now active');
  } catch (error) {
    logger.error('Failed to activate Dapper Debugger extension', error as Error);
    vscode.window.showErrorMessage('Failed to activate Dapper Debugger. Check the output for details.');
  }
}

export function deactivate() {
  logger.log('Dapper Debugger extension is now deactivated');
  logger.dispose();
}
