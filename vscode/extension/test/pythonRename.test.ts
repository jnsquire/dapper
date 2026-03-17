import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { PythonRenameService } from '../src/python/rename.js';

const vscode = await import('vscode');

describe('PythonRenameService', () => {
  let service: PythonRenameService;

  beforeEach(() => {
    service = new PythonRenameService({
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

  it('applies semantic rename edits by default', async () => {
    const edit = new vscode.WorkspaceEdit();
    edit.set(vscode.Uri.file('/workspace/app.py'), [
      new vscode.TextEdit(new vscode.Range(new vscode.Position(4, 2), new vscode.Position(4, 7)), 'new_name'),
      new vscode.TextEdit(new vscode.Range(new vscode.Position(8, 1), new vscode.Position(8, 6)), 'new_name'),
    ]);

    vi.spyOn(vscode.workspace, 'openTextDocument').mockResolvedValue({ uri: vscode.Uri.file('/workspace/app.py') } as any);
    vi.spyOn(vscode.commands, 'executeCommand').mockResolvedValue(edit);
    const applyEditSpy = vi.spyOn(vscode.workspace, 'applyEdit').mockResolvedValue(true);

    const result = await service.rename({ file: 'app.py', line: 5, column: 3, newName: 'new_name' });

    expect(result.status).toBe('complete');
    expect(result.applied).toBe(true);
    expect(result.fileCount).toBe(1);
    expect(result.editCount).toBe(2);
    expect(result.edits[0]).toEqual({
      path: '/workspace/app.py',
      range: { startLine: 5, startColumn: 3, endLine: 5, endColumn: 8 },
      newText: 'new_name',
    });
    expect(applyEditSpy).toHaveBeenCalledWith(edit);
  });

  it('supports preview mode without applying edits', async () => {
    const edit = new vscode.WorkspaceEdit();
    edit.set(vscode.Uri.file('/workspace/app.py'), [
      new vscode.TextEdit(new vscode.Range(new vscode.Position(1, 0), new vscode.Position(1, 4)), 'renamed'),
    ]);

    vi.spyOn(vscode.workspace, 'openTextDocument').mockResolvedValue({ uri: vscode.Uri.file('/workspace/app.py') } as any);
    vi.spyOn(vscode.commands, 'executeCommand').mockResolvedValue(edit);
    const applyEditSpy = vi.spyOn(vscode.workspace, 'applyEdit').mockResolvedValue(true);

    const result = await service.rename({ file: 'app.py', line: 2, newName: 'renamed', apply: false });

    expect(result.status).toBe('complete');
    expect(result.applied).toBe(false);
    expect(result.editCount).toBe(1);
    expect(applyEditSpy).not.toHaveBeenCalled();
  });

  it('surfaces rename provider failures cleanly', async () => {
    vi.spyOn(vscode.workspace, 'openTextDocument').mockResolvedValue({ uri: vscode.Uri.file('/workspace/app.py') } as any);
    vi.spyOn(vscode.commands, 'executeCommand').mockRejectedValue(new Error('rename not supported'));

    const result = await service.rename({ file: 'app.py', line: 1, newName: 'renamed' });

    expect(result.status).toBe('failed');
    expect(result.error).toBe('rename not supported');
    expect(result.edits).toEqual([]);
  });
});