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
            description: 'invalid-return-type: Return type does not match returned value: expected `str`, found `Literal[42]`',
            check_name: 'invalid-return-type',
            fingerprint: 'ty-return-1',
            severity: 'major',
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
    expect(result.completionStatus).toBe('complete');
    expect(result.totalDiagnostics).toBe(1);
    expect(result.backend.status).toBe('complete');
    expect(result.outputBudget).toEqual({
      requestedLimit: 10,
      appliedLimit: 10,
      requestedOffset: undefined,
      appliedOffset: 0,
      returnedItems: 1,
      totalItems: 1,
      truncated: false,
      nextOffset: undefined,
    });
    expect(result.summary).toBeDefined();
    expect(result.summary.countsByFile).toEqual({ 'app.py': 1 });
    expect(result.summary.countsByCode).toEqual({ 'invalid-return-type': 1 });
    expect(result.diagnostics).toEqual([
      expect.objectContaining({
        source: 'ty',
        severity: 'warning',
        nativeSeverity: 'major',
        code: 'invalid-return-type',
        message: 'Return type does not match returned value: expected `str`, found `Literal[42]`',
        file: 'app.py',
        startLine: 8,
        startColumn: 5,
        endLine: 8,
        endColumn: 6,
        fingerprint: 'ty-return-1',
        typeInfo: {
          declaredType: 'str',
          inferredType: 'Literal[42]',
          symbolKind: 'function',
          source: 'ty',
        },
        diagnosticContext: {
          summary: 'Invalid Return Type',
          explanation: 'Return type does not match returned value: expected `str`, found `Literal[42]`',
          rule: 'invalid-return-type',
          code: 'invalid-return-type',
        },
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
    expect(result.completionStatus).toBe('failed');
    expect(result.backend.status).toBe('unavailable');
    expect(result.diagnostics).toEqual([]);
  });

  it('supports paged typecheck results with explicit offsets', async () => {
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
            description: 'invalid-return-type: Return type does not match returned value: expected `str`, found `Literal[1]`',
            check_name: 'invalid-return-type',
            fingerprint: 'ty-return-1',
            severity: 'major',
            location: { path: 'app.py', positions: { begin: { line: 8, column: 5 }, end: { line: 8, column: 6 } } },
          },
          {
            description: 'invalid-return-type: Return type does not match returned value: expected `str`, found `Literal[2]`',
            check_name: 'invalid-return-type',
            fingerprint: 'ty-return-2',
            severity: 'major',
            location: { path: 'app.py', positions: { begin: { line: 9, column: 5 }, end: { line: 9, column: 6 } } },
          },
          {
            description: 'invalid-return-type: Return type does not match returned value: expected `str`, found `Literal[3]`',
            check_name: 'invalid-return-type',
            fingerprint: 'ty-return-3',
            severity: 'major',
            location: { path: 'app.py', positions: { begin: { line: 10, column: 5 }, end: { line: 10, column: 6 } } },
          },
        ],
        resolution: 'python-module',
      }),
    };

    const service = new PythonTypecheckService(environmentSnapshotService as any, tyRunnerService as any);
    const result = await service.getTypecheck({ files: ['app.py'], limit: 1, offset: 1 });

    expect(result.status).toBe('complete');
    expect(result.completionStatus).toBe('partial');
    expect(result.totalDiagnostics).toBe(3);
    expect(result.diagnostics).toHaveLength(1);
    expect(result.diagnostics[0]?.fingerprint).toBe('ty-return-2');
    expect(result.offset).toBe(1);
    expect(result.truncated).toBe(true);
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