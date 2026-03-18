import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import * as vscode from 'vscode';
import { fileExists } from '../src/utils/fileSystem.js';

describe('fileExists', () => {
  const uri = vscode.Uri.file('/tmp/log.txt');

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('returns false for missing files', async () => {
    vi.spyOn(vscode.workspace.fs, 'stat').mockRejectedValue({ code: 'FileNotFound' });

    await expect(fileExists(uri)).resolves.toBe(false);
  });

  it('rethrows unexpected filesystem errors', async () => {
    vi.spyOn(vscode.workspace.fs, 'stat').mockRejectedValue(new Error('permission denied'));

    await expect(fileExists(uri)).rejects.toThrow('permission denied');
  });

  it('returns true when the file exists', async () => {
    vi.spyOn(vscode.workspace.fs, 'stat').mockResolvedValue({} as any);

    await expect(fileExists(uri)).resolves.toBe(true);
  });
});