import * as vscode from 'vscode';
import { logger } from '../utils/logger.js';
import { insertLaunchConfiguration } from '../utils/insertLaunchConfiguration.js';
import { IViewComponent } from './components/BaseView.js';

// Type for view components
type ViewType = 'debug' | 'config';

export class DapperWebview {
  public static currentPanel: DapperWebview | undefined;
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

  public static async createOrShow(extensionUri: vscode.Uri, viewType: 'debug' | 'config' = 'debug') {
    logger.debug(`Creating or showing ${viewType} webview`);
    
    const column = vscode.window.activeTextEditor
      ? vscode.window.activeTextEditor.viewColumn
      : undefined;

    const title = viewType === 'config' ? 'Dapper Settings' : 'Dapper Debugger';
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
          vscode.Uri.joinPath(extensionUri, 'out/compiled')
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
    const newTitle = viewType === 'config' ? 'Dapper Settings' : 'Dapper Debugger';
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
          // TODO: Implement debug view component
          logger.debug('Creating debug view component (falling back to config view)');
          component = await this.createConfigView();
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
    return {
      render: () => `
        <html>
          <head>
            <title>Dapper Settings</title>
            <script type="module" src="${this.getWebviewUri('config.js')}"></script>
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
                // Respond with the saved configuration or default
                try {
                  const saved = vscode.workspace.getConfiguration('dapper').get('debug');
                  panel.webview.postMessage({ command: 'updateConfig', config: saved || {} });
                } catch (err) {
                  logger.error('Failed to read saved configuration', err as Error);
                  panel.webview.postMessage({ command: 'updateConfig', config: {} });
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
