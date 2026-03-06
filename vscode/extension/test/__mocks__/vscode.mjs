export const workspace = {
  workspaceFolders: [{ name: 'temp', uri: { fsPath: '' } }],
  fs: {
      readFile: () => Promise.reject(new Error('not implemented')),
      writeFile: () => Promise.resolve(),
      createDirectory: () => Promise.resolve()
  },
  openTextDocument: () => Promise.resolve({}),
  getConfiguration: () => ({ get: () => undefined, update: () => {} }),
  getWorkspaceFolder: (uri) => {
    const folders = workspace.workspaceFolders ?? [];
    return folders.find((folder) => typeof uri?.fsPath === 'string' && uri.fsPath.startsWith(folder.uri.fsPath));
  },
  asRelativePath: (uriOrPath) => {
    const rawPath = typeof uriOrPath === 'string' ? uriOrPath : uriOrPath?.fsPath ?? '';
    const base = workspace.workspaceFolders?.[0]?.uri?.fsPath ?? '';
    if (base && rawPath.startsWith(base)) {
      return rawPath.slice(base.length).replace(/^\//, '');
    }
    return rawPath;
  },
  onDidChangeConfiguration: (handler) => ({ dispose: () => {} })
};

export const window = {
  showErrorMessage: () => {},
  showWarningMessage: () => {},
  showInformationMessage: () => {},
  showQuickPick: () => {},
  showTextDocument: () => {},
  activeTextEditor: undefined,
  createOutputChannel: (name) => ({
      appendLine: () => {},
      show: () => {},
      dispose: () => {},
      // LogOutputChannel helpers (do nothing by default)
      debug: () => {},
      info: () => {},
      warn: () => {},
      error: () => {},
  })
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
  file: (fsPath) => ({ fsPath, scheme: 'file' })
};
// Join path is handy to resolve directories
Uri.joinPath = (base, ...segments) => ({ fsPath: [base.fsPath, ...segments].join('/'), scheme: 'file' });

export class Position {
  constructor(line, character) {
    this.line = line;
    this.character = character;
  }
}

export class Range {
  constructor(start, end) {
    this.start = start;
    this.end = end;
  }
}

export class Location {
  constructor(uri, positionOrRange) {
    this.uri = uri;
    this.range = positionOrRange instanceof Range
      ? positionOrRange
      : new Range(positionOrRange, positionOrRange);
  }
}

export class Breakpoint {
  constructor(enabled = true) {
    this.enabled = enabled;
  }
}

export class SourceBreakpoint extends Breakpoint {
  constructor(location, enabled = true, condition, hitCondition, logMessage) {
    super(enabled);
    this.location = location;
    this.condition = condition;
    this.hitCondition = hitCondition;
    this.logMessage = logMessage;
  }
}

export const commands = {
  executeCommand: (...args) => Promise.resolve()
};

export const extensions = {
  getExtension: () => undefined,
};

export class LanguageModelTextPart {
  constructor(value) {
    this.value = value;
  }
}

export class LanguageModelToolResult {
  constructor(parts = []) {
    this.content = parts;
  }
}

export const lm = {
  registerTool: () => ({ dispose: () => {} }),
};

// Debug event emitter helpers — tests can fire these to simulate VS Code debug events
const _debugListeners = {
  onDidStartDebugSession: [],
  onDidTerminateDebugSession: [],
  onDidChangeActiveStackItem: [],
  onDidReceiveDebugSessionCustomEvent: [],
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
  breakpoints: [],
  addBreakpoints: (bps) => {
    debug.breakpoints = [...debug.breakpoints, ...bps];
  },
  removeBreakpoints: (bps) => {
    const removeSet = new Set(bps);
    debug.breakpoints = debug.breakpoints.filter((bp) => !removeSet.has(bp));
  },
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
  onDidReceiveDebugSessionCustomEvent: (listener) => {
    _debugListeners.onDidReceiveDebugSessionCustomEvent.push(listener);
    return { dispose: () => { const i = _debugListeners.onDidReceiveDebugSessionCustomEvent.indexOf(listener); if (i >= 0) _debugListeners.onDidReceiveDebugSessionCustomEvent.splice(i, 1); } };
  },
};

export const panelsList = panels;

window.createWebviewPanel = createWebviewPanel;
export default { workspace, window, Uri, Position, Range, Location, Breakpoint, SourceBreakpoint, commands, debug, extensions, lm, LanguageModelTextPart, LanguageModelToolResult };
export const ViewColumn = { One: 1, Two: 2 };
export const resetDebugListeners = () => {
  _debugListeners.onDidStartDebugSession.length = 0;
  _debugListeners.onDidTerminateDebugSession.length = 0;
  _debugListeners.onDidChangeActiveStackItem.length = 0;
  _debugListeners.onDidReceiveDebugSessionCustomEvent.length = 0;
  debug.activeDebugSession = null;
  debug.activeStackItem = null;
  debug.breakpoints = [];
  window.activeTextEditor = undefined;
};
