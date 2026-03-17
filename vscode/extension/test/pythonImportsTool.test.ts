import { describe, expect, it } from 'vitest';

import { PythonImportsTool } from '../src/agent/tools/pythonImports.js';

describe('PythonImportsTool', () => {
  it('returns imports results as JSON', async () => {
    const service = {
      run: async () => ({
        mode: 'all',
        cleanup: {
          mode: 'cleanup',
          status: 'complete',
          args: ['check', '--select', 'F401', '--fix-only'],
          exitCode: 0,
          changed: false,
          applied: true,
          resolution: 'python-module',
        },
        organize: {
          mode: 'organize',
          status: 'complete',
          args: ['check', '--select', 'I', '--fix-only'],
          exitCode: 0,
          changed: false,
          applied: true,
          resolution: 'python-module',
        },
      }),
    };

    const tool = new PythonImportsTool(service as any);
    const result = await tool.invoke({ input: {} } as any, {} as any);
    const text = ((result as any).content ?? []).map((part: { value?: string }) => part.value ?? '').join('');
    const payload = JSON.parse(text);

    expect(payload.mode).toBe('all');
    expect(payload.cleanup.mode).toBe('cleanup');
    expect(payload.organize.mode).toBe('organize');
  });

  it('passes mode through to service', async () => {
    let receivedOptions: any;
    const service = {
      run: async (opts: any) => {
        receivedOptions = opts;
        return { mode: 'cleanup', status: 'complete', changed: false, applied: true };
      },
    };

    const tool = new PythonImportsTool(service as any);
    await tool.invoke({ input: { mode: 'cleanup' } } as any, {} as any);

    expect(receivedOptions.mode).toBe('cleanup');
  });
});
