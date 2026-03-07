import * as vscode from 'vscode';
import type { DebugProtocol } from '@vscode/debugprotocol';

export interface LaunchRequestArguments extends DebugProtocol.LaunchRequestArguments {
  program?: string;
  module?: string;
  moduleSearchPaths?: string[];
  venvPath?: string;
  pythonPath?: string;
  subprocessAutoAttach?: boolean;
  args?: string[];
  stopOnEntry?: boolean;
  console?: 'internalConsole' | 'integratedTerminal' | 'externalTerminal';
  cwd?: string;
  env?: { [key: string]: string };
  forceReinstall?: boolean;
}

export interface AttachRequestArguments extends DebugProtocol.AttachRequestArguments {
  host?: string;
  port?: number;
  processId?: number | string;
  pythonPath?: string;
  venvPath?: string;
  cwd?: string;
  env?: { [key: string]: string };
  justMyCode?: boolean;
  strictExpressionWatchPolicy?: boolean;
  forceReinstall?: boolean;
}

export interface InternalChildLaunchConfiguration extends vscode.DebugConfiguration {
  __dapperIsChildSession: true;
  __dapperChildSessionId: string;
  __dapperChildPid: number;
  __dapperChildName: string;
  __dapperParentDebugSessionId: string;
  __dapperChildIpcPort: number;
}

export interface PendingChildSession {
  launcherSessionId: string;
  pid: number;
  name: string;
  ipcPort: number;
  parentDebugSessionId: string;
  parentSession: vscode.DebugSession;
  workspaceFolder?: vscode.WorkspaceFolder;
  cwd?: string;
  command?: string[];
  listener?: import('net').Server;
  socket?: import('net').Socket;
  adapterServer?: import('net').Server;
  vscodeSessionId?: string;
  launchRequested?: boolean;
  terminated?: boolean;
}

export interface AttachByPidDiagnostic {
  code: string;
  message: string;
  detail?: string;
  hint?: string;
}