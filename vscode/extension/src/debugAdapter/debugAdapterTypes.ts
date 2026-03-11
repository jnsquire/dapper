import * as vscode from 'vscode';
import type { DebugProtocol } from '@vscode/debugprotocol';
import type { PendingChildConnection } from './pendingChildConnection.js';

export interface LaunchRequestArguments extends DebugProtocol.LaunchRequestArguments {
  program?: string;
  module?: string;
  moduleSearchPaths?: string[];
  venvPath?: string;
  pythonPath?: string;
  __dapperExplicitEnvironmentSelection?: boolean;
  __dapperEnvironmentSearchRoot?: string;
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
  connection: PendingChildConnection;
  vscodeSessionId?: string;
}

export interface AttachByPidDiagnostic {
  code: string;
  message: string;
  detail?: string;
  hint?: string;
}