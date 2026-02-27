// Messages sent FROM the extension host TO the webview
export type HostToWebviewMessage =
  | { command: 'stackTrace'; frames: StackFrame[] }
  | { command: 'variables'; frameId: number; variables: Variable[] }
  | { command: 'sourceLines'; frameId: number; lines: string[] }
  | { command: 'threads'; threads: ThreadInfo[] }
  | { command: 'sessionState'; state: 'running' | 'paused' | 'stopped' }
  | { command: 'clearStack' };

// Messages sent FROM the webview TO the extension host
export type WebviewToHostMessage =
  | { command: 'continue' }
  | { command: 'stepOver' }
  | { command: 'stepInto' }
  | { command: 'stepOut' }
  | { command: 'pause' }
  | { command: 'selectFrame'; frameId: number }
  | { command: 'expandFrame'; frameId: number }
  | { command: 'filterStack'; query: string }
  | { command: 'selectThread'; threadId: number };

export interface StackFrame {
  id: number;
  name: string;
  source: string;
  line: number;
  column: number;
  isOptimized?: boolean;
  isSynthetic?: boolean;
  isCython?: boolean;
  sourceLines?: string[]; // up to 5 context lines; index 2 is the current line
}

export interface Variable {
  name: string;
  value: string;
  type?: string;
  hasChildren: boolean;
  variablesReference: number;
}

export interface ThreadInfo {
  id: number;
  name: string;
  state: 'running' | 'paused' | 'stopped';
}
