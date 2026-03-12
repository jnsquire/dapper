import * as vscode from 'vscode';
import { logger } from '../utils/logger.js';
import { insertLaunchConfiguration } from '../utils/insertLaunchConfiguration.js';
import { getWebviewResourceRoot, renderReactWebviewDocument } from './reactWebviewSupport.js';
import { SingletonWebviewPanelHost, WebviewPanelController } from './singletonWebviewPanel.js';

type WizardStateStore = Pick<vscode.Memento, 'get' | 'update'>;

export class DapperWebview extends WebviewPanelController {
  public static readonly panelViewType = 'dapperWebview';
  private static readonly _wizardDraftKey = 'dapper.launchWizardDraft';
  /** Resolve callback set when the wizard is opened via the Dynamic debug config provider. */
  private static _dynamicProviderResolve: ((config: vscode.DebugConfiguration | undefined) => void) | undefined;
  private static _wizardState: WizardStateStore | undefined;
  private static readonly host = new SingletonWebviewPanelHost<DapperWebview>({
    viewType: DapperWebview.panelViewType,
    title: 'Dapper Launch Configuration Wizard',
    defaultColumn: vscode.ViewColumn.One,
    createPanelOptions: (extensionUri) => ({
      enableScripts: true,
      retainContextWhenHidden: true,
      localResourceRoots: [
        vscode.Uri.joinPath(extensionUri, 'media'),
        getWebviewResourceRoot(extensionUri),
      ],
    }),
    createController: (panel, extensionUri, onDisposed) => new DapperWebview(panel, extensionUri, onDisposed),
  });

  public static get currentPanel(): DapperWebview | undefined {
    return DapperWebview.host.currentPanel;
  }

  public static set currentPanel(value: DapperWebview | undefined) {
    DapperWebview.host.currentPanel = value;
  }

  private constructor(panel: vscode.WebviewPanel, extensionUri: vscode.Uri, onDisposed: () => void) {
    super(panel, extensionUri, onDisposed);
  }

  public static initialize(state?: WizardStateStore): void {
    DapperWebview._wizardState = state;
  }

  private static _cloneConfig<T>(config: T): T {
    return JSON.parse(JSON.stringify(config)) as T;
  }

  private static getStoredWizardDraft(): vscode.DebugConfiguration | undefined {
    try {
      const draft = DapperWebview._wizardState?.get<vscode.DebugConfiguration>(DapperWebview._wizardDraftKey);
      return draft ? DapperWebview._cloneConfig(draft) : undefined;
    } catch (error) {
      logger.warn('Failed to read wizard draft', error);
      return undefined;
    }
  }

  private static async persistWizardDraft(config: vscode.DebugConfiguration): Promise<void> {
    if (!DapperWebview._wizardState) {
      return;
    }

    try {
      await DapperWebview._wizardState.update(
        DapperWebview._wizardDraftKey,
        DapperWebview._cloneConfig(config),
      );
    } catch (error) {
      logger.warn('Failed to persist wizard draft', error);
    }
  }

  /**
   * Open the configuration wizard and wait for the user to confirm a configuration.
   * Used by {@link DapperDynamicConfigurationProvider} to satisfy the Dynamic
   * `DebugConfigurationProviderTriggerKind` hook in the run/debug UI.
   *
   * Resolves with the confirmed {@link vscode.DebugConfiguration}, or `undefined`
   * if the user closes the wizard without confirming.
   */
  public static showAndWaitForConfig(
    extensionUri: vscode.Uri
  ): Promise<vscode.DebugConfiguration | undefined> {
    // If a previous call is still pending, cancel it immediately.
    DapperWebview._dynamicProviderResolve?.(undefined);

    return new Promise((resolve) => {
      DapperWebview._dynamicProviderResolve = resolve;
      // providerMode is communicated to the webview via the updateConfig response to
      // requestConfig (sent by the React app on mount), avoiding a timing race.
      void DapperWebview.show(extensionUri);
    });
  }

  public static async show(extensionUri: vscode.Uri): Promise<void> {
    logger.debug('Creating or showing launch wizard webview');
    if (DapperWebview.currentPanel) {
      logger.debug('Revealing existing launch wizard webview panel');
    } else {
      logger.debug(`Creating new webview panel with id: ${DapperWebview.panelViewType}`);
    }
    DapperWebview.host.show(extensionUri);
    logger.log('Successfully created and initialized launch wizard webview');
  }

  public static registerSerializer(extensionUri: vscode.Uri): vscode.Disposable | undefined {
    return DapperWebview.host.registerSerializer(extensionUri);
  }

  protected get title(): string {
    return 'Dapper Launch Configuration Wizard';
  }

  protected render(): string {
    return renderReactWebviewDocument({
      webview: this.panel.webview,
      extensionUri: this.extensionUri,
      title: 'Dapper Launch Configuration Wizard',
      stylesheets: ['styles/webview/styles.css'],
      scripts: [
        { path: 'vendor/bundled.js', module: true },
        { path: 'webview/pages/ConfigView.js', module: true },
      ],
    });
  }

