import * as vscode from 'vscode';

export type InstallMode = 'auto' | 'wheel' | 'pypi' | 'workspace';

export interface EnvManifest {
  dapperVersionInstalled: string;
  installSource: 'wheel' | 'pypi';
  wheelHash?: string;
  created: string;
  updated: string;
}

export interface PythonEnvInfo {
  pythonPath: string;
  venvPath?: string;
  dapperVersionInstalled?: string;
  needsInstall: boolean;
  dapperLibPath?: string;
}

export interface PrepareEnvironmentOptions {
  workspaceFolder?: vscode.WorkspaceFolder;
  preferredPythonPath?: string;
  preferredVenvPath?: string;
  allowInstallToPreferredInterpreter?: boolean;
  searchRootPath?: string;
}
