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
    asWebviewUri: (uri) => uri.fsPath ?? String(uri)
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
Uri.joinPath = (base, ...segments) => ({ fsPath: [base.fsPath, ...segments].join('/') });

export const commands = {
  executeCommand: (...args) => Promise.resolve()
};

// Debug event emitter helpers — tests can fire these to simulate VS Code debug events
const _debugListeners = {
  onDidStartDebugSession: [],
  onDidTerminateDebugSession: [],
  onDidChangeActiveStackItem: [],
};

export const fireDebugEvent = (eventName, arg) => {
  for (const listener of _debugListeners[eventName] ?? []) {
    listener(arg);
  }
};

export const debug = {
  startDebugging: async (...args) => true,
  activeDebugSession: null,
  activeStackItem: null,
  onDidStartDebugSession: (listener) => {
    _debugListeners.onDidStartDebugSession.push(listener);
    return { dispose: () => { const i = _debugListeners.onDidStartDebugSession.indexOf(listener); if (i >= 0) _debugListeners.onDidStartDebugSession.splice(i, 1); } };
  },
  onDidTerminateDebugSession: (listener) => {
    _debugListeners.onDidTerminateDebugSession.push(listener);
    return { dispose: () => { const i = _debugListeners.onDidTerminateDebugSession.indexOf(listener); if (i >= 0) _debugListeners.onDidTerminateDebugSession.splice(i, 1); } };
  },
  onDidChangeActiveStackItem: (listener) => {
    _debugListeners.onDidChangeActiveStackItem.push(listener);
    return { dispose: () => { const i = _debugListeners.onDidChangeActiveStackItem.indexOf(listener); if (i >= 0) _debugListeners.onDidChangeActiveStackItem.splice(i, 1); } };
  },
};

export const panelsList = panels;

window.createWebviewPanel = createWebviewPanel;
export default { workspace, window, Uri, commands, debug };
export const ViewColumn = { One: 1, Two: 2 };
export const resetDebugListeners = () => {
  _debugListeners.onDidStartDebugSession.length = 0;
  _debugListeners.onDidTerminateDebugSession.length = 0;
  _debugListeners.onDidChangeActiveStackItem.length = 0;
};