  protected registerMessageHandlers(): void {
    const postStatus = (text: string) => {
      this.panel.webview.postMessage({ command: 'updateStatus', text });
    };
    const saveDefaultConfig = async (cfg: vscode.DebugConfiguration) => {
      await vscode.workspace.getConfiguration('dapper').update('debug', cfg, true);
    };

    this.registerDisposable(this.panel.webview.onDidReceiveMessage(async (message) => {
      if (message.config) {
        await DapperWebview.persistWizardDraft(message.config as vscode.DebugConfiguration);
      }

      switch (message.command) {
              case 'saveConfig':
                try {
                  await saveDefaultConfig(message.config as vscode.DebugConfiguration);
                  vscode.window.showInformationMessage('Default Dapper configuration saved');
                  postStatus('Saved as the default Dapper configuration in VS Code setting dapper.debug.');
                } catch (err) {
                  logger.error('Failed to save configuration', err as Error);
                  vscode.window.showErrorMessage('Failed to save configuration');
                  postStatus('Failed to save configuration.');
                }
                break;
              case 'requestConfig':
                // Respond with the saved configuration or default.
                try {
                  const draft = DapperWebview.getStoredWizardDraft();
                  const saved = vscode.workspace.getConfiguration('dapper').get('debug');
                  this.panel.webview.postMessage({
                    command: 'updateConfig',
                    config: draft || saved || {},
                    providerMode: DapperWebview._dynamicProviderResolve !== undefined,
                  });
                } catch (err) {
                  logger.error('Failed to read saved configuration', err as Error);
                  this.panel.webview.postMessage({
                    command: 'updateConfig',
                    config: {},
                    providerMode: DapperWebview._dynamicProviderResolve !== undefined,
                  });
                }
                break;
              case 'draftConfigChanged':
                // draft already persisted above
                break;
              case 'saveAndInsert':
                try {
                  await saveDefaultConfig(message.config as vscode.DebugConfiguration);
                  const ok = await insertLaunchConfiguration(message.config as any);
                  if (ok) {
                    vscode.window.showInformationMessage('Configuration inserted into launch.json');
                    postStatus('Saved as the default Dapper configuration and inserted into .vscode/launch.json.');
                  } else {
                    postStatus('Failed to insert configuration into launch.json');
                  }
                } catch (err) {
                  logger.error('Failed to save and insert configuration', err as Error);
                  vscode.window.showErrorMessage('Failed to save and insert configuration');
                  postStatus('Failed to insert configuration into launch.json');
                }
                break;
              case 'saveAndLaunch':
                try {
                  await saveDefaultConfig(message.config as vscode.DebugConfiguration);
                  const ok = await insertLaunchConfiguration(message.config as any);
                  if (!ok) {
                    postStatus('Failed to insert configuration into launch.json');
                    break;
                  }

                  if (DapperWebview._dynamicProviderResolve) {
                    postStatus('Saved as the default Dapper configuration, inserted into .vscode/launch.json, and launching.');
                    DapperWebview._dynamicProviderResolve(message.config as vscode.DebugConfiguration);
                    DapperWebview._dynamicProviderResolve = undefined;
                    this.panel.dispose();
                    break;
                  }

                  const started = await vscode.debug.startDebugging(undefined, message.config);
                  if (started) {
                    postStatus('Saved as the default Dapper configuration, inserted into .vscode/launch.json, and launched.');
                  } else {
                    vscode.window.showErrorMessage('Failed to start debugging');
                    postStatus('Saved to .vscode/launch.json, but VS Code did not start the debug session.');
                  }
                } catch (err) {
                  logger.error('Failed to save, insert, and launch configuration', err as Error);
                  vscode.window.showErrorMessage('Failed to save and launch configuration');
                  postStatus('Failed to save, insert, and launch configuration.');
                }
                break;
              case 'startDebug':
                try {
                  await vscode.debug.startDebugging(undefined, message.config);
                } catch (err) {
                  logger.error('Failed to start debug session from webview', err as Error);
                  vscode.window.showErrorMessage('Failed to start debugging');
                }
                break;
              case 'confirmConfig':
                // Sent by the wizard when invoked from the Dynamic debug config provider.
                // Resolve the waiting provideDebugConfigurations promise, then close the panel.
                if (DapperWebview._dynamicProviderResolve) {
                  DapperWebview._dynamicProviderResolve(message.config as vscode.DebugConfiguration);
                  DapperWebview._dynamicProviderResolve = undefined;
                }
                this.panel.dispose();
                break;
              case 'cancelConfig':
                // Close the webview
                this.panel.dispose();
                break;
      }
    }));
  }

  protected override onPanelDisposed(): void {
    logger.debug('Disposing launch wizard webview');

    // If the wizard was opened via the Dynamic config provider and the user closes it
    // without confirming, resolve the pending promise with undefined (cancellation).
    DapperWebview._dynamicProviderResolve?.(undefined);
    DapperWebview._dynamicProviderResolve = undefined;

    logger.log('Webview cleanup completed');
  }

  public static revive(panel: vscode.WebviewPanel, extensionUri: vscode.Uri) {
    DapperWebview.host.revive(panel, extensionUri);
  }
}
