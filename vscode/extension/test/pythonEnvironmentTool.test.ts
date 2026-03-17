import { describe, expect, it } from 'vitest';

import { PythonEnvironmentTool } from '../src/agent/tools/pythonEnvironment.js';

describe('PythonEnvironmentTool', () => {
  it('returns the environment snapshot as JSON', async () => {
    const service = {
      getSnapshot: async () => ({
        generatedAt: '2026-03-15T00:00:00.000Z',
        searchRoots: ['/workspace'],
        python: { available: true, source: 'activeInterpreter', pythonPath: '/workspace/.venv/bin/python' },
        ty: { available: true, resolution: 'python-module', args: ['-m', 'ty'] },
        ruff: { available: true, resolution: 'python-module', args: ['-m', 'ruff'] },
        tyConfig: { configured: false, files: [] },
        ruffConfig: { configured: false, files: [] },
      }),
    };

    const tool = new PythonEnvironmentTool(service as any);
    const result = await tool.invoke({ input: {} } as any, {} as any);
    const text = ((result as any).content ?? []).map((part: { value?: string }) => part.value ?? '').join('');
    const payload = JSON.parse(text);

    expect(payload.python.pythonPath).toBe('/workspace/.venv/bin/python');
    expect(payload.ty.available).toBe(true);
    expect(payload.ruff.available).toBe(true);
  });
});