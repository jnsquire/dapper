import * as vscode from 'vscode';
import { DebugConfiguration, ProviderResult, WorkspaceFolder } from 'vscode';
import { DapperWebview } from '../webview/DapperWebview.js';

function createLaunchFileConfiguration(): DebugConfiguration {
  return {
    type: 'dapper',
    request: 'launch',
    name: 'Dapper: Launch ${fileBasename}',
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

function createAttachHostPortConfiguration(): DebugConfiguration {
  return {
    type: 'dapper',
    request: 'attach',
    name: 'Dapper: Attach to Host/Port',
    host: 'localhost',
    port: 5678,
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
  private static readonly _savedSettingBlocklist = new Set([
    'type',
    'request',
    'name',
    'program',
    'module',
    'processId',
    'host',
    'port',
    'pathMappings',
    '__dapperUseWizard',
  ]);

  constructor(extensionUri: vscode.Uri) {
    this._extensionUri = extensionUri;
  }

  private static hasLaunchTarget(config: DebugConfiguration): boolean {
    return DapperConfigurationProvider._countLaunchTargets(config) === 1
      && DapperConfigurationProvider._countAttachTargets(config) === 0;
  }

  private static hasAttachTarget(config: DebugConfiguration): boolean {
    return DapperConfigurationProvider._countAttachTargets(config) === 1
      && DapperConfigurationProvider._countLaunchTargets(config) === 0;
  }

  private static _countLaunchTargets(config: DebugConfiguration): number {
    let count = 0;
    if (typeof config.program === 'string' && config.program.trim()) {
      count += 1;
    }
    const moduleName = (config as Record<string, unknown>).module;
    if (typeof moduleName === 'string' && moduleName.trim()) {
      count += 1;
    }
    return count;
  }

  private static _countAttachTargets(config: DebugConfiguration): number {
    let count = 0;
    const rawProcessId = (config as Record<string, unknown>).processId;
    const hasProcessId = typeof rawProcessId === 'number'
      || (typeof rawProcessId === 'string' && rawProcessId.trim().length > 0);
    if (hasProcessId) {
      count += 1;
    }

    const host = typeof (config as Record<string, unknown>).host === 'string'
      ? String((config as Record<string, unknown>).host).trim()
      : '';
    const rawPort = (config as Record<string, unknown>).port;
    const hasPort = typeof rawPort === 'number'
      || (typeof rawPort === 'string' && rawPort.trim().length > 0);
    if (host && hasPort) {
      count += 1;
    }

    return count;
  }

  private static _countExplicitTargets(config: DebugConfiguration): number {
    return DapperConfigurationProvider._countLaunchTargets(config)
      + DapperConfigurationProvider._countAttachTargets(config);
  }

  private static mergeSavedSettings(target: DebugConfiguration, saved: DebugConfiguration): void {
    for (const key of Object.keys(saved)) {
      if (DapperConfigurationProvider._savedSettingBlocklist.has(key)) {
        continue;
      }
      if ((target as Record<string, unknown>)[key] == null) {
        (target as Record<string, unknown>)[key] = (saved as Record<string, unknown>)[key];
      }
    }
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
      createAttachHostPortConfiguration(),
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

    // When the user selects the wizard entry we expect the configuration to
    // consist only of the magic ``__dapperUseWizard`` flag.  The normal target
    // validation below would reject such a config and short-circuit the
    // process, preventing the wizard from ever opening and producing the
    // confusing "Provide exactly one launch target" message that the user saw.
    // So skip validation in that case and just return the placeholder as-is;
    // it will be handled later in
    // ``resolveDebugConfigurationWithSubstitutedVariables``.
    if ((config as { __dapperUseWizard?: boolean }).__dapperUseWizard) {
      return config;
    }

    if (config.request === 'launch' && !DapperConfigurationProvider.hasLaunchTarget(config)) {
      vscode.window.showInformationMessage('Provide exactly one launch target: program or module.');
      return undefined;
    }

    if (config.request === 'attach' && !DapperConfigurationProvider.hasAttachTarget(config)) {
      vscode.window.showInformationMessage('Provide exactly one attach target: processId or host/port.');
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
    if (config.request === 'launch' && DapperConfigurationProvider._countExplicitTargets(config) === 0) {
      // If the user didn't provide a launch target, fall back to active editor or abort
      const editor = vscode.window.activeTextEditor;
      if (editor && editor.document.languageId === 'python') config.program = '${file}';
      else {
        // Show an informative message and abort launch
        await vscode.window.showInformationMessage('Provide exactly one launch target: program or module.');
        return undefined;
      }
    } else if (config.request === 'launch' && !DapperConfigurationProvider.hasLaunchTarget(config)) {
      await vscode.window.showInformationMessage('Provide exactly one launch target: program or module.');
      return undefined;
    }

    if (config.request === 'attach' && !DapperConfigurationProvider.hasAttachTarget(config)) {
      await vscode.window.showInformationMessage('Provide exactly one attach target: processId or host/port.');
      return undefined;
    }

    // If needed, merge saved settings from workspace configuration
    try {
      const saved = vscode.workspace.getConfiguration('dapper').get('debug') as DebugConfiguration | undefined;
      if (saved) {
        DapperConfigurationProvider.mergeSavedSettings(config, saved);
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
      createAttachHostPortConfiguration(),
      createLaunchWizardConfiguration(),
    ];
  }
}
