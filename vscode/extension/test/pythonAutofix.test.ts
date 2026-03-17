import { describe, expect, it } from 'vitest';

import { PythonAutofixService } from '../src/python/autofix.js';

describe('PythonAutofixService', () => {
  it('returns Ruff autofix results', async () => {
    const service = new PythonAutofixService({
      runAutofix: async () => ({
        status: 'complete',
        args: ['check', '--fix-only'],
        cwd: '/workspace',
        exitCode: 1,
        changed: true,
        applied: true,
        resolution: 'python-module',
      }),
    } as any);

    const result = await service.run({ files: ['app.py'] });

    expect(result.mode).toBe('autofix');
    expect(result.changed).toBe(true);
    expect(result.applied).toBe(true);
    expect(result.diffSummary).toBeUndefined();
  });

  it('includes diff summary in preview mode', async () => {
    const diff = '--- a/app.py\n+++ b/app.py\n@@ -1,3 +1,2 @@\n import os\n-import sys\n print(os.getcwd())\n--- a/utils.py\n+++ b/utils.py\n@@ -1,2 +1,1 @@\n-import json\n pass\n';
    const service = new PythonAutofixService({
      runAutofix: async () => ({
        status: 'complete',
        args: ['check', '--diff'],
        cwd: '/workspace',
        exitCode: 1,
        changed: true,
        applied: false,
        diff,
        resolution: 'python-module',
      }),
    } as any);

    const result = await service.run({ apply: false });

    expect(result.mode).toBe('autofix');
    expect(result.diff).toBe(diff);
    expect(result.diffSummary).toBeDefined();
    expect(result.diffSummary!.filesAffected).toBe(2);
    expect(result.diffSummary!.files).toEqual(['app.py', 'utils.py']);
    expect(result.diffSummary!.truncated).toBe(false);
  });

  it('truncates large diffs and sets truncated flag', async () => {
    const largeDiff = '--- a/app.py\n+++ b/app.py\n' + 'x'.repeat(40_000) + '\n';
    const service = new PythonAutofixService({
      runAutofix: async () => ({
        status: 'complete',
        args: ['check', '--diff'],
        cwd: '/workspace',
        exitCode: 1,
        changed: true,
        applied: false,
        diff: largeDiff,
        resolution: 'python-module',
      }),
    } as any);

    const result = await service.run({ apply: false });

    expect(result.diffSummary!.truncated).toBe(true);
    expect(result.diffSummary!.totalDiffBytes).toBeGreaterThan(32_768);
    expect(result.diff!.length).toBeLessThan(largeDiff.length);
    expect(result.diff!).toContain('... (diff truncated)');
  });
});