import * as vscode from 'vscode';

import { resolvePythonDocumentUri } from './document.js';
import type { EnvironmentSnapshotOptions, EnvironmentSnapshotService } from './environmentSnapshot.js';

export type PythonSymbolAction = 'definition' | 'references' | 'implementations' | 'hover';

export interface PythonSymbolOptions extends EnvironmentSnapshotOptions {
  action: PythonSymbolAction;
  file: string;
  line: number;
  column?: number;
}

export interface PythonSymbolRange {
  startLine: number;
  startColumn: number;
  endLine: number;
  endColumn: number;
}

export interface PythonSymbolLocationResult {
  kind: 'location' | 'location-link';
  path: string;
  range: PythonSymbolRange;
  targetSelectionRange?: PythonSymbolRange;
}

export interface PythonHoverResult {
  kind: 'hover';
  contents: string[];
  range?: PythonSymbolRange;
}

export interface PythonSymbolBackendStatus {
  provider: 'vscode-language-features';
  preferredSemanticBackend: 'ty' | 'fallback';
  tyAvailable: boolean;
  note: string;
}

export interface PythonSymbolResult {
  generatedAt: string;
  action: PythonSymbolAction;
  status: 'complete' | 'failed';
  request: {
    file: string;
    line: number;
    column: number;
  };
  backend: PythonSymbolBackendStatus;
  count: number;
  results: Array<PythonSymbolLocationResult | PythonHoverResult>;
  error?: string;
}

export class PythonSymbolService {
  constructor(private readonly environmentSnapshotService: Pick<EnvironmentSnapshotService, 'getSnapshot'>) {}

  async resolve(options: PythonSymbolOptions): Promise<PythonSymbolResult> {
    const snapshot = await this.environmentSnapshotService.getSnapshot(options);
    const documentUri = resolvePythonDocumentUri(options);
    const position = new vscode.Position(options.line - 1, (options.column ?? 1) - 1);

    try {
      await vscode.workspace.openTextDocument(documentUri);
      const rawResults = await this._executeProvider(options.action, documentUri, position);
      const normalizedResults = this._normalizeResults(options.action, rawResults);

      return {
        generatedAt: new Date().toISOString(),
        action: options.action,
        status: 'complete',
        request: {
          file: documentUri.fsPath,
          line: options.line,
          column: options.column ?? 1,
        },
        backend: this._createBackendStatus(snapshot.ty.available),
        count: normalizedResults.length,
        results: normalizedResults,
      };
    } catch (error) {
      return {
        generatedAt: new Date().toISOString(),
        action: options.action,
        status: 'failed',
        request: {
          file: documentUri.fsPath,
          line: options.line,
          column: options.column ?? 1,
        },
        backend: this._createBackendStatus(snapshot.ty.available),
        count: 0,
        results: [],
        error: error instanceof Error ? error.message : String(error),
      };
    }
  }

  private async _executeProvider(
    action: PythonSymbolAction,
    documentUri: vscode.Uri,
    position: vscode.Position,
  ): Promise<unknown> {
    switch (action) {
      case 'definition':
        return vscode.commands.executeCommand('vscode.executeDefinitionProvider', documentUri, position);
      case 'references':
        return vscode.commands.executeCommand('vscode.executeReferenceProvider', documentUri, position);
      case 'implementations':
        return vscode.commands.executeCommand('vscode.executeImplementationProvider', documentUri, position);
      case 'hover':
        return vscode.commands.executeCommand('vscode.executeHoverProvider', documentUri, position);
    }
  }

  private _normalizeResults(
    action: PythonSymbolAction,
    rawResults: unknown,
  ): Array<PythonSymbolLocationResult | PythonHoverResult> {
    if (!Array.isArray(rawResults)) {
      return [];
    }

    if (action === 'hover') {
      return rawResults
        .map(item => this._normalizeHover(item))
        .filter((item): item is PythonHoverResult => item !== undefined);
    }

    return rawResults
      .map(item => this._normalizeLocation(item))
      .filter((item): item is PythonSymbolLocationResult => item !== undefined);
  }

  private _normalizeLocation(value: unknown): PythonSymbolLocationResult | undefined {
    if (!value || typeof value !== 'object') {
      return undefined;
    }

    const candidate = value as {
      uri?: { fsPath?: string };
      range?: vscode.Range;
      targetUri?: { fsPath?: string };
      targetRange?: vscode.Range;
      targetSelectionRange?: vscode.Range;
    };

    if (candidate.targetUri?.fsPath && candidate.targetRange) {
      return {
        kind: 'location-link',
        path: candidate.targetUri.fsPath,
        range: this._normalizeRange(candidate.targetRange),
        targetSelectionRange: candidate.targetSelectionRange
          ? this._normalizeRange(candidate.targetSelectionRange)
          : undefined,
      };
    }

    if (candidate.uri?.fsPath && candidate.range) {
      return {
        kind: 'location',
        path: candidate.uri.fsPath,
        range: this._normalizeRange(candidate.range),
      };
    }

    return undefined;
  }

  private _normalizeHover(value: unknown): PythonHoverResult | undefined {
    if (!value || typeof value !== 'object') {
      return undefined;
    }

    const candidate = value as { contents?: unknown; range?: vscode.Range };
    const contents = this._normalizeHoverContents(candidate.contents);
    if (contents.length === 0) {
      return undefined;
    }

    return {
      kind: 'hover',
      contents,
      range: candidate.range ? this._normalizeRange(candidate.range) : undefined,
    };
  }

  private _normalizeHoverContents(value: unknown): string[] {
    if (typeof value === 'string') {
      return [value];
    }
    if (Array.isArray(value)) {
      return value.flatMap(item => this._normalizeHoverContents(item));
    }
    if (value && typeof value === 'object') {
      const candidate = value as { value?: unknown; language?: unknown };
      if (typeof candidate.value === 'string' && typeof candidate.language === 'string') {
        return [`${candidate.language}\n${candidate.value}`];
      }
      if (typeof candidate.value === 'string') {
        return [candidate.value];
      }
    }
    return [];
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
      note: 'VS Code does not expose which extension satisfied the provider request; Ty availability only indicates the preferred semantic backend for this workspace.',
    };
  }
}