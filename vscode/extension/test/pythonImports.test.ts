import { describe, expect, it } from 'vitest';

import { PythonImportsService } from '../src/python/imports.js';

describe('PythonImportsService', () => {
  it('runs cleanup mode', async () => {
    const service = new PythonImportsService({
      runImportCleanup: async () => ({
        status: 'complete',
        args: ['check', '--select', 'F401', '--fix-only'],
        cwd: '/workspace',
        exitCode: 1,
        changed: true,
        applied: true,
        resolution: 'python-module',
      }),
      runOrganizeImports: async () => { throw new Error('should not be called'); },
    } as any);

    const result = await service.run({ mode: 'cleanup' });

    expect(result.mode).toBe('cleanup');
    expect('cleanup' in result).toBe(false);
    expect((result as any).changed).toBe(true);
  });

  it('runs organize mode', async () => {
    const service = new PythonImportsService({
      runImportCleanup: async () => { throw new Error('should not be called'); },
      runOrganizeImports: async () => ({
        status: 'complete',
        args: ['check', '--select', 'I', '--fix-only'],
        cwd: '/workspace',
        exitCode: 0,
        changed: false,
        applied: true,
        resolution: 'python-module',
      }),
    } as any);

    const result = await service.run({ mode: 'organize' });

    expect(result.mode).toBe('organize');
    expect((result as any).changed).toBe(false);
  });

  it('runs both in all mode (default)', async () => {
    const service = new PythonImportsService({
      runImportCleanup: async () => ({
        status: 'complete',
        args: ['check', '--select', 'F401', '--fix-only'],
        cwd: '/workspace',
        exitCode: 1,
        changed: true,
        applied: true,
        resolution: 'python-module',
      }),
      runOrganizeImports: async () => ({
        status: 'complete',
        args: ['check', '--select', 'I', '--fix-only'],
        cwd: '/workspace',
        exitCode: 0,
        changed: false,
        applied: true,
        resolution: 'python-module',
      }),
    } as any);

    const result = await service.run();

    expect(result.mode).toBe('all');
    expect('cleanup' in result).toBe(true);
    expect('organize' in result).toBe(true);
    const allResult = result as any;
    expect(allResult.cleanup.mode).toBe('cleanup');
    expect(allResult.cleanup.changed).toBe(true);
    expect(allResult.organize.mode).toBe('organize');
    expect(allResult.organize.changed).toBe(false);
  });
});
