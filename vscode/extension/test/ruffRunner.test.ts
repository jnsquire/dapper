import { describe, expect, it, vi } from 'vitest';

import * as processRunner from '../src/environment/processRunner.js';
import { RuffRunnerService } from '../src/python/ruffRunner.js';

const fakeOutputChannel: any = {
  info: () => {}, debug: () => {}, warn: () => {}, error: () => {}, trace: () => {},
};

describe('RuffRunnerService', () => {
  it('runs Ruff check with structured JSON output', async () => {
    const snapshotService = {
      getSnapshot: async () => ({
        workspaceFolder: '/workspace',
        ruff: {
          available: true,
          resolution: 'python-module',
          command: '/workspace/.venv/bin/python',
          args: ['-m', 'ruff'],
        },
      }),
    };

    const runnerSpy = vi.spyOn(processRunner, 'runLoggedProcessResult').mockResolvedValue({
      ok: false,
      code: 1,
      output: '[{"code":"F401","message":"unused import","filename":"app.py"}]',
      stdout: '[{"code":"F401","message":"unused import","filename":"app.py"}]',
      stderr: '',
    });

    const service = new RuffRunnerService(fakeOutputChannel, snapshotService as any);
    const result = await service.runCheck({ files: ['app.py'] });

    expect(runnerSpy).toHaveBeenCalledWith(
      fakeOutputChannel,
      '/workspace/.venv/bin/python',
      ['-m', 'ruff', 'check', '--output-format', 'json', 'app.py'],
      { label: 'ruff check', cwd: '/workspace' },
    );
    expect(result.status).toBe('complete');
    expect(result.diagnostics).toHaveLength(1);
  });

  it('fails clearly when Ruff is unavailable', async () => {
    const snapshotService = {
      getSnapshot: async () => ({
        workspaceFolder: '/workspace',
        ruff: {
          available: false,
          resolution: 'none',
          args: [],
          error: 'Ruff missing',
        },
      }),
    };

    const service = new RuffRunnerService(fakeOutputChannel, snapshotService as any);
    const result = await service.runCheck();

    expect(result.status).toBe('failed');
    expect(result.error).toBe('Ruff missing');
    expect(result.diagnostics).toEqual([]);
  });

  it('runs Ruff autofix in preview mode with diff output', async () => {
    const snapshotService = {
      getSnapshot: async () => ({
        workspaceFolder: '/workspace',
        ruff: {
          available: true,
          resolution: 'python-module',
          command: '/workspace/.venv/bin/python',
          args: ['-m', 'ruff'],
        },
      }),
    };

    const runnerSpy = vi.spyOn(processRunner, 'runLoggedProcessResult').mockResolvedValue({
      ok: false,
      code: 1,
      output: '--- a/app.py\n+++ b/app.py\n',
      stdout: '--- a/app.py\n+++ b/app.py\n',
      stderr: '',
    });

    const service = new RuffRunnerService(fakeOutputChannel, snapshotService as any);
    const result = await service.runAutofix({ files: ['app.py'], apply: false });

    expect(runnerSpy).toHaveBeenCalledWith(
      fakeOutputChannel,
      '/workspace/.venv/bin/python',
      ['-m', 'ruff', 'check', '--diff', 'app.py'],
      { label: 'ruff autofix', cwd: '/workspace' },
    );
    expect(result.status).toBe('complete');
    expect(result.changed).toBe(true);
    expect(result.applied).toBe(false);
  });

  it('runs Ruff format with apply mode', async () => {
    const snapshotService = {
      getSnapshot: async () => ({
        workspaceFolder: '/workspace',
        ruff: {
          available: true,
          resolution: 'python-module',
          command: '/workspace/.venv/bin/python',
          args: ['-m', 'ruff'],
        },
      }),
    };

    const runnerSpy = vi.spyOn(processRunner, 'runLoggedProcessResult').mockResolvedValue({
      ok: false,
      code: 1,
      output: '',
      stdout: '',
      stderr: '',
    });

    const service = new RuffRunnerService(fakeOutputChannel, snapshotService as any);
    const result = await service.runFormat({ files: ['app.py'] });

    expect(runnerSpy).toHaveBeenCalledWith(
      fakeOutputChannel,
      '/workspace/.venv/bin/python',
      ['-m', 'ruff', 'format', '--exit-non-zero-on-format', 'app.py'],
      { label: 'ruff format', cwd: '/workspace' },
    );
    expect(result.status).toBe('complete');
    expect(result.changed).toBe(true);
    expect(result.applied).toBe(true);
  });
});