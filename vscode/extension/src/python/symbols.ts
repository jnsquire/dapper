import * as vscode from 'vscode';

import { resolvePythonDocumentUri } from './document.js';
import type { EnvironmentSnapshotOptions, EnvironmentSnapshotService } from './environmentSnapshot.js';
import type {
  PythonCallSignature,
  PythonDocumentation,
  PythonOutputBudget,
  PythonToolCompletionStatus,
  PythonTypeInfo,
} from './semanticPayloads.js';

export type PythonSymbolAction = 'definition' | 'references' | 'implementations' | 'hover';

export interface PythonSymbolOptions extends EnvironmentSnapshotOptions {
  action: PythonSymbolAction;
  file: string;
  line: number;
  column?: number;
  limit?: number;
  offset?: number;
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
  typeInfo?: PythonTypeInfo;
  signatures?: PythonCallSignature[];
  documentation?: PythonDocumentation;
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
  completionStatus: PythonToolCompletionStatus;
  request: {
    file: string;
    line: number;
    column: number;
  };
  backend: PythonSymbolBackendStatus;
  count: number;
  outputBudget: PythonOutputBudget;
  results: Array<PythonSymbolLocationResult | PythonHoverResult>;
  error?: string;
}

export class PythonSymbolService {
  constructor(private readonly environmentSnapshotService: Pick<EnvironmentSnapshotService, 'getSnapshot'>) {}

