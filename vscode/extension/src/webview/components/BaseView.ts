import * as vscode from 'vscode';

export interface IViewComponent {
  render(): string;
  setupMessageHandlers(panel: vscode.WebviewPanel): void;
  dispose?(): void;
}

export abstract class BaseView implements IViewComponent {
  protected disposables: vscode.Disposable[] = [];
  protected panel: vscode.WebviewPanel;
  protected extensionUri: vscode.Uri;

  constructor(panel: vscode.WebviewPanel, extensionUri: vscode.Uri) {
    this.panel = panel;
    this.extensionUri = extensionUri;
  }

  abstract render(): string;
  abstract setupMessageHandlers(panel: vscode.WebviewPanel): void;

  protected getWebviewUri(...pathSegments: string[]): vscode.Uri {
    return this.panel.webview.asWebviewUri(
      vscode.Uri.joinPath(this.extensionUri, ...pathSegments)
    );
  }

  public dispose() {
    this.disposables.forEach(d => d.dispose());
    this.disposables = [];
  }
}
