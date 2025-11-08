import * as vscode from 'vscode';
import { DapperDebugAdapterDescriptorFactory } from './debugAdapter/dapperDebugAdapter.js';
import { DapperConfigurationProvider } from './debugAdapter/configurationProvider.js';
import { DapperWebview } from './webview/DapperWebview.js';
import { logger, registerLoggerCommands } from './utils/logger.js';

function* registerCommands(context: vscode.ExtensionContext): Iterable<vscode.Disposable> {
  logger.log('Registering Dapper Debugger commands');
  // Show Debug Panel Command
  yield vscode.commands.registerCommand('dapper.showDebugPanel', () => {
    logger.log('Executing command: dapper.showDebugPanel');
    try {
      DapperWebview.createOrShow(context.extensionUri);
      logger.log('Debug panel opened successfully');
    } catch (error) {
      logger.error('Failed to open debug panel', error as Error);
      vscode.window.showErrorMessage('Failed to open debug panel. Check the Dapper Debugger output for details.');
    }
  });

  // Show Variable Inspector Command
  yield vscode.commands.registerCommand('dapper.showVariableInspector', () => {
    DapperWebview.createOrShow(context.extensionUri);
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
      DapperWebview.createOrShow(context.extensionUri, 'config');
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to open settings: ${error}`);
    }
  });

  // Toggle Breakpoint Command
  yield vscode.commands.registerCommand('dapper.toggleBreakpoint', async (file: string, line: number) => {
    try {
      const uri = vscode.Uri.file(file);
      const document = await vscode.workspace.openTextDocument(uri);
      const position = new vscode.Position(line - 1, 0);
      const range = new vscode.Range(position, position);
      
      const existingBreakpoints = vscode.debug.breakpoints.filter(bp => {
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

function* registerDebugAdapters(): Iterable<vscode.Disposable> {
  // Register debug configuration provider
  const provider = new DapperConfigurationProvider();
  yield vscode.debug.registerDebugConfigurationProvider('dapper', provider);

  // Register debug adapter descriptor factory
  const factory = new DapperDebugAdapterDescriptorFactory();
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
    
    // Register logger commands
    logger.debug('Registering logger commands...');
    registerLoggerCommands(context);
    
    // Register all commands
    logger.debug('Registering extension commands...');
    const commandDisposables = Array.from(registerCommands(context));
    commandDisposables.forEach(disposable => context.subscriptions.push(disposable));
    logger.log(`Registered ${commandDisposables.length} command handlers`);

    // Register debug adapters
    logger.debug('Registering debug adapters...');
    const debugDisposables = Array.from(registerDebugAdapters());
    debugDisposables.forEach(disposable => context.subscriptions.push(disposable));
    logger.log(`Registered ${debugDisposables.length} debug adapters`);

    // Register webview
    logger.debug('Registering webview...');
    const webviewDisposables = Array.from(registerWebview(context));
    webviewDisposables.forEach(disposable => context.subscriptions.push(disposable));
    logger.log(`Registered ${webviewDisposables.length} webview handlers`);

    // Register logger for cleanup
    context.subscriptions.push({
      dispose: () => {
        logger.log('Dapper Debugger extension is deactivating...');
        const subscriptionCount = context.subscriptions.length;
        logger.log(`Cleaning up ${subscriptionCount} subscriptions...`);
        logger.dispose();
      }
    });

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
