import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';

import * as processRunner from '../src/environment/processRunner.js';
import { PythonEnvironmentManager } from '../src/python/environment.js';
import { EnvironmentSnapshotService } from '../src/python/environmentSnapshot.js';

const fakeOutputChannel: any = {
  info: () => {}, debug: () => {}, warn: () => {}, error: () => {}, trace: () => {},
};

describe('EnvironmentSnapshotService', () => {
  let service: EnvironmentSnapshotService;

  beforeEach(() => {
    service = new EnvironmentSnapshotService(fakeOutputChannel);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('prefers python -m ty when Ty is available in the selected interpreter', async () => {
    vi.spyOn(PythonEnvironmentManager, 'getPythonEnvironment').mockResolvedValue({
      path: '/venv/bin/python',
      pythonPath: '/venv/bin/python',
      version: '3.12',
      env: {},
    });
    vi.spyOn(processRunner, 'runLoggedProcessResult')
      .mockResolvedValueOnce({ ok: true, code: 0, output: 'ty 0.0.1', stdout: 'ty 0.0.1', stderr: '' })
      .mockResolvedValueOnce({ ok: true, code: 0, output: 'ruff 0.15.5', stdout: 'ruff 0.15.5', stderr: '' });

    const snapshot = await service.getSnapshot();

    expect(snapshot.python.available).toBe(true);
    expect(snapshot.python.source).toBe('activeInterpreter');
    expect(snapshot.ty.available).toBe(true);
    expect(snapshot.ty.resolution).toBe('python-module');
    expect(snapshot.ty.command).toBe('/venv/bin/python');
    expect(snapshot.ty.args).toEqual(['-m', 'ty']);
    expect(snapshot.ty.version).toBe('0.0.1');
    expect(snapshot.ruff.available).toBe(true);
    expect(snapshot.ruff.resolution).toBe('python-module');
    expect(snapshot.ruff.command).toBe('/venv/bin/python');
    expect(snapshot.ruff.args).toEqual(['-m', 'ruff']);
    expect(snapshot.ruff.version).toBe('0.15.5');
  });

  it('falls back to a workspace venv when the Python extension interpreter is unavailable', async () => {
    const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'dapper-ty-env-'));
    const venvPath = path.join(tmpRoot, '.venv');
    const pythonPath = process.platform === 'win32'
      ? path.join(venvPath, 'Scripts', 'python.exe')
      : path.join(venvPath, 'bin', 'python');

    fs.mkdirSync(path.dirname(pythonPath), { recursive: true });
    fs.writeFileSync(pythonPath, '');

    vi.spyOn(PythonEnvironmentManager, 'getPythonEnvironment').mockRejectedValue(new Error('No interpreter'));
    vi.spyOn(processRunner, 'runLoggedProcessResult')
      .mockResolvedValueOnce({ ok: false, code: 1, output: 'No module named ty', stdout: '', stderr: 'No module named ty' })
      .mockResolvedValueOnce({ ok: false, code: null, output: '', stdout: '', stderr: '', error: new Error('not found') })
      .mockResolvedValueOnce({ ok: false, code: 1, output: 'No module named ruff', stdout: '', stderr: 'No module named ruff' })
      .mockResolvedValueOnce({ ok: false, code: null, output: '', stdout: '', stderr: '', error: new Error('not found') });

    const snapshot = await service.getSnapshot({ searchRootPath: tmpRoot });

    expect(snapshot.python.available).toBe(true);
    expect(snapshot.python.source).toBe('workspaceVenv');
    expect(snapshot.python.pythonPath).toBe(pythonPath);
    expect(snapshot.ty.available).toBe(false);
    expect(snapshot.ty.resolution).toBe('none');
    expect(snapshot.ruff.available).toBe(false);
    expect(snapshot.ruff.resolution).toBe('none');

    fs.rmSync(tmpRoot, { recursive: true, force: true });
  });

  it('detects Ty and Ruff configuration files from search roots', async () => {
    const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'dapper-ty-config-'));
    fs.writeFileSync(path.join(tmpRoot, 'pyproject.toml'), '[tool.ty]\npython-version = "3.12"\n[tool.ruff]\nline-length = 99\n');
    fs.writeFileSync(path.join(tmpRoot, 'ty.toml'), 'python-version = "3.12"\n');
    fs.writeFileSync(path.join(tmpRoot, 'ruff.toml'), 'line-length = 99\n');

    vi.spyOn(PythonEnvironmentManager, 'getPythonEnvironment').mockRejectedValue(new Error('No interpreter'));
    vi.spyOn(processRunner, 'runLoggedProcessResult')
      .mockResolvedValueOnce({ ok: false, code: null, output: '', stdout: '', stderr: '', error: new Error('not found') })
      .mockResolvedValueOnce({ ok: false, code: null, output: '', stdout: '', stderr: '', error: new Error('not found') });

    const snapshot = await service.getSnapshot({ searchRootPath: tmpRoot });

    expect(snapshot.tyConfig.configured).toBe(true);
    expect(snapshot.tyConfig.files).toEqual(expect.arrayContaining([
      expect.objectContaining({ kind: 'pyproject', hasTySection: true }),
      expect.objectContaining({ kind: 'ty.toml' }),
    ]));
    expect(snapshot.ruffConfig.configured).toBe(true);
    expect(snapshot.ruffConfig.files).toEqual(expect.arrayContaining([
      expect.objectContaining({ kind: 'pyproject', hasRuffSection: true }),
      expect.objectContaining({ kind: 'ruff.toml' }),
    ]));

    fs.rmSync(tmpRoot, { recursive: true, force: true });
  });
});