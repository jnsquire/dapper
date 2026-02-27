import * as vscode from 'vscode';
import { logger } from '../utils/logger.js';
import { insertLaunchConfiguration } from '../utils/insertLaunchConfiguration.js';
import { IViewComponent } from './components/BaseView.js';
import { DebugView } from './components/debug/DebugView.js';

// Type for view components
type ViewType = 'debug' | 'config';

export class DapperWebview {
  public static currentPanel: DapperWebview | undefined;
  /** Resolve callback set when the wizard is opened via the Dynamic debug config provider. */
  private static _dynamicProviderResolve: ((config: vscode.DebugConfiguration | undefined) => void) | undefined;
  private readonly _panel: vscode.WebviewPanel;
  private _disposables: vscode.Disposable[] = [];
  private _extensionUri: vscode.Uri;
  private _viewType: ViewType = 'debug';
  private _viewComponent: IViewComponent | null = null;

  private constructor(panel: vscode.WebviewPanel, extensionUri: vscode.Uri) {
    this._panel = panel;
    this._extensionUri = extensionUri;
    this._panel.onDidDispose(() => this.dispose(), null, this._disposables);
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
      void DapperWebview.createOrShow(extensionUri, 'config');
    });
  }

  public static async createOrShow(extensionUri: vscode.Uri, viewType: 'debug' | 'config' = 'debug') {
    logger.debug(`Creating or showing ${viewType} webview`);
    
    const column = vscode.window.activeTextEditor
      ? vscode.window.activeTextEditor.viewColumn
      : undefined;

    const title = viewType === 'config' ? 'Dapper Launch Configuration Wizard' : 'Dapper Debugger';
    const panelId = `dapperWebview.${viewType}`;

    // If we already have a panel with the same view type, show it
    if (DapperWebview.currentPanel) {
      if (DapperWebview.currentPanel._panel.viewType === panelId) {
        logger.debug(`Revealing existing ${viewType} webview panel`);
        DapperWebview.currentPanel._panel.reveal(column);
        return;
      } else {
        // If we have a different view type, dispose it
        logger.debug(`Disposing existing ${DapperWebview.currentPanel._viewType} webview to show ${viewType} view`);
        DapperWebview.currentPanel.dispose();
      }
    }

    logger.debug(`Creating new webview panel with id: ${panelId}`);
    const panel = vscode.window.createWebviewPanel(
      panelId,
      title,
      column || vscode.ViewColumn.One,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [
          vscode.Uri.joinPath(extensionUri, 'media'),
          vscode.Uri.joinPath(extensionUri, 'out/compiled'),
          vscode.Uri.joinPath(extensionUri, 'node_modules', '@vscode-elements', 'elements', 'dist')
        ]
      }
    );

    logger.debug(`Initializing new ${viewType} webview instance`);
    DapperWebview.currentPanel = new DapperWebview(panel, extensionUri);
    await DapperWebview.currentPanel.setViewType(viewType);
    logger.log(`Successfully created and initialized ${viewType} webview`);
  }

  private async setViewType(viewType: ViewType) {
    logger.debug(`Setting webview type to: ${viewType}`);
    this._viewType = viewType;
    
    // Update panel title based on view type
    const newTitle = viewType === 'config' ? 'Dapper Launch Configuration Wizard' : 'Dapper Debugger';
    this._panel.title = newTitle;
    logger.debug(`Updated webview title to: ${newTitle}`);
    
    // Load the appropriate view component
    await this.loadViewComponent(viewType);
  }

  private async loadViewComponent(viewType: ViewType) {
    logger.debug(`Loading ${viewType} view component`);
    try {
      // In a real implementation, you would dynamically import the component
      // For now, we'll use a simple switch
      let component: IViewComponent;
      
      switch (viewType) {
        case 'debug':
          logger.debug('Creating debug view component');
          component = new DebugView(this._panel, this._extensionUri);
          break;
        case 'config':
        default:
          logger.debug('Creating config view component');
          component = await this.createConfigView();
          break;
      }
      
      this._viewComponent = component;
      logger.debug('Rendering view component HTML');
      this._panel.webview.html = component.render();
      logger.debug('Setting up view component message handlers');
      component.setupMessageHandlers(this._panel);
      
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      logger.error('Failed to load view component', error);
      this._panel.webview.html = `
        <html>
          <body>
            <h2>Error loading view</h2>
            <p>${errorMessage}</p>
          </body>
        </html>`;
    }
  }

  private async createConfigView(): Promise<IViewComponent> {
    // In a real implementation, you would import the actual component
    const nonce = String(Date.now());
    const configScriptUri = this.getWebviewUri('webview/views/config/ConfigView.js');
    const stylesUri = this.getWebviewUri('styles/webview/styles.css');
    const elementsUri = this._panel.webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, 'node_modules', '@vscode-elements', 'elements', 'dist', 'bundled.js')
    );
    return {
      render: () => `
        <!doctype html>
        <html>
          <head>
            <meta charset="UTF-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1.0" />
            <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${this._panel.webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}'; img-src ${this._panel.webview.cspSource} https: data:; font-src ${this._panel.webview.cspSource};" />
            <title>Dapper Launch Configuration Wizard</title>
            <link rel="stylesheet" href="${stylesUri}" />
            <script type="module" nonce="${nonce}" src="${elementsUri}"></script>
            <script type="module" nonce="${nonce}" src="${configScriptUri}"></script>
          </head>
          <body>
            <div id="root"></div>
          </body>
        </html>`,
      setupMessageHandlers: (panel: vscode.WebviewPanel) => {
        // Setup config view message handlers
        panel.webview.onDidReceiveMessage(
          async (message) => {
            switch (message.command) {
              case 'saveConfig':
                // Handle config save
                await vscode.workspace.getConfiguration('dapper').update('debug', message.config, true);
                vscode.window.showInformationMessage('Configuration saved');
                break;
              case 'requestConfig':
                // Respond with the saved configuration or default.
                // Include providerMode so the wizard knows it was opened from the
                // Dynamic debug-config provider (reliable: sent in response to the
                // webview's own mount-time message, so the listener is always ready).
                try {
                  const saved = vscode.workspace.getConfiguration('dapper').get('debug');
                  panel.webview.postMessage({
                    command: 'updateConfig',
                    config: saved || {},
                    providerMode: DapperWebview._dynamicProviderResolve !== undefined,
                  });
                } catch (err) {
                  logger.error('Failed to read saved configuration', err as Error);
                  panel.webview.postMessage({
                    command: 'updateConfig',
                    config: {},
                    providerMode: DapperWebview._dynamicProviderResolve !== undefined,
                  });
                }
                break;
              case 'saveAndInsert':
                try {
                  await vscode.workspace.getConfiguration('dapper').update('debug', message.config, true);
                  // Insert into launch.json
                  const ok = await insertLaunchConfiguration(message.config as any);
                  if (ok) {
                    vscode.window.showInformationMessage('Configuration inserted into launch.json');
                    panel.webview.postMessage({ command: 'updateStatus', text: 'Configuration inserted into launch.json' });
                  } else {
                    panel.webview.postMessage({ command: 'updateStatus', text: 'Failed to insert configuration into launch.json' });
                  }
                } catch (err) {
                  logger.error('Failed to save and insert configuration', err as Error);
                  vscode.window.showErrorMessage('Failed to save and insert configuration');
                  panel.webview.postMessage({ command: 'updateStatus', text: 'Failed to insert configuration into launch.json' });
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
                panel.dispose();
                break;
              case 'cancelConfig':
                // Close the webview
                panel.dispose();
                break;
            }
          },
          null,
          this._disposables
        );
      }
    };
  }

  private getWebviewUri(webviewPath: string): vscode.Uri {
    return this._panel.webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, 'out', 'compiled', webviewPath)
    );
  }

  public dispose() {
    logger.debug(`Disposing ${this._viewType} webview`);
    DapperWebview.currentPanel = undefined;

    // If the wizard was opened via the Dynamic config provider and the user closes it
    // without confirming, resolve the pending promise with undefined (cancellation).
    DapperWebview._dynamicProviderResolve?.(undefined);
    DapperWebview._dynamicProviderResolve = undefined;

    // Clean up our resources
    this._panel.dispose();
    logger.debug('Webview panel disposed');

    while (this._disposables.length) {
      const disposable = this._disposables.pop();
      if (disposable) {
        try {
          disposable.dispose();
        } catch (error) {
          logger.warn('Error while disposing webview resource', error);
        }
      }
    }
    logger.log('Webview cleanup completed');
  }

  public static revive(panel: vscode.WebviewPanel, extensionUri: vscode.Uri) {
    DapperWebview.currentPanel = new DapperWebview(panel, extensionUri);
  }
}
