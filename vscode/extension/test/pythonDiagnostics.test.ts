import { describe, expect, it } from 'vitest';

import { PythonDiagnosticsService } from '../src/python/diagnostics.js';

describe('PythonDiagnosticsService', () => {
  it('normalizes Ruff and Ty diagnostics into a shared result', async () => {
    const environmentSnapshotService = {
      getSnapshot: async () => ({
        workspaceFolder: '/workspace',
        ruff: {
          available: true,
          resolution: 'python-module',
        },
        ty: {
          available: true,
          resolution: 'python-module',
        },
      }),
    };
    const ruffRunnerService = {
      runCheck: async () => ({
        status: 'complete',
        args: ['-m', 'ruff', 'check', '--output-format', 'json'],
        exitCode: 1,
        diagnostics: [
          {
            code: 'F401',
            message: 'unused import',
            filename: 'app.py',
            location: { row: 1, column: 8 },
            end_location: { row: 1, column: 14 },
            fix: { applicability: 'safe' },
            url: 'https://docs.astral.sh/ruff/rules/unused-import/',
          },
        ],
        resolution: 'python-module',
      }),
    };
    const tyRunnerService = {
      runCheck: async () => ({
        status: 'complete',
        args: ['check', '--output-format', 'gitlab'],
        exitCode: 1,
        diagnostics: [
          {
            description: 'Argument of type "Literal[1]" is not assignable to parameter of type "str"',
            check_name: 'invalid-argument-type',
            fingerprint: 'ty-1',
            severity: 'major',
            location: {
              path: 'app.py',
              positions: {
                begin: { line: 5, column: 12 },
                end: { line: 5, column: 13 },
              },
            },
          },
        ],
        resolution: 'python-module',
      }),
    };

    const service = new PythonDiagnosticsService(
      environmentSnapshotService as any,
      ruffRunnerService as any,
      tyRunnerService as any,
    );
    const result = await service.getDiagnostics({ files: ['app.py'], limit: 10 });

    expect(result.status).toBe('complete');
    expect(result.totalDiagnostics).toBe(2);
    expect(result.truncated).toBe(false);
    expect(result.summary).toBeDefined();
    expect(result.summary.countsByCode).toEqual({ 'invalid-argument-type': 1, 'F401': 1 });
    expect(result.diagnostics).toEqual([
      expect.objectContaining({
        source: 'ty',
        code: 'invalid-argument-type',
        nativeSeverity: 'major',
        message: 'Argument of type "Literal[1]" is not assignable to parameter of type "str"',
        file: 'app.py',
        startLine: 5,
        startColumn: 12,
        endLine: 5,
        endColumn: 13,
        fingerprint: 'ty-1',
      }),
      expect.objectContaining({
        source: 'ruff',
        code: 'F401',
        message: 'unused import',
        file: 'app.py',
        startLine: 1,
        startColumn: 8,
        endLine: 1,
        endColumn: 14,
        fixable: true,
      }),
    ]);
    expect(result.backends.ruff.status).toBe('complete');
    expect(result.backends.ty.status).toBe('complete');
  });

  it('applies the diagnostics limit', async () => {
    const environmentSnapshotService = {
      getSnapshot: async () => ({
        workspaceFolder: '/workspace',
        ruff: {
          available: true,
          resolution: 'python-module',
        },
        ty: {
          available: false,
          resolution: 'none',
          error: 'Ty missing',
        },
      }),
    };
    const ruffRunnerService = {
      runCheck: async () => ({
        status: 'complete',
        args: [],
        exitCode: 1,
        diagnostics: [
          { message: 'one' },
          { message: 'two' },
        ],
        resolution: 'python-module',
      }),
    };
    const tyRunnerService = {
      runCheck: async () => ({
        status: 'failed',
        args: [],
        exitCode: null,
        diagnostics: [],
        error: 'Ty missing',
        resolution: 'none',
      }),
    };

    const service = new PythonDiagnosticsService(
      environmentSnapshotService as any,
      ruffRunnerService as any,
      tyRunnerService as any,
    );
    const result = await service.getDiagnostics({ limit: 1 });

    expect(result.totalDiagnostics).toBe(2);
    expect(result.diagnostics).toHaveLength(1);
    expect(result.truncated).toBe(true);
    expect(result.backends.ty.status).toBe('unavailable');
  });
});