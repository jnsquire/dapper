import { describe, expect, it } from 'vitest';

import { PythonTypecheckTool } from '../src/agent/tools/pythonTypecheck.js';

describe('PythonTypecheckTool', () => {
  it('returns typecheck results as JSON', async () => {
    const service = {
      getTypecheck: async () => ({
        generatedAt: '2026-03-15T00:00:00.000Z',
        status: 'complete',
        truncated: false,
        totalDiagnostics: 1,
        summary: { countsByFile: {}, countsByCode: {}, countsBySeverity: {}, hotspots: [] },
        diagnostics: [{ source: 'ty', severity: 'error', message: 'bad types' }],
        backend: { name: 'ty', status: 'complete', available: true, diagnosticCount: 1 },
      }),
    };

    const tool = new PythonTypecheckTool(service as any);
    const result = await tool.invoke({ input: {} } as any, {} as any);
    const text = ((result as any).content ?? []).map((part: { value?: string }) => part.value ?? '').join('');
    const payload = JSON.parse(text);

    expect(payload.status).toBe('complete');
    expect(payload.backend.status).toBe('complete');
    expect(payload.diagnostics[0].message).toBe('bad types');
  });
});