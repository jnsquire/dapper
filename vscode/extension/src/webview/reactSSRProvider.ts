import * as vscode from 'vscode';
import * as path from 'path';
import * as React from 'react';
import * as ReactDOMServer from 'react-dom/server';
import { VariableInspector } from '../ui/components/VariableInspector.js';

export class ReactSSRProvider {
  public static readonly viewType = 'dapper.variableInspector';
  
  private static instance: ReactSSRProvider | undefined;
  private panel: vscode.WebviewPanel | undefined;
  private readonly extensionUri: vscode.Uri;

  private constructor(extensionUri: vscode.Uri) {
    this.extensionUri = extensionUri;
  }

  public static createOrShow(extensionUri: vscode.Uri): ReactSSRProvider {
    if (!ReactSSRProvider.instance) {
      ReactSSRProvider.instance = new ReactSSRProvider(extensionUri);
    }
    ReactSSRProvider.instance.show();
    return ReactSSRProvider.instance;
  }

  private show() {
    const column = vscode.window.activeTextEditor
      ? vscode.window.activeTextEditor.viewColumn
      : undefined;

    if (!this.panel) {
      this.panel = vscode.window.createWebviewPanel(
        ReactSSRProvider.viewType,
        'Dapper Variable Inspector',
        column || vscode.ViewColumn.Two,
        {
          enableScripts: true,
          retainContextWhenHidden: true,
          localResourceRoots: [
            vscode.Uri.file(path.join(this.extensionUri.fsPath, 'out', 'webview'))
          ]
        }
      );

      this.panel.onDidDispose(() => {
        this.panel = undefined;
      }, null);
    }

    this.updateWebview();
  }

  private updateWebview() {
    if (!this.panel) {
      return;
    }

    // Render React component to string
    const html = this.getWebviewContent({
      title: 'Dapper Variable Inspector',
      body: ReactDOMServer.renderToString(
        React.createElement(VariableInspector, { variables: [] })
      ),
      scriptUri: this.getWebviewUri('webview.js'),
      stylesUri: this.getWebviewUri('styles.css')
    });

    this.panel.webview.html = html;
  }

  private getWebviewUri(webviewPath: string): vscode.Uri {
    return this.panel!.webview.asWebviewUri(
      vscode.Uri.file(
        path.join(this.extensionUri.fsPath, 'out', 'webview', webviewPath)
      )
    );
  }

  private getWebviewContent(params: {
    title: string;
    body: string;
    scriptUri: vscode.Uri;
    stylesUri: vscode.Uri;
  }): string {
    return `
      <!DOCTYPE html>
      <html lang="en">
      <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>${params.title}</title>
        <link href="${params.stylesUri}" rel="stylesheet">
      </head>
      <body>
        <div id="root">${params.body}</div>
        <script src="${params.scriptUri}"></script>
      </body>
      </html>
    `;
  }
}
