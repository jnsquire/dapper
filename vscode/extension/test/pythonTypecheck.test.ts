import { describe, expect, it } from 'vitest';

import { PythonTypecheckService } from '../src/python/typecheck.js';

describe('PythonTypecheckService', () => {
  it('normalizes Ty diagnostics into the shared schema', async () => {
    const environmentSnapshotService = {
      getSnapshot: async () => ({
        workspaceFolder: '/workspace',
        ty: {
          available: true,
          resolution: 'python-module',
        },
      }),
    };
    const tyRunnerService = {
      runCheck: async () => ({
        status: 'complete',
        args: ['check', '--output-format', 'gitlab'],
        exitCode: 1,
        diagnostics: [
          {
            description: 'Value of type "int" is not assignable to return type "str"',
            check_name: 'invalid-return-type',
            fingerprint: 'ty-return-1',
            severity: 'error',
            location: {
              path: 'app.py',
              positions: {
                begin: { line: 8, column: 5 },
                end: { line: 8, column: 6 },
              },
            },
          },
        ],
        resolution: 'python-module',
      }),
    };

    const service = new PythonTypecheckService(environmentSnapshotService as any, tyRunnerService as any);
    const result = await service.getTypecheck({ files: ['app.py'], limit: 10 });

    expect(result.status).toBe('complete');
    expect(result.totalDiagnostics).toBe(1);
    expect(result.backend.status).toBe('complete');
    expect(result.summary).toBeDefined();
    expect(result.summary.countsByFile).toEqual({ 'app.py': 1 });
    expect(result.summary.countsByCode).toEqual({ 'invalid-return-type': 1 });
    expect(result.diagnostics).toEqual([
      expect.objectContaining({
        source: 'ty',
        severity: 'error',
        nativeSeverity: 'error',
        code: 'invalid-return-type',
        message: 'Value of type "int" is not assignable to return type "str"',
        file: 'app.py',
        startLine: 8,
        startColumn: 5,
        endLine: 8,
        endColumn: 6,
        fingerprint: 'ty-return-1',
      }),
    ]);
  });

  it('reports Ty unavailability clearly', async () => {
    const environmentSnapshotService = {
      getSnapshot: async () => ({
        workspaceFolder: '/workspace',
        ty: {
          available: false,
          resolution: 'none',
          error: 'Ty missing',
        },
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

    const service = new PythonTypecheckService(environmentSnapshotService as any, tyRunnerService as any);
    const result = await service.getTypecheck();

    expect(result.status).toBe('failed');
    expect(result.backend.status).toBe('unavailable');
    expect(result.diagnostics).toEqual([]);
  });
});