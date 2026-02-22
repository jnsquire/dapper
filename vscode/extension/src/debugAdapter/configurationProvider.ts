import * as vscode from 'vscode';
import { DebugConfiguration, ProviderResult, WorkspaceFolder } from 'vscode';

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
