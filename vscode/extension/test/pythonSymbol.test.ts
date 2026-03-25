import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { PythonSymbolService } from '../src/python/symbols.js';

const vscode = await import('vscode');

describe('PythonSymbolService', () => {
  let service: PythonSymbolService;

  beforeEach(() => {
    service = new PythonSymbolService({
      getSnapshot: async () => ({
        ty: { available: true },
      }),
    } as any);

    Object.defineProperty(vscode.workspace, 'workspaceFolders', {
      configurable: true,
      value: [{ index: 0, name: 'project', uri: vscode.Uri.file('/workspace') }],
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('normalizes definition locations from VS Code providers', async () => {
    vi.spyOn(vscode.workspace, 'openTextDocument').mockResolvedValue({ uri: vscode.Uri.file('/workspace/app.py') } as any);
    vi.spyOn(vscode.commands, 'executeCommand').mockResolvedValue([
      new vscode.Location(
        vscode.Uri.file('/workspace/pkg/mod.py'),
        new vscode.Range(new vscode.Position(4, 2), new vscode.Position(4, 10)),
      ),
    ]);

    const result = await service.resolve({ action: 'definition', file: 'app.py', line: 10, column: 3 });

    expect(result.status).toBe('complete');
    expect(result.completionStatus).toBe('complete');
    expect(result.backend.preferredSemanticBackend).toBe('ty');
    expect(result.outputBudget).toEqual({
      requestedLimit: undefined,
      appliedLimit: undefined,
      requestedOffset: undefined,
      appliedOffset: 0,
      returnedItems: 1,
      totalItems: 1,
      truncated: false,
      nextOffset: undefined,
    });
    expect(result.results).toEqual([
      {
        kind: 'location',
        path: '/workspace/pkg/mod.py',
        range: { startLine: 5, startColumn: 3, endLine: 5, endColumn: 11 },
      },
    ]);
    expect(vscode.commands.executeCommand).toHaveBeenCalledWith(
      'vscode.executeDefinitionProvider',
      expect.objectContaining({ fsPath: '/workspace/app.py' }),
      expect.objectContaining({ line: 9, character: 2 }),
    );
  });

  it('normalizes hover results', async () => {
    vi.spyOn(vscode.workspace, 'openTextDocument').mockResolvedValue({ uri: vscode.Uri.file('/workspace/app.py') } as any);
    vi.spyOn(vscode.commands, 'executeCommand').mockResolvedValue([
      {
        contents: [
          { language: 'python', value: 'def greet(name: str) -> str' },
          'Greets the provided user.',
        ],
        range: new vscode.Range(new vscode.Position(1, 0), new vscode.Position(1, 5)),
      },
    ]);

    const result = await service.resolve({ action: 'hover', file: 'app.py', line: 2 });

    expect(result.status).toBe('complete');
    expect(result.completionStatus).toBe('complete');
    expect(result.results).toEqual([
      {
        kind: 'hover',
        contents: ['python\ndef greet(name: str) -> str', 'Greets the provided user.'],
        range: { startLine: 2, startColumn: 1, endLine: 2, endColumn: 6 },
        typeInfo: {
          declaredType: 'def greet(name: str) -> str',
          inferredType: 'str',
          symbolKind: 'function',
          source: 'ty',
        },
        signatures: [
          {
            label: 'def greet(name: str) -> str',
            parameters: [
              {
                name: 'name',
                kind: 'positional-or-keyword',
                type: 'str',
                defaultValue: undefined,
                optional: false,
              },
            ],
            returnType: 'str',
          },
        ],
        documentation: {
          format: 'plaintext',
          summary: 'Greets the provided user.',
          docstring: 'Greets the provided user.',
        },
      },
    ]);
  });

  it('extracts inspection data from markdown hover payloads', async () => {
    vi.spyOn(vscode.workspace, 'openTextDocument').mockResolvedValue({ uri: vscode.Uri.file('/workspace/app.py') } as any);
    vi.spyOn(vscode.commands, 'executeCommand').mockResolvedValue([
      {
        contents: {
          value: '```python\n(class) Person\n```\n---\nSimple dataclass for testing object inspection.\n<!--moduleHash:1937579081-->',
        },
      },
    ]);

    const result = await service.resolve({ action: 'hover', file: 'app.py', line: 4 });

    expect(result.results).toEqual([
      {
        kind: 'hover',
        contents: ['python\n(class) Person', 'Simple dataclass for testing object inspection.'],
        typeInfo: {
          declaredType: 'Person',
          symbolKind: 'class',
          source: 'ty',
        },
        signatures: undefined,
        documentation: {
          format: 'plaintext',
          summary: 'Simple dataclass for testing object inspection.',
          docstring: 'Simple dataclass for testing object inspection.',
        },
      },
    ]);
  });

  it('extracts method signatures from observed Ty markdown hover payloads', async () => {
    vi.spyOn(vscode.workspace, 'openTextDocument').mockResolvedValue({ uri: vscode.Uri.file('/workspace/app.py') } as any);
    vi.spyOn(vscode.commands, 'executeCommand').mockResolvedValue([
      {
        contents: {
          value:
            '```python\n(method) def add_data(\n    self: Self@DataProcessor,\n    category: str,\n    items: list[Any]\n) -> None\n```\n---\nAdd data to the processor.\n<!--moduleHash:1937579081-->',
        },
      },
    ]);

    const result = await service.resolve({ action: 'hover', file: 'app.py', line: 8 });

    expect(result.results).toEqual([
      {
        kind: 'hover',
        contents: [
          'python\n(method) def add_data(\n    self: Self@DataProcessor,\n    category: str,\n    items: list[Any]\n) -> None',
          'Add data to the processor.',
        ],
        typeInfo: {
          declaredType: 'def add_data( self: Self@DataProcessor, category: str, items: list[Any] ) -> None',
          inferredType: 'None',
          symbolKind: 'method',
          source: 'ty',
        },
        signatures: [
          {
            label: 'def add_data( self: Self@DataProcessor, category: str, items: list[Any] ) -> None',
            parameters: [
              {
                name: 'self',
                kind: 'positional-or-keyword',
                type: 'Self@DataProcessor',
                defaultValue: undefined,
                optional: false,
              },
              {
                name: 'category',
                kind: 'positional-or-keyword',
                type: 'str',
                defaultValue: undefined,
                optional: false,
              },
              {
                name: 'items',
                kind: 'positional-or-keyword',
                type: 'list[Any]',
                defaultValue: undefined,
                optional: false,
              },
            ],
            returnType: 'None',
          },
        ],
        documentation: {
          format: 'plaintext',
          summary: 'Add data to the processor.',
          docstring: 'Add data to the processor.',
        },
      },
    ]);
  });

  it('extracts variable and constant inspection data from observed Ty hover payloads', async () => {
    vi.spyOn(vscode.workspace, 'openTextDocument').mockResolvedValue({ uri: vscode.Uri.file('/workspace/app.py') } as any);
    vi.spyOn(vscode.commands, 'executeCommand').mockResolvedValue([
      {
        contents: ['```python\n(variable) unit_price: float\n```\n<!--moduleHash:-807463382-->'],
      },
      {
        contents: ['```python\n(constant) R: type[R]\n```\n<!--moduleHash:-1339023190-->'],
      },
    ]);

    const result = await service.resolve({ action: 'hover', file: 'app.py', line: 10 });

    expect(result.results).toEqual([
      {
        kind: 'hover',
        contents: ['python\n(variable) unit_price: float'],
        typeInfo: {
          declaredType: 'float',
          symbolKind: 'variable',
          source: 'ty',
        },
        signatures: undefined,
        documentation: undefined,
      },
      {
        kind: 'hover',
        contents: ['python\n(constant) R: type[R]'],
        typeInfo: {
          declaredType: 'type[R]',
          symbolKind: 'constant',
          source: 'ty',
        },
        signatures: undefined,
        documentation: undefined,
      },
    ]);
  });

  it('ignores Copilot summary noise and strips markdown parameter headings from docs', async () => {
    vi.spyOn(vscode.workspace, 'openTextDocument').mockResolvedValue({ uri: vscode.Uri.file('/workspace/app.py') } as any);
    vi.spyOn(vscode.commands, 'executeCommand').mockResolvedValue([
      {
        contents: [
          '```python\n(parameter) command: str\n```\n\n\n**command**  \nThe command to execute\n\n---\n<!--moduleHash:-1339023190-->',
          '[$(sparkle) Generate Copilot summary](command:pylance.generateCopilotSummary?x "AI-generated content may be incorrect.")',
        ],
      },
    ]);

    const result = await service.resolve({ action: 'hover', file: 'app.py', line: 12 });

    expect(result.results).toEqual([
      {
        kind: 'hover',
        contents: [
          'python\n(parameter) command: str',
          '**command**\nThe command to execute',
          '[$(sparkle) Generate Copilot summary](command:pylance.generateCopilotSummary?x "AI-generated content may be incorrect.")',
        ],
        typeInfo: {
          declaredType: 'str',
          symbolKind: 'parameter',
          source: 'ty',
        },
        signatures: undefined,
        documentation: {
          format: 'plaintext',
          summary: 'The command to execute',
          docstring: 'The command to execute',
        },
      },
    ]);
  });

  it('surfaces provider failures cleanly', async () => {
    vi.spyOn(vscode.workspace, 'openTextDocument').mockRejectedValue(new Error('missing file'));

    const result = await service.resolve({ action: 'references', file: 'missing.py', line: 1 });

    expect(result.status).toBe('failed');
    expect(result.completionStatus).toBe('failed');
    expect(result.error).toBe('missing file');
    expect(result.outputBudget).toEqual({
      requestedLimit: undefined,
      appliedLimit: undefined,
      requestedOffset: undefined,
      appliedOffset: 0,
      returnedItems: 0,
      totalItems: 0,
      truncated: false,
      nextOffset: undefined,
    });
    expect(result.results).toEqual([]);
  });

  it('supports paged symbol results with explicit offsets', async () => {
    vi.spyOn(vscode.workspace, 'openTextDocument').mockResolvedValue({ uri: vscode.Uri.file('/workspace/app.py') } as any);
    vi.spyOn(vscode.commands, 'executeCommand').mockResolvedValue([
      new vscode.Location(
        vscode.Uri.file('/workspace/pkg/one.py'),
        new vscode.Range(new vscode.Position(1, 0), new vscode.Position(1, 3)),
      ),
      new vscode.Location(
        vscode.Uri.file('/workspace/pkg/two.py'),
        new vscode.Range(new vscode.Position(2, 0), new vscode.Position(2, 3)),
      ),
      new vscode.Location(
        vscode.Uri.file('/workspace/pkg/three.py'),
        new vscode.Range(new vscode.Position(3, 0), new vscode.Position(3, 5)),
      ),
    ]);

    const result = await service.resolve({ action: 'references', file: 'app.py', line: 10, limit: 1, offset: 1 });

    expect(result.status).toBe('complete');
    expect(result.completionStatus).toBe('partial');
    expect(result.count).toBe(1);
    expect(result.results).toEqual([
      {
        kind: 'location',
        path: '/workspace/pkg/two.py',
        range: { startLine: 3, startColumn: 1, endLine: 3, endColumn: 4 },
      },
    ]);
    expect(result.outputBudget).toEqual({
      requestedLimit: 1,
      appliedLimit: 1,
      requestedOffset: 1,
      appliedOffset: 1,
      returnedItems: 1,
      totalItems: 3,
      truncated: true,
      nextOffset: 2,
    });
  });
});