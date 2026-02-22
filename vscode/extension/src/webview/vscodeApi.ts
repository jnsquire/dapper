// Shared VS Code webview API singleton.
// acquireVsCodeApi() can only be called once per webview, so we
// centralise the call here and re-export the instance.

declare function acquireVsCodeApi(): {
  postMessage(message: unknown): void;
  getState(): unknown;
  setState(state: unknown): void;
};

export type VsCodeApi = ReturnType<typeof acquireVsCodeApi>;

export const vscode: VsCodeApi | undefined =
  typeof acquireVsCodeApi !== 'undefined' ? acquireVsCodeApi() : undefined;
