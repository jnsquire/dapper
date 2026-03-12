import * as vscode from 'vscode';

export type WebviewPanelControllerFactory<T extends WebviewPanelController> = (
  panel: vscode.WebviewPanel,
  extensionUri: vscode.Uri,
  onDisposed: () => void,
) => T;

export interface SingletonWebviewPanelHostOptions<T extends WebviewPanelController> {
  viewType: string;
  title: string;
  defaultColumn?: vscode.ViewColumn;
  createPanelOptions: (extensionUri: vscode.Uri) => vscode.WebviewPanelOptions & vscode.WebviewOptions;
  createController: WebviewPanelControllerFactory<T>;
}

export abstract class WebviewPanelController implements vscode.Disposable {
  private readonly disposables: vscode.Disposable[] = [];
  private isDisposed = false;

  protected constructor(
    protected readonly panel: vscode.WebviewPanel,
    protected readonly extensionUri: vscode.Uri,
    private readonly onDisposed: () => void,
  ) {
    this.registerDisposable(this.panel.onDidDispose(() => this.handlePanelDisposed()));
  }

  protected abstract get title(): string;
  protected abstract render(): string;
  protected abstract registerMessageHandlers(): void;

  public initialize(): void {
    this.panel.title = this.title;
    this.panel.webview.html = this.render();
    this.registerMessageHandlers();
  }

  public reveal(column?: vscode.ViewColumn): void {
    this.panel.reveal(column);
  }

  public dispose(): void {
    if (!this.isDisposed) {
      this.panel.dispose();
    }
  }

  protected registerDisposable<T extends vscode.Disposable>(disposable: T): T {
    this.disposables.push(disposable);
    return disposable;
  }

  protected onPanelDisposed(): void {
    // subclasses can override to perform extra cleanup
  }

  private handlePanelDisposed(): void {
    if (this.isDisposed) {
      return;
    }

    this.isDisposed = true;
    this.onDisposed();
    this.onPanelDisposed();

    while (this.disposables.length) {
      this.disposables.pop()?.dispose();
    }
  }
}

export class SingletonWebviewPanelHost<T extends WebviewPanelController> {
  public currentPanel: T | undefined;
  private readonly options: SingletonWebviewPanelHostOptions<T>;

  constructor(options: SingletonWebviewPanelHostOptions<T>) {
    this.options = options;
  }

  public show(extensionUri: vscode.Uri): T {
    const column = vscode.window.activeTextEditor?.viewColumn;
    if (this.currentPanel) {
      this.currentPanel.reveal(column);
      return this.currentPanel;
    }

    const panel = vscode.window.createWebviewPanel(
      this.options.viewType,
      this.options.title,
      column || this.options.defaultColumn || vscode.ViewColumn.One,
      this.options.createPanelOptions(extensionUri),
    );

    const controller = this.attach(panel, extensionUri);
    controller.initialize();
    return controller;
  }

  public revive(panel: vscode.WebviewPanel, extensionUri: vscode.Uri): T {
    const controller = this.attach(panel, extensionUri);
    controller.initialize();
    return controller;
  }

  public registerSerializer(extensionUri: vscode.Uri): vscode.Disposable | undefined {
    if (!vscode.window.registerWebviewPanelSerializer) {
      return undefined;
    }

    return vscode.window.registerWebviewPanelSerializer(this.options.viewType, {
      deserializeWebviewPanel: async (panel: vscode.WebviewPanel) => {
        this.revive(panel, extensionUri);
      },
    });
  }

  private attach(panel: vscode.WebviewPanel, extensionUri: vscode.Uri): T {
    let controller: T;
    controller = this.options.createController(panel, extensionUri, () => {
      if (this.currentPanel === controller) {
        this.currentPanel = undefined;
      }
    });
    this.currentPanel = controller;
    return controller;
  }
}