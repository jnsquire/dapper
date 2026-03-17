import { describe, expect, it } from 'vitest';

import { PythonDiagnosticsTool } from '../src/agent/tools/pythonDiagnostics.js';

describe('PythonDiagnosticsTool', () => {
  it('returns diagnostics as JSON', async () => {
    const service = {
      getDiagnostics: async () => ({
        generatedAt: '2026-03-15T00:00:00.000Z',
        status: 'complete',
        truncated: false,
        totalDiagnostics: 1,
        summary: { countsByFile: {}, countsByCode: {}, countsBySeverity: {}, hotspots: [] },
        diagnostics: [{ source: 'ruff', severity: 'warning', message: 'unused import' }],
        backends: {
          ruff: { name: 'ruff', status: 'complete', available: true, diagnosticCount: 1 },
          ty: { name: 'ty', status: 'unavailable', available: false, diagnosticCount: 0 },
        },
      }),
    };

    const tool = new PythonDiagnosticsTool(service as any);
    const result = await tool.invoke({ input: {} } as any, {} as any);
    const text = ((result as any).content ?? []).map((part: { value?: string }) => part.value ?? '').join('');
    const payload = JSON.parse(text);

    expect(payload.status).toBe('complete');
    expect(payload.totalDiagnostics).toBe(1);
    expect(payload.diagnostics[0].message).toBe('unused import');
  });
});