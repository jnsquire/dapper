import { describe, expect, it } from 'vitest';

import { PythonRenameTool } from '../src/agent/tools/pythonRename.js';

describe('PythonRenameTool', () => {
  it('returns rename results as JSON', async () => {
    const service = {
      rename: async () => ({
        generatedAt: '2026-03-15T00:00:00.000Z',
        status: 'complete',
        applied: true,
        request: { file: '/workspace/app.py', line: 10, column: 3, newName: 'new_name' },
        backend: {
          provider: 'vscode-language-features',
          preferredSemanticBackend: 'ty',
          tyAvailable: true,
          note: 'test backend',
        },
        fileCount: 1,
        editCount: 2,
        edits: [{ path: '/workspace/app.py', range: { startLine: 5, startColumn: 3, endLine: 5, endColumn: 8 }, newText: 'new_name' }],
      }),
    };

    const tool = new PythonRenameTool(service as any);
    const result = await tool.invoke({ input: { file: 'app.py', line: 10, column: 3, newName: 'new_name' } } as any, {} as any);
    const text = ((result as any).content ?? []).map((part: { value?: string }) => part.value ?? '').join('');
    const payload = JSON.parse(text);

    expect(payload.status).toBe('complete');
    expect(payload.applied).toBe(true);
    expect(payload.editCount).toBe(2);
  });
});