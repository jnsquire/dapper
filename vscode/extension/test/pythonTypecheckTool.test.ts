import { describe, expect, it } from 'vitest';

import { PythonTypecheckTool } from '../src/agent/tools/pythonTypecheck.js';

describe('PythonTypecheckTool', () => {
  it('returns typecheck results as JSON', async () => {
    const service = {
      getTypecheck: async (input: unknown) => ({
        generatedAt: '2026-03-15T00:00:00.000Z',
        status: 'complete',
        completionStatus: 'partial',
        offset: (input as { offset?: number }).offset,
        truncated: false,
        totalDiagnostics: 1,
        outputBudget: {
          requestedLimit: 10,
          appliedLimit: 10,
          requestedOffset: 5,
          appliedOffset: 5,
          returnedItems: 1,
          totalItems: 1,
          truncated: false,
        },
        summary: { countsByFile: {}, countsByCode: {}, countsBySeverity: {}, hotspots: [] },
        diagnostics: [{ source: 'ty', severity: 'error', message: 'bad types' }],
        backend: { name: 'ty', status: 'complete', available: true, diagnosticCount: 1 },
      }),
    };

    const tool = new PythonTypecheckTool(service as any);
    const result = await tool.invoke({ input: { limit: 10, offset: 5 } } as any, {} as any);
    const text = ((result as any).content ?? []).map((part: { value?: string }) => part.value ?? '').join('');
    const payload = JSON.parse(text);

    expect(payload.status).toBe('complete');
    expect(payload.completionStatus).toBe('partial');
    expect(payload.offset).toBe(5);
    expect(payload.outputBudget.appliedOffset).toBe(5);
    expect(payload.backend.status).toBe('complete');
    expect(payload.diagnostics[0].message).toBe('bad types');
  });
});