export const workspace = {
  workspaceFolders: [{ name: 'temp', uri: { fsPath: '' } }],
  fs: {
      readFile: () => Promise.reject(new Error('not implemented')),
      writeFile: () => Promise.resolve(),
      createDirectory: () => Promise.resolve()
  },
  openTextDocument: () => Promise.resolve({}),
  getConfiguration: () => ({ get: () => undefined, update: () => {} })
  ,
  onDidChangeConfiguration: (handler) => ({ dispose: () => {} })
};

export const window = {
  showErrorMessage: () => {},
  showWarningMessage: () => {},
  showInformationMessage: () => {},
  showQuickPick: () => {},
  showTextDocument: () => {},
  createOutputChannel: (name) => ({ appendLine: () => {}, show: () => {}, dispose: () => {} })
};

// createWebviewPanel should return an object that mimics VS Code WebviewPanel API
const panels = [];
export const createWebviewPanel = (viewType, title, column, options) => {
  const webview = {
    _messageHandler: null,
    onDidReceiveMessage: (handler) => { webview._messageHandler = handler; return { dispose: () => {} } },
    postMessage: (m) => Promise.resolve(true),
    asWebviewUri: (uri) => uri
  };
  const panel = {
    webview,
    title,
    viewType,
    reveal: () => {},
    dispose: () => {},
    onDidDispose: () => ({ dispose: () => {} })
  };
  panels.push(panel);
  return panel;
};

export const Uri = {
  file: (fsPath) => ({ fsPath })
};
// Join path is handy to resolve directories
Uri.joinPath = (base, pathSegment) => ({ fsPath: `${base.fsPath}/${pathSegment}` });

export const commands = {
  executeCommand: (...args) => Promise.resolve()
};

export const debug = {
  startDebugging: async (...args) => true
};

export const panelsList = panels;

window.createWebviewPanel = createWebviewPanel;
export default { workspace, window, Uri, commands, debug };
export const ViewColumn = { One: 1, Two: 2 };
