import * as vscode from 'vscode';
import { PythonEnvironmentError, PythonEnvironmentManager } from './python/environment.js';

export interface DapperWorkspacePythonRuntime {
  interpreterPath: string;
  pythonPath: string;
  version: string;
  env: NodeJS.ProcessEnv;
  cwd?: string;
  workspaceFolder?: string;
  source: 'python-extension';
}

export type DapperWorkspaceSelectionKind = 'explicit' | 'active-editor' | 'first-workspace' | 'unscoped';

export interface DapperWorkspaceSelection {
  kind: DapperWorkspaceSelectionKind;
  requestedWorkspaceFolder?: string;
  resolvedWorkspaceFolder?: string;
}

export type DapperWorkspaceRuntimeFailureCode =
  | 'workspace_not_found'
  | 'python_extension_missing'
  | 'python_extension_api_unavailable'
  | 'interpreter_not_found'
  | 'environment_variables_unavailable'
  | 'unknown';

export interface DapperWorkspacePythonRuntimeSuccess {
  ok: true;
  runtime: DapperWorkspacePythonRuntime;
  selection: DapperWorkspaceSelection;
}

export interface DapperWorkspacePythonRuntimeFailure {
  ok: false;
  code: DapperWorkspaceRuntimeFailureCode;
  message: string;
  selection: DapperWorkspaceSelection;
}

export type DapperWorkspacePythonRuntimeResult =
  | DapperWorkspacePythonRuntimeSuccess
  | DapperWorkspacePythonRuntimeFailure;

export interface DapperExtensionApi {
  apiVersion: 1;
  getWorkspacePythonRuntime(workspaceFolderUri?: vscode.Uri): Promise<DapperWorkspacePythonRuntimeResult>;
}

function resolveWorkspaceFolder(workspaceFolderUri?: vscode.Uri): {
  workspaceFolder?: vscode.WorkspaceFolder;
  selection: DapperWorkspaceSelection;
  failure?: DapperWorkspacePythonRuntimeFailure;
} {
  if (workspaceFolderUri) {
    const explicitFolder = vscode.workspace.getWorkspaceFolder(workspaceFolderUri);
    if (!explicitFolder) {
      return {
        selection: {
          kind: 'explicit',
          requestedWorkspaceFolder: workspaceFolderUri.toString(),
        },
        failure: {
          ok: false,
          code: 'workspace_not_found',
          message: 'The requested workspace folder URI is not part of the current VS Code workspace.',
          selection: {
            kind: 'explicit',
            requestedWorkspaceFolder: workspaceFolderUri.toString(),
          },
        },
      };
    }

    return {
      workspaceFolder: explicitFolder,
      selection: {
        kind: 'explicit',
        requestedWorkspaceFolder: workspaceFolderUri.toString(),
        resolvedWorkspaceFolder: explicitFolder.uri.toString(),
      },
    };
  }

  const activeDocumentUri = vscode.window.activeTextEditor?.document.uri;
  if (activeDocumentUri) {
    const activeFolder = vscode.workspace.getWorkspaceFolder(activeDocumentUri);
    if (activeFolder) {
      return {
        workspaceFolder: activeFolder,
        selection: {
          kind: 'active-editor',
          resolvedWorkspaceFolder: activeFolder.uri.toString(),
        },
      };
    }
  }

  const firstWorkspace = vscode.workspace.workspaceFolders?.[0];
  if (firstWorkspace) {
    return {
      workspaceFolder: firstWorkspace,
      selection: {
        kind: 'first-workspace',
        resolvedWorkspaceFolder: firstWorkspace.uri.toString(),
      },
    };
  }

  return {
    selection: {
      kind: 'unscoped',
    },
  };
}

export function createExtensionApi(): DapperExtensionApi {
  return {
    apiVersion: 1,
    async getWorkspacePythonRuntime(workspaceFolderUri?: vscode.Uri): Promise<DapperWorkspacePythonRuntimeResult> {
      const resolution = resolveWorkspaceFolder(workspaceFolderUri);
      if (resolution.failure) {
        return resolution.failure;
      }

      try {
        const environment = await PythonEnvironmentManager.getPythonEnvironment(resolution.workspaceFolder);

        return {
          ok: true,
          selection: resolution.selection,
          runtime: {
            interpreterPath: environment.pythonPath,
            pythonPath: environment.pythonPath,
            version: environment.version,
            env: environment.env,
            cwd: resolution.workspaceFolder?.uri.fsPath,
            workspaceFolder: resolution.workspaceFolder?.uri.toString(),
            source: 'python-extension',
          },
        };
      } catch (error) {
        if (error instanceof PythonEnvironmentError) {
          return {
            ok: false,
            code: error.code,
            message: error.message,
            selection: resolution.selection,
          };
        }

        return {
          ok: false,
          code: 'unknown',
          message: error instanceof Error ? error.message : String(error),
          selection: resolution.selection,
        };
      }
    },
  };
}