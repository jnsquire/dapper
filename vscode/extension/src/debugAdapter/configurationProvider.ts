import * as vscode from 'vscode';
import { DebugConfiguration, ProviderResult, WorkspaceFolder } from 'vscode';
import { DapperWebview } from '../webview/DapperWebview.js';

export class DapperConfigurationProvider implements vscode.DebugConfigurationProvider {
  private static hasLaunchTarget(config: DebugConfiguration): boolean {
    return Boolean(config.program || (config as Record<string, unknown>).module);
  }

  provideDebugConfigurations(folder: WorkspaceFolder | undefined): ProviderResult<DebugConfiguration[]> {
    try {
      const saved = vscode.workspace.getConfiguration('dapper').get('debug') as DebugConfiguration | undefined;
      if (saved) return [saved];
    } catch (err) {
      // Ignore and fall back to default
    }
    // Fallback to a simple default
    return [
      {
        type: 'dapper',
        request: 'launch',
        name: 'Dapper: Launch File',
        program: '${file}',
        console: 'integratedTerminal'
      }
    ];
  }
  resolveDebugConfiguration(
    folder: WorkspaceFolder | undefined,
    config: DebugConfiguration
  ): DebugConfiguration | undefined {
    // If no launch.json exists, we create a default configuration
    if (!config.type && !config.request && !config.name) {
      const editor = vscode.window.activeTextEditor;
      if (editor && editor.document.languageId === 'python') {
        config.type = 'dapper';
        config.name = 'Launch Python with Dapper';    
        config.request = 'launch';
        config.program = '${file}';
        config.console = 'integratedTerminal';
        config.stopOnEntry = true;
      }
    }

    if (config.request === 'launch' && !DapperConfigurationProvider.hasLaunchTarget(config)) {
      vscode.window.showInformationMessage('Cannot find a program or module to debug');
      return undefined;
    }

    return config;
  }

  async resolveDebugConfigurationWithSubstitutedVariables(
    folder: WorkspaceFolder | undefined,
    config: DebugConfiguration,
    token?: vscode.CancellationToken
  ): Promise<DebugConfiguration | undefined> {
    // If no launch config fields are present, keep existing behavior
    if (!config || Object.keys(config).length === 0) {
      const res = await this.resolveDebugConfiguration(folder, config as DebugConfiguration);
      return res ?? undefined;
    }

    // Fill a few basic defaults
    if (!config.type) config.type = 'dapper';
    if (!config.request) config.request = 'launch';
    if (!config.name) config.name = 'Dapper: Launch';
    if (config.request === 'launch' && !DapperConfigurationProvider.hasLaunchTarget(config)) {
      // If the user didn't provide a launch target, fall back to active editor or abort
      const editor = vscode.window.activeTextEditor;
      if (editor && editor.document.languageId === 'python') config.program = '${file}';
      else {
        // Show an informative message and abort launch
        await vscode.window.showInformationMessage('Cannot find a program or module to debug');
        return undefined;
      }
    }

    // If needed, merge saved settings from workspace configuration
    try {
      const saved = vscode.workspace.getConfiguration('dapper').get('debug') as DebugConfiguration | undefined;
      if (saved) {
        // Merge missing properties from saved config
        for (const k of Object.keys(saved)) {
          if ((config as any)[k] == null) (config as any)[k] = (saved as any)[k];
        }
      }
    } catch (err) {
      // Ignore and continue with provided config
    }

    return config;
  }
}

/**
 * Registered with {@link vscode.DebugConfigurationProviderTriggerKind.Dynamic} so that VS Code
 * calls `provideDebugConfigurations` when the user opens the run/debug picker and asks for
 * dynamically-generated configurations (e.g. via "Select and Start Debugging").
 *
 * Instead of returning a static list, we open the Dapper Launch Configuration Wizard and wait
 * for the user to confirm their settings.  When the wizard emits a `confirmConfig` message the
 * promise resolves and VS Code receives the configured launch configuration.  If the user closes
 * the wizard without confirming, the call resolves to an empty array so VS Code hides the picker
 * entry gracefully.
 */
export class DapperDynamicConfigurationProvider implements vscode.DebugConfigurationProvider {
  private readonly _extensionUri: vscode.Uri;

  constructor(extensionUri: vscode.Uri) {
    this._extensionUri = extensionUri;
  }

  async provideDebugConfigurations(
    _folder: WorkspaceFolder | undefined,
    _token?: vscode.CancellationToken
  ): Promise<DebugConfiguration[]> {
    const config = await DapperWebview.showAndWaitForConfig(this._extensionUri);
    return config ? [config] : [];
  }
}