  async resolve(options: PythonSymbolOptions): Promise<PythonSymbolResult> {
    const snapshot = await this.environmentSnapshotService.getSnapshot(options);
    const documentUri = resolvePythonDocumentUri(options);
    const position = new vscode.Position(options.line - 1, (options.column ?? 1) - 1);
    const limit = this._normalizeLimit(options.limit);
    const offset = this._normalizeOffset(options.offset);

    try {
      await vscode.workspace.openTextDocument(documentUri);
      const rawResults = await this._executeProvider(options.action, documentUri, position);
      const normalizedResults = this._normalizeResults(options.action, rawResults, snapshot.ty.available ? 'ty' : 'fallback');
      const pagedResults = this._slicePage(normalizedResults, offset, limit);
      const nextOffset = offset + pagedResults.length;
      const truncated = nextOffset < normalizedResults.length;
      const partial = offset > 0 || truncated;

      return {
        generatedAt: new Date().toISOString(),
        action: options.action,
        status: 'complete',
        completionStatus: partial ? 'partial' : 'complete',
        request: {
          file: documentUri.fsPath,
          line: options.line,
          column: options.column ?? 1,
        },
        backend: this._createBackendStatus(snapshot.ty.available),
        count: pagedResults.length,
        outputBudget: {
          requestedLimit: options.limit,
          appliedLimit: limit,
          requestedOffset: options.offset,
          appliedOffset: offset,
          returnedItems: pagedResults.length,
          totalItems: normalizedResults.length,
          truncated,
          nextOffset: truncated ? nextOffset : undefined,
        },
        results: pagedResults,
      };
    } catch (error) {
      return {
        generatedAt: new Date().toISOString(),
        action: options.action,
        status: 'failed',
        completionStatus: 'failed',
        request: {
          file: documentUri.fsPath,
          line: options.line,
          column: options.column ?? 1,
        },
        backend: this._createBackendStatus(snapshot.ty.available),
        count: 0,
        outputBudget: {
          requestedLimit: options.limit,
          appliedLimit: limit,
          requestedOffset: options.offset,
          appliedOffset: offset,
          returnedItems: 0,
          totalItems: 0,
          truncated: false,
          nextOffset: undefined,
        },
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
    typeSource: PythonTypeInfo['source'],
  ): Array<PythonSymbolLocationResult | PythonHoverResult> {
    if (!Array.isArray(rawResults)) {
      return [];
    }

    if (action === 'hover') {
      return rawResults
        .map(item => this._normalizeHover(item, typeSource))
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

  private _normalizeHover(value: unknown, typeSource: PythonTypeInfo['source']): PythonHoverResult | undefined {
    if (!value || typeof value !== 'object') {
      return undefined;
    }

    const candidate = value as { contents?: unknown; range?: vscode.Range };
    const entries = this._collectHoverEntries(candidate.contents);
    const contents = entries.map(entry => (entry.language ? `${entry.language}\n${entry.text}` : entry.text));
    if (contents.length === 0) {
      return undefined;
    }

    const typeInfo = this._deriveHoverTypeInfo(entries, typeSource);
    const signatures = this._deriveHoverSignatures(entries);
    const documentation = this._deriveHoverDocumentation(entries);

    const normalized: PythonHoverResult = {
      kind: 'hover',
      contents,
      typeInfo,
      signatures,
      documentation,
    };

    if (candidate.range) {
      normalized.range = this._normalizeRange(candidate.range);
    }

    return normalized;
  }

  private _collectHoverEntries(value: unknown): Array<{ text: string; language?: string }> {
    if (typeof value === 'string') {
      return this._parseMarkdownEntries(value);
    }
    if (Array.isArray(value)) {
      return value.flatMap(item => this._collectHoverEntries(item));
    }
    if (value && typeof value === 'object') {
      const candidate = value as { value?: unknown; language?: unknown };
      if (typeof candidate.value === 'string' && typeof candidate.language === 'string') {
        return [{ language: candidate.language, text: candidate.value.trim() }];
      }
      if (typeof candidate.value === 'string') {
        return this._parseMarkdownEntries(candidate.value);
      }
    }
    return [];
  }

  private _parseMarkdownEntries(value: string): Array<{ text: string; language?: string }> {
    const entries: Array<{ text: string; language?: string }> = [];
    const fencePattern = /```([\w-]+)?\n([\s\S]*?)```/g;
    let lastIndex = 0;
    let match: RegExpExecArray | null;

    while ((match = fencePattern.exec(value)) !== null) {
      const prefix = this._cleanMarkdownSegment(value.slice(lastIndex, match.index));
      if (prefix) {
        entries.push({ text: prefix });
      }
      const language = match[1]?.trim() || undefined;
      const body = this._cleanMarkdownSegment(match[2] ?? '');
      if (body) {
        entries.push({ language, text: body });
      }
      lastIndex = match.index + match[0].length;
    }

    const suffix = this._cleanMarkdownSegment(value.slice(lastIndex));
    if (suffix) {
      entries.push({ text: suffix });
    }

    if (entries.length > 0) {
      return entries;
    }

    const cleaned = this._cleanMarkdownSegment(value);
    return cleaned ? [{ text: cleaned }] : [];
  }

  private _deriveHoverTypeInfo(
    entries: Array<{ text: string; language?: string }>,
    source: PythonTypeInfo['source'],
  ): PythonTypeInfo | undefined {
    const signature = this._extractSignature(entries);
    if (!signature) {
      return undefined;
    }

    if (signature.symbolKind === 'function' || signature.symbolKind === 'method') {
      return {
        declaredType: signature.label,
        inferredType: signature.returnType,
        symbolKind: signature.symbolKind,
        source,
      };
    }

    if (signature.symbolKind === 'class') {
      return {
        declaredType: signature.label,
        symbolKind: 'class',
        source,
      };
    }

    if (
      signature.symbolKind === 'variable' ||
      signature.symbolKind === 'parameter' ||
      signature.symbolKind === 'constant'
    ) {
      return {
        declaredType: signature.typeText,
        symbolKind: signature.symbolKind,
        source,
      };
    }

    return {
      declaredType: signature.label,
      source,
    };
  }

  private _deriveHoverSignatures(entries: Array<{ text: string; language?: string }>): PythonCallSignature[] | undefined {
    const signature = this._extractSignature(entries);
    if (!signature || (signature.symbolKind !== 'function' && signature.symbolKind !== 'method')) {
      return undefined;
    }

    const parameters = this._parseSignatureParameters(signature.parametersText ?? '');
    return [
      {
        label: signature.label,
        parameters,
        returnType: signature.returnType,
      },
    ];
  }

  private _deriveHoverDocumentation(entries: Array<{ text: string; language?: string }>): PythonDocumentation | undefined {
    const docText = entries
      .filter(entry => !entry.language && !this._isCopilotSummaryEntry(entry.text))
      .map(entry => this._cleanDocumentationText(entry.text))
      .filter(entry => entry.length > 0)
      .join('\n\n');
    if (!docText) {
      return undefined;
    }

    const summary = docText.split(/\r?\n/).map(line => line.trim()).find(line => line.length > 0);
    return {
      format: 'plaintext',
      summary,
      docstring: docText,
    };
  }

  private _extractSignature(
    entries: Array<{ text: string; language?: string }>,
  ):
    | {
        symbolKind?: PythonTypeInfo['symbolKind'];
        label: string;
        parametersText?: string;
        returnType?: string;
        typeText?: string;
      }
    | undefined {
    for (const entry of entries) {
      if (this._isCopilotSummaryEntry(entry.text)) {
        continue;
      }

      const normalized = entry.text
        .split(/\r?\n/)
        .map(line => line.trim())
        .filter(line => line.length > 0)
        .join(' ')
        .replace(/\s+/g, ' ')
        .trim();
      if (!normalized) {
        continue;
      }

      const prefixed = /^\((class|method|function|variable|parameter|constant)\)\s+(.+)$/.exec(normalized);
      const prefixKind = prefixed?.[1];
      const body = prefixed?.[2] ?? normalized;

      const functionMatch = /^def\s+([A-Za-z_][\w]*)\s*\((.*)\)\s*(?:->\s*(.+))?$/.exec(body);
      if (functionMatch) {
        return {
          symbolKind: prefixKind === 'method' ? 'method' : 'function',
          label: body,
          parametersText: functionMatch[2]?.trim(),
          returnType: functionMatch[3]?.trim(),
        };
      }

      const classKeywordMatch = /^class\s+([A-Za-z_][\w]*)/.exec(body);
      if (classKeywordMatch) {
        return {
          symbolKind: 'class',
          label: classKeywordMatch[1],
        };
      }

      if (prefixKind === 'class' && /^[A-Za-z_][\w]*$/.test(body)) {
        return {
          symbolKind: 'class',
          label: body,
        };
      }

      const variableMatch = /^([A-Za-z_][\w]*)\s*:\s*(.+)$/.exec(body);
      if (variableMatch) {
        return {
          symbolKind:
            prefixKind === 'parameter'
              ? 'parameter'
              : prefixKind === 'constant'
                ? 'constant'
                : 'variable',
          label: variableMatch[1].trim(),
          typeText: variableMatch[2].trim(),
        };
      }
    }
    return undefined;
  }

  private _cleanMarkdownSegment(value: string): string | undefined {
    const cleaned = value
      .replace(/<!--.*?-->/gs, '')
      .split(/\r?\n/)
      .map(line => line.trimEnd())
      .filter(line => line.trim() !== '---')
      .join('\n')
      .trim();

    return cleaned.length > 0 ? cleaned : undefined;
  }

  private _cleanDocumentationText(value: string): string {
    const lines = value
      .replace(/<!--.*?-->/gs, '')
      .split(/\r?\n/)
      .map(line => line.trim())
      .filter(line => line.length > 0 && line !== '---');

    if (lines.length >= 2 && /^\*\*[^*]+\*\*$/.test(lines[0])) {
      return lines.slice(1).join('\n').trim();
    }

    return lines.join('\n').trim();
  }

  private _isCopilotSummaryEntry(value: string): boolean {
    return value.includes('Generate Copilot summary') && value.includes('command:pylance.generateCopilotSummary');
  }

  private _parseSignatureParameters(signature: string): PythonCallSignature['parameters'] {
    const parameters: PythonCallSignature['parameters'] = [];
    let keywordOnly = false;

    for (const rawPart of this._splitTopLevel(signature, ',')) {
      const part = rawPart.trim();
      if (!part || part === '/') {
        continue;
      }
      if (part === '*') {
        keywordOnly = true;
        continue;
      }

      const defaultSplit = this._splitTopLevel(part, '=');
      const declaration = defaultSplit[0]?.trim() ?? part;
      const defaultValue = defaultSplit.length > 1 ? defaultSplit.slice(1).join('=').trim() : undefined;
      const typeSeparator = declaration.indexOf(':');
      const rawName = typeSeparator >= 0 ? declaration.slice(0, typeSeparator).trim() : declaration;
      const type = typeSeparator >= 0 ? declaration.slice(typeSeparator + 1).trim() : undefined;

      let kind: PythonCallSignature['parameters'][number]['kind'] = keywordOnly
        ? 'keyword-only'
        : 'positional-or-keyword';
      let name = rawName;
      if (name.startsWith('**')) {
        kind = 'kwargs';
        name = name.slice(2).trim();
      } else if (name.startsWith('*')) {
        kind = 'vararg';
        keywordOnly = true;
        name = name.slice(1).trim();
      }

      if (!name) {
        continue;
      }

      parameters.push({
        name,
        kind,
        type,
        defaultValue,
        optional: defaultValue !== undefined,
      });
    }

    return parameters;
  }

  private _splitTopLevel(value: string, separator: string): string[] {
    const parts: string[] = [];
    let current = '';
    let depth = 0;

    for (const character of value) {
      if (character === '(' || character === '[' || character === '{') {
        depth += 1;
      } else if (character === ')' || character === ']' || character === '}') {
        depth = Math.max(0, depth - 1);
      }

      if (character === separator && depth === 0) {
        parts.push(current);
        current = '';
        continue;
      }

      current += character;
    }

    parts.push(current);
    return parts;
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

  private _normalizeLimit(value: number | undefined): number | undefined {
    if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) {
      return undefined;
    }
    return Math.floor(value);
  }

  private _normalizeOffset(value: number | undefined): number {
    if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) {
      return 0;
    }
    return Math.floor(value);
  }

  private _slicePage<T>(items: T[], offset: number, limit: number | undefined): T[] {
    if (limit == null) {
      return items.slice(offset);
    }
    return items.slice(offset, offset + limit);
  }
}