export type IPCMethod = 'tcp' | 'unix' | 'pipe';
export type ConsoleType = 'internalConsole' | 'integratedTerminal' | 'externalTerminal';

export interface DebugConfiguration {
  // Basic configuration
  name: string;
  type: 'dapper';
  request: 'launch' | 'attach';
  program: string;
  args: string[];
  cwd: string;
  
  // Debug server settings
  debugServer: number;
  useIpc: boolean;
  ipcTransport: IPCMethod;
  
  // Debug behavior
  frameEval: boolean;
  inProcess: boolean;
  stopOnEntry: boolean;
  justMyCode: boolean;
  
  // Python environment
  pythonPath?: string;
  env?: Record<string, string>;
  console?: ConsoleType;
  
  // Output control
  redirectOutput?: boolean;
  showReturnValue?: boolean;
  logToFile?: boolean;
  
  // Framework specific
  django?: boolean;
  flask?: boolean;
  jinja?: boolean;
  gevent?: boolean;
  
  // Advanced
  debugOptions?: string[];
  
  // Subprocess debugging
  subProcess?: boolean;
  subProcessId?: number;
  subProcessParentId?: number;
  subProcessName?: string;
  subProcessArgs?: string[];
  subProcessCwd?: string;
  subProcessEnv?: Record<string, string>;
  subProcessPythonPath?: string;
  
  // Framework settings for subprocesses
  subProcessDjango?: boolean;
  subProcessFlask?: boolean;
  subProcessJinja?: boolean;
  subProcessGevent?: boolean;
  
  // Debug options for subprocesses
  subProcessStopOnEntry?: boolean;
  subProcessJustMyCode?: boolean;
  subProcessRedirectOutput?: boolean;
  subProcessShowReturnValue?: boolean;
  subProcessLogToFile?: boolean;
  subProcessDebugOptions?: string[];
  subProcessDebugServer?: number;
  subProcessUseIpc?: boolean;
  subProcessIpcTransport?: IPCMethod;
  subProcessFrameEval?: boolean;
}
