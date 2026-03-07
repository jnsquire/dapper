import * as vscode from 'vscode';
import { DebugConfiguration, ProviderResult, WorkspaceFolder } from 'vscode';
import { DapperWebview } from '../webview/DapperWebview.js';

function createLaunchFileConfiguration(): DebugConfiguration {
  return {
    type: 'dapper',
    request: 'launch',
    name: 'Dapper: Launch Current Python File',
    program: '${file}',
    console: 'integratedTerminal',
  };
}

function createLaunchModuleConfiguration(): DebugConfiguration {
  return {
    type: 'dapper',
    request: 'launch',
    name: 'Dapper: Launch Python Module',
    module: 'package.module',
    args: [],
    console: 'integratedTerminal',
  };
}

function createAttachByPidConfiguration(): DebugConfiguration {
  return {
    type: 'dapper',
    request: 'attach',
    name: 'Dapper: Attach by PID',
    processId: '${command:pickProcess}',
    justMyCode: true,
  };
}

function createLaunchWizardConfiguration(): DebugConfiguration {
  return {
    type: 'dapper',
    request: 'launch',
    name: 'Dapper: Configure via Wizard',
    __dapperUseWizard: true,
  } satisfies DebugConfiguration & { __dapperUseWizard: true };
}

export class DapperConfigurationProvider implements vscode.DebugConfigurationProvider {
  private readonly _extensionUri: vscode.Uri;

  constructor(extensionUri: vscode.Uri) {
    this._extensionUri = extensionUri;
  }

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
    return [
      createLaunchFileConfiguration(),
      createAttachByPidConfiguration(),
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
    if ((config as { __dapperUseWizard?: boolean }).__dapperUseWizard) {
      const resolved = await DapperWebview.showAndWaitForConfig(this._extensionUri);
      return resolved ?? undefined;
    }

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
 * We return a small set of Python-oriented Dapper configurations so the picker can offer
 * immediate launch and attach-by-PID choices without requiring the user to hand-author JSON.
 * The wizard remains available as an explicit generated entry for users who want a richer setup flow.
 */
export class DapperDynamicConfigurationProvider implements vscode.DebugConfigurationProvider {
  async provideDebugConfigurations(
    _folder: WorkspaceFolder | undefined,
    _token?: vscode.CancellationToken
  ): Promise<DebugConfiguration[]> {
    return [
      createLaunchFileConfiguration(),
      createLaunchModuleConfiguration(),
      createAttachByPidConfiguration(),
      createLaunchWizardConfiguration(),
    ];
  }
}
