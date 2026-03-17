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
    expect(result.backend.preferredSemanticBackend).toBe('ty');
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
    expect(result.results).toEqual([
      {
        kind: 'hover',
        contents: ['python\ndef greet(name: str) -> str', 'Greets the provided user.'],
        range: { startLine: 2, startColumn: 1, endLine: 2, endColumn: 6 },
      },
    ]);
  });

  it('surfaces provider failures cleanly', async () => {
    vi.spyOn(vscode.workspace, 'openTextDocument').mockRejectedValue(new Error('missing file'));

    const result = await service.resolve({ action: 'references', file: 'missing.py', line: 1 });

    expect(result.status).toBe('failed');
    expect(result.error).toBe('missing file');
    expect(result.results).toEqual([]);
  });
});