class MockEventEmitter {
  constructor() {
    this._listeners = [];
    this.event = (listener) => {
      this._listeners.push(listener);
      return {
        dispose: () => {
          const index = this._listeners.indexOf(listener);
          if (index >= 0) {
            this._listeners.splice(index, 1);
          }
        }
      };
    };
  }

  fire(data) {
    for (const listener of this._listeners.slice()) {
      listener(data);
    }
  }

  dispose() {
    this._listeners.length = 0;
  }
}

export class TreeItem {
  constructor(label, collapsibleState = 0) {
    this.label = label;
    this.collapsibleState = collapsibleState;
  }
}

export const TreeItemCollapsibleState = {
  None: 0,
  Collapsed: 1,
  Expanded: 2,
};

export class ThemeIcon {
  constructor(id) {
    this.id = id;
  }
}

export const workspace = {
  workspaceFolders: [{ name: 'temp', uri: { fsPath: '' } }],
  fs: {
      stat: () => Promise.reject(new Error('not implemented')),
      readFile: () => Promise.reject(new Error('not implemented')),
      writeFile: () => Promise.resolve(),
      createDirectory: () => Promise.resolve()
  },
  openTextDocument: () => Promise.resolve({}),
  applyEdit: () => Promise.resolve(true),
  getConfiguration: () => ({ get: () => undefined, update: () => {} }),
  getWorkspaceFolder: (uri) => {
    const folders = workspace.workspaceFolders ?? [];
    return folders.find((folder) => typeof uri?.fsPath === 'string' && uri.fsPath.startsWith(folder.uri.fsPath));
  },
  asRelativePath: (uriOrPath) => {
    const rawPath = typeof uriOrPath === 'string' ? uriOrPath : uriOrPath?.fsPath ?? '';
    const base = workspace.workspaceFolders?.[0]?.uri?.fsPath ?? '';
    if (base && rawPath.startsWith(base)) {
      return rawPath.slice(base.length).replace(/^[\\/]+/, '');
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
  showInputBox: async () => undefined,
  showTextDocument: () => {},
  createTerminal: () => ({
    show: () => {},
    dispose: () => {},
    exitStatus: { code: 0 },
  }),
  onDidCloseTerminal: () => ({ dispose: () => {} }),
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
  }),
  createTreeView: (id, options) => ({
    id,
    options,
    title: undefined,
    description: undefined,
    message: undefined,
    badge: undefined,
    visible: true,
    selection: [],
    onDidExpandElement: () => ({ dispose: () => {} }),
    onDidCollapseElement: () => ({ dispose: () => {} }),
    onDidChangeSelection: () => ({ dispose: () => {} }),
    onDidChangeVisibility: () => ({ dispose: () => {} }),
    onDidChangeCheckboxState: () => ({ dispose: () => {} }),
    reveal: () => Promise.resolve(),
    dispose: () => {},
  }),
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

export class TextEdit {
  constructor(range, newText) {
    this.range = range;
    this.newText = newText;
  }
}

export class WorkspaceEdit {
  constructor() {
    this._entries = [];
  }

  set(uri, edits) {
    this._entries.push([uri, edits]);
  }

  entries() {
    return this._entries;
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
  executeCommand: (...args) => Promise.resolve(),
  registerCommand: (command, callback) => ({ command, callback, dispose: () => {} }),
};

export const env = {
  clipboard: {
    writeText: async () => {},
  },
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
  stopDebugging: async (...args) => {},
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

export class Disposable {
  constructor(callOnDispose = () => {}) {
    this._callOnDispose = callOnDispose;
  }

  dispose() {
    this._callOnDispose();
  }

  static from(...disposables) {
    return new Disposable(() => {
      for (const disposable of disposables) {
        disposable?.dispose?.();
      }
    });
  }
}

export class DebugAdapterServer {
  constructor(port, host) {
    this.port = port;
    this.host = host;
  }
}

export class DebugAdapterExecutable {
  constructor(command, args = []) {
    this.command = command;
    this.args = args;
  }
}

export const panelsList = panels;
export const DebugConsoleMode = {
  MergeWithParent: 'mergeWithParent',
};

export const ConfigurationTarget = {
  Global: 1,
  Workspace: 2,
  WorkspaceFolder: 3,
};

window.createWebviewPanel = createWebviewPanel;
export const EventEmitter = MockEventEmitter;

export default { workspace, window, Uri, Position, Range, Location, TextEdit, WorkspaceEdit, Breakpoint, SourceBreakpoint, commands, debug, extensions, env, lm, LanguageModelTextPart, LanguageModelToolResult, DebugAdapterServer, DebugAdapterExecutable, DebugConsoleMode, ConfigurationTarget, TreeItem, TreeItemCollapsibleState, ThemeIcon, EventEmitter, Disposable };
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
