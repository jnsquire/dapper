import * as path from 'path';

import * as vscode from 'vscode';

import type { EnvironmentSnapshotOptions, EnvironmentSnapshotService } from './environmentSnapshot.js';
import type { PythonSymbolBackendStatus, PythonSymbolRange } from './symbols.js';

export interface PythonRenameOptions extends EnvironmentSnapshotOptions {
  file: string;
  line: number;
  column?: number;
  newName: string;
  apply?: boolean;
}

export interface PythonRenameEdit {
  path: string;
  range: PythonSymbolRange;
  newText: string;
}

export interface PythonRenameResult {
  generatedAt: string;
  status: 'complete' | 'failed';
  applied: boolean;
  request: {
    file: string;
    line: number;
    column: number;
    newName: string;
  };
  backend: PythonSymbolBackendStatus;
  fileCount: number;
  editCount: number;
  edits: PythonRenameEdit[];
  error?: string;
}

type WorkspaceEditEntries = Iterable<[vscode.Uri, vscode.TextEdit[]]>;

export class PythonRenameService {
  constructor(private readonly environmentSnapshotService: Pick<EnvironmentSnapshotService, 'getSnapshot'>) {}

  async rename(options: PythonRenameOptions): Promise<PythonRenameResult> {
    const snapshot = await this.environmentSnapshotService.getSnapshot(options);
    const documentUri = this._resolveDocumentUri(options);
    const position = new vscode.Position(options.line - 1, (options.column ?? 1) - 1);

    try {
      await vscode.workspace.openTextDocument(documentUri);
      const workspaceEdit = await vscode.commands.executeCommand(
        'vscode.executeDocumentRenameProvider',
        documentUri,
        position,
        options.newName,
      );
      const edits = this._normalizeWorkspaceEdit(workspaceEdit);
      const shouldApply = options.apply !== false;
      let applied = false;

      if (shouldApply && edits.length > 0) {
        applied = await vscode.workspace.applyEdit(workspaceEdit as vscode.WorkspaceEdit);
      }

      return {
        generatedAt: new Date().toISOString(),
        status: 'complete',
        applied,
        request: {
          file: documentUri.fsPath,
          line: options.line,
          column: options.column ?? 1,
          newName: options.newName,
        },
        backend: this._createBackendStatus(snapshot.ty.available),
        fileCount: new Set(edits.map(edit => edit.path)).size,
        editCount: edits.length,
        edits,
      };
    } catch (error) {
      return {
        generatedAt: new Date().toISOString(),
        status: 'failed',
        applied: false,
        request: {
          file: documentUri.fsPath,
          line: options.line,
          column: options.column ?? 1,
          newName: options.newName,
        },
        backend: this._createBackendStatus(snapshot.ty.available),
        fileCount: 0,
        editCount: 0,
        edits: [],
        error: error instanceof Error ? error.message : String(error),
      };
    }
  }

  private _resolveDocumentUri(options: PythonRenameOptions): vscode.Uri {
    const inputPath = path.resolve(this._resolveBasePath(options), options.file);
    return vscode.Uri.file(inputPath);
  }

  private _resolveBasePath(options: PythonRenameOptions): string {
    return options.searchRootPath
      ?? options.workspaceFolder?.uri.fsPath
      ?? vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
      ?? process.cwd();
  }

  private _normalizeWorkspaceEdit(value: unknown): PythonRenameEdit[] {
    if (!value || typeof value !== 'object') {
      return [];
    }

    const candidate = value as { entries?: () => WorkspaceEditEntries };
    if (typeof candidate.entries !== 'function') {
      return [];
    }

    const edits: PythonRenameEdit[] = [];
    for (const [uri, textEdits] of candidate.entries()) {
      for (const edit of textEdits) {
        edits.push({
          path: uri.fsPath,
          range: this._normalizeRange(edit.range),
          newText: edit.newText,
        });
      }
    }
    return edits;
  }

  private _normalizeRange(range: vscode.Range): PythonSymbolRange {
    return {
      startLine: range.start.line + 1,
      startColumn: range.start.character + 1,
      endLine: range.end.line + 1,
      endColumn: range.end.character + 1,
    };
  }

  private _createBackendStatus(tyAvailable: boolean): PythonSymbolBackendStatus {
    return {
      provider: 'vscode-language-features',
      preferredSemanticBackend: tyAvailable ? 'ty' : 'fallback',
      tyAvailable,
      note: 'VS Code does not expose which extension satisfied the rename request; Ty availability only indicates the preferred semantic backend for this workspace.',
    };
  }
}