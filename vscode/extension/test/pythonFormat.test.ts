import { describe, expect, it } from 'vitest';

import { PythonFormatService } from '../src/python/format.js';

describe('PythonFormatService', () => {
  it('returns Ruff format results', async () => {
    const service = new PythonFormatService({
      runFormat: async () => ({
        status: 'complete',
        args: ['format'],
        cwd: '/workspace',
        exitCode: 1,
        changed: true,
        applied: false,
        diff: '--- a/app.py\n+++ b/app.py',
        resolution: 'python-module',
      }),
    } as any);

    const result = await service.run({ files: ['app.py'], apply: false });

    expect(result.mode).toBe('format');
    expect(result.applied).toBe(false);
    expect(result.diff).toContain('app.py');
    expect(result.diffSummary).toBeDefined();
    expect(result.diffSummary!.filesAffected).toBe(1);
    expect(result.diffSummary!.files).toEqual(['app.py']);
    expect(result.diffSummary!.truncated).toBe(false);
  });

  it('omits diff summary when no diff is present', async () => {
    const service = new PythonFormatService({
      runFormat: async () => ({
        status: 'complete',
        args: ['format', '--exit-non-zero-on-format'],
        cwd: '/workspace',
        exitCode: 0,
        changed: false,
        applied: true,
        resolution: 'python-module',
      }),
    } as any);

    const result = await service.run();

    expect(result.mode).toBe('format');
    expect(result.diffSummary).toBeUndefined();
  });
});