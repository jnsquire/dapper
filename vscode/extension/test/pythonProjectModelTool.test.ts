import { describe, expect, it } from 'vitest';

import { PythonProjectModelTool } from '../src/agent/tools/pythonProjectModel.js';

describe('PythonProjectModelTool', () => {
  it('returns project model results as JSON', async () => {
    const service = {
      getProjectModel: async () => ({
        generatedAt: '2026-03-15T00:00:00.000Z',
        searchRoots: ['/workspace'],
        python: { available: true, pythonPath: '/workspace/.venv/bin/python' },
        sourceRoots: [{ path: '/workspace/src', reason: 'src-directory' }],
        testRoots: [{ path: '/workspace/tests', reason: 'directory-name' }],
        configFiles: [{ kind: 'pyproject.toml', path: '/workspace/pyproject.toml' }],
        packageBoundaries: [{
          name: 'samplepkg',
          path: '/workspace/src/samplepkg',
          sourceRoot: '/workspace/src',
          kind: 'regular-package',
        }],
      }),
    };

    const tool = new PythonProjectModelTool(service as any);
    const result = await tool.invoke({ input: {} } as any, {} as any);
    const text = ((result as any).content ?? []).map((part: { value?: string }) => part.value ?? '').join('');
    const payload = JSON.parse(text);

    expect(payload.sourceRoots[0].path).toBe('/workspace/src');
    expect(payload.testRoots[0].path).toBe('/workspace/tests');
    expect(payload.packageBoundaries[0].name).toBe('samplepkg');
  });
});