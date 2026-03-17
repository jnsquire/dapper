import { describe, expect, it, vi } from 'vitest';

import * as processRunner from '../src/environment/processRunner.js';
import { TyRunnerService } from '../src/python/tyRunner.js';

const fakeOutputChannel: any = {
  info: () => {}, debug: () => {}, warn: () => {}, error: () => {}, trace: () => {},
};

describe('TyRunnerService', () => {
  it('runs Ty check with GitLab JSON output', async () => {
    const snapshotService = {
      getSnapshot: async () => ({
        workspaceFolder: '/workspace',
        python: {
          pythonPath: '/workspace/.venv/bin/python',
        },
        ty: {
          available: true,
          resolution: 'python-module',
          command: '/workspace/.venv/bin/python',
          args: ['-m', 'ty'],
        },
      }),
    };

    const runnerSpy = vi.spyOn(processRunner, 'runLoggedProcessResult').mockResolvedValue({
      ok: false,
      code: 1,
      output: '[{"description":"bad types","check_name":"invalid-argument-type","severity":"major","location":{"path":"app.py","lines":{"begin":4}}}]',
      stdout: '[{"description":"bad types","check_name":"invalid-argument-type","severity":"major","location":{"path":"app.py","lines":{"begin":4}}}]',
      stderr: '',
    });

    const service = new TyRunnerService(fakeOutputChannel, snapshotService as any);
    const result = await service.runCheck({ files: ['app.py'] });

    expect(runnerSpy).toHaveBeenCalledWith(
      fakeOutputChannel,
      '/workspace/.venv/bin/python',
      ['-m', 'ty', 'check', '--output-format', 'gitlab', '--no-progress', '--project', '/workspace', '--python', '/workspace/.venv/bin/python', 'app.py'],
      { label: 'ty check', cwd: '/workspace' },
    );
    expect(result.status).toBe('complete');
    expect(result.diagnostics).toHaveLength(1);
  });

  it('fails clearly when Ty is unavailable', async () => {
    const snapshotService = {
      getSnapshot: async () => ({
        workspaceFolder: '/workspace',
        ty: {
          available: false,
          resolution: 'none',
          args: [],
          error: 'Ty missing',
        },
      }),
    };

    const service = new TyRunnerService(fakeOutputChannel, snapshotService as any);
    const result = await service.runCheck();

    expect(result.status).toBe('failed');
    expect(result.error).toBe('Ty missing');
    expect(result.diagnostics).toEqual([]);
  });

  it('includes stderr in error when Ty output is not parseable', async () => {
    const snapshotService = {
      getSnapshot: async () => ({
        workspaceFolder: '/workspace',
        python: {
          pythonPath: '/workspace/.venv/bin/python',
        },
        ty: {
          available: true,
          resolution: 'python-module',
          command: '/workspace/.venv/bin/python',
          args: ['-m', 'ty'],
        },
      }),
    };

    vi.spyOn(processRunner, 'runLoggedProcessResult').mockResolvedValue({
      ok: false,
      code: 2,
      output: 'error: invalid option --bad-flag\nUsage: ty check [OPTIONS]',
      stdout: '',
      stderr: 'error: invalid option --bad-flag\nUsage: ty check [OPTIONS]',
    });

    const service = new TyRunnerService(fakeOutputChannel, snapshotService as any);
    const result = await service.runCheck();

    expect(result.status).toBe('failed');
    expect(result.error).toContain('invalid option');
  });
});