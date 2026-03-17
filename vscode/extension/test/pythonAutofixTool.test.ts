import { describe, expect, it } from 'vitest';

import { PythonAutofixTool } from '../src/agent/tools/pythonAutofix.js';

describe('PythonAutofixTool', () => {
  it('returns autofix results as JSON', async () => {
    const service = {
      run: async () => ({
        mode: 'autofix',
        status: 'complete',
        args: ['check', '--fix-only'],
        exitCode: 1,
        changed: true,
        applied: true,
        resolution: 'python-module',
      }),
    };

    const tool = new PythonAutofixTool(service as any);
    const result = await tool.invoke({ input: {} } as any, {} as any);
    const text = ((result as any).content ?? []).map((part: { value?: string }) => part.value ?? '').join('');
    const payload = JSON.parse(text);

    expect(payload.mode).toBe('autofix');
    expect(payload.changed).toBe(true);
  });
});