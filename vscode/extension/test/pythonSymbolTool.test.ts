import { describe, expect, it } from 'vitest';

import { PythonSymbolTool } from '../src/agent/tools/pythonSymbol.js';

describe('PythonSymbolTool', () => {
  it('returns symbol results as JSON', async () => {
    const service = {
      resolve: async (input: unknown) => ({
        generatedAt: '2026-03-15T00:00:00.000Z',
        action: 'definition',
        status: 'complete',
        completionStatus: 'partial',
        request: { file: '/workspace/app.py', line: 10, column: 3 },
        backend: {
          provider: 'vscode-language-features',
          preferredSemanticBackend: 'ty',
          tyAvailable: true,
          note: 'test backend',
        },
        count: 1,
        outputBudget: {
          requestedLimit: 5,
          appliedLimit: 5,
          requestedOffset: 10,
          appliedOffset: (input as { offset?: number }).offset,
          returnedItems: 1,
          totalItems: 3,
          truncated: true,
          nextOffset: 11,
        },
        results: [{ kind: 'location', path: '/workspace/pkg/mod.py', range: { startLine: 5, startColumn: 3, endLine: 5, endColumn: 11 } }],
      }),
    };

    const tool = new PythonSymbolTool(service as any);
    const result = await tool.invoke({ input: { action: 'definition', file: 'app.py', line: 10, column: 3, limit: 5, offset: 10 } } as any, {} as any);
    const text = ((result as any).content ?? []).map((part: { value?: string }) => part.value ?? '').join('');
    const payload = JSON.parse(text);

    expect(payload.status).toBe('complete');
    expect(payload.completionStatus).toBe('partial');
    expect(payload.count).toBe(1);
    expect(payload.outputBudget.appliedOffset).toBe(10);
    expect(payload.results[0].path).toBe('/workspace/pkg/mod.py');
  });
});