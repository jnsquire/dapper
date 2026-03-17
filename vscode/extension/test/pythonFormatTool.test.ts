import { describe, expect, it } from 'vitest';

import { PythonFormatTool } from '../src/agent/tools/pythonFormat.js';

describe('PythonFormatTool', () => {
  it('returns format results as JSON', async () => {
    const service = {
      run: async () => ({
        mode: 'format',
        status: 'complete',
        args: ['format'],
        exitCode: 0,
        changed: false,
        applied: true,
        resolution: 'python-module',
      }),
    };

    const tool = new PythonFormatTool(service as any);
    const result = await tool.invoke({ input: {} } as any, {} as any);
    const text = ((result as any).content ?? []).map((part: { value?: string }) => part.value ?? '').join('');
    const payload = JSON.parse(text);

    expect(payload.mode).toBe('format');
    expect(payload.status).toBe('complete');
  });
});