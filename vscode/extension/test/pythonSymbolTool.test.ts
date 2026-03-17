import { describe, expect, it } from 'vitest';

import { PythonSymbolTool } from '../src/agent/tools/pythonSymbol.js';

describe('PythonSymbolTool', () => {
  it('returns symbol results as JSON', async () => {
    const service = {
      resolve: async () => ({
        generatedAt: '2026-03-15T00:00:00.000Z',
        action: 'definition',
        status: 'complete',
        request: { file: '/workspace/app.py', line: 10, column: 3 },
        backend: {
          provider: 'vscode-language-features',
          preferredSemanticBackend: 'ty',
          tyAvailable: true,
          note: 'test backend',
        },
        count: 1,
        results: [{ kind: 'location', path: '/workspace/pkg/mod.py', range: { startLine: 5, startColumn: 3, endLine: 5, endColumn: 11 } }],
      }),
    };

    const tool = new PythonSymbolTool(service as any);
    const result = await tool.invoke({ input: { action: 'definition', file: 'app.py', line: 10, column: 3 } } as any, {} as any);
    const text = ((result as any).content ?? []).map((part: { value?: string }) => part.value ?? '').join('');
    const payload = JSON.parse(text);

    expect(payload.status).toBe('complete');
    expect(payload.count).toBe(1);
    expect(payload.results[0].path).toBe('/workspace/pkg/mod.py');
  });
});