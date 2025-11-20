import * as vscode from 'vscode';
import { DapperDebugAdapterDescriptorFactory } from './debugAdapter/dapperDebugAdapter.js';
import { DapperConfigurationProvider } from './debugAdapter/configurationProvider.js';
import { DapperWebview } from './webview/DapperWebview.js';
import { logger, registerLoggerCommands } from './utils/logger.js';
import { insertLaunchConfiguration } from './utils/insertLaunchConfiguration.js';

function* registerCommands(context: vscode.ExtensionContext): Iterable<vscode.Disposable> {
  logger.log('Registering Dapper Debugger commands');
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

  // Configure Settings Command
  yield vscode.commands.registerCommand('dapper.configureSettings', async () => {
    try {
      // Get the current workspace folder
      const workspaceFolders = vscode.workspace.workspaceFolders;
      if (!workspaceFolders || workspaceFolders.length === 0) {
        vscode.window.showErrorMessage('No workspace folder is open');
        return;
      }

      // Create or show the webview with configuration
      await DapperWebview.createOrShow(context.extensionUri, 'config');
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to open settings: ${error}`);
    }
  });

  // Toggle Breakpoint Command
    // Add Debug Configuration Command (insert last saved config into launch.json)
    yield vscode.commands.registerCommand('dapper.addDebugConfiguration', async () => {
      try {
        const saved = vscode.workspace.getConfiguration('dapper').get('debug');
        if (!saved) {
          vscode.window.showInformationMessage('No saved configuration found. Use Dapper: Configure Settings to create one.');
          return;
        }
        const ok = await insertLaunchConfiguration(saved as any);
        if (ok) vscode.window.showInformationMessage('Configuration added to launch.json');
        else vscode.window.showErrorMessage('Failed to insert configuration into launch.json');
      } catch (error) {
        vscode.window.showErrorMessage(`Failed to add debug configuration: ${error}`);
      }
    });
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
        vscode.window.showInformationMessage('No saved configuration found. Use Dapper: Configure Settings to create one.');
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
