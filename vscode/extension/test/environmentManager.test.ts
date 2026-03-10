
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { EnvironmentManager } from '../src/environment/EnvironmentManager.js';
import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

// Minimal fake context used in tests. We don't actually touch the file system.
const fakeContext: any = {
  globalStorageUri: { fsPath: '/tmp/does-not-exist' }
};

const fakeOutputChannel: any = {
  info: () => {}, debug: () => {}, warn: () => {}, error: () => {}, trace: () => {}
};

describe('EnvironmentManager helpers', () => {
  let envMgr: EnvironmentManager;
  let runCalls: Array<{ cmd: string; args: string[]; opts: any }>;
  let resultCalls: Array<{ cmd: string; args: string[]; opts: any }>;

  beforeEach(() => {
    envMgr = new EnvironmentManager(fakeContext, fakeOutputChannel);
    runCalls = [];
    resultCalls = [];

    (envMgr as any).runProcess = async (cmd: string, args: string[], opts: any) => {
      runCalls.push({ cmd, args, opts });
      return Promise.resolve();
    };

    (envMgr as any).runProcessResult = async (cmd: string, args: string[], opts: any) => {
      resultCalls.push({ cmd, args, opts });
      return { ok: true, code: 0, output: '' };
    };
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('installWheel adds --force-reinstall and --no-cache-dir when forced', async () => {
    await (envMgr as any).installWheel('/python', '/wheel', '1.2.3', true);
    expect(runCalls.length).toBe(1);
    const { args } = runCalls[0];
    expect(args).toContain('--find-links');
    expect(args).toContain('--no-index');
    expect(args).toContain('--no-cache-dir');
    expect(args).toContain('--force-reinstall');
  });

  it('installWheel omits --force-reinstall when not forced', async () => {
    await (envMgr as any).installWheel('/python', '/wheel', '1.2.3', false);
    expect(runCalls.length).toBe(1);
    const { args } = runCalls[0];
    expect(args).toContain('--no-cache-dir');
    expect(args).not.toContain('--force-reinstall');
  });

  it('installFromPyPI respects force flag', async () => {
    await (envMgr as any).installFromPyPI('/python', '4.5.6', true);
    expect(runCalls.length).toBe(1);
    const { args } = runCalls[0];
    expect(args).toContain('--force-reinstall');
  });

  it('installFromPyPI does not add force when false', async () => {
    await (envMgr as any).installFromPyPI('/python', '4.5.6', false);
    expect(runCalls.length).toBe(1);
    const { args } = runCalls[0];
    expect(args).not.toContain('--force-reinstall');
  });

  it('ensurePip runs ensurepip when pip is unavailable', async () => {
    (envMgr as any).runProcessResult = async (cmd: string, args: string[], opts: any) => {
      resultCalls.push({ cmd, args, opts });
      return { ok: false, code: 1, output: 'No module named pip' };
    };

    await (envMgr as any).ensurePip('/python');

    expect(resultCalls).toContainEqual({
      cmd: '/python',
      args: ['-m', 'pip', '--version'],
      opts: { label: 'check pip' },
    });
    expect(runCalls).toContainEqual({
      cmd: '/python',
      args: ['-m', 'ensurepip', '--upgrade'],
      opts: { label: 'ensurepip' },
    });
  });

  it('ensurePip skips ensurepip when pip is already available', async () => {
    await (envMgr as any).ensurePip('/python');

    expect(resultCalls).toContainEqual({
      cmd: '/python',
      args: ['-m', 'pip', '--version'],
      opts: { label: 'check pip' },
    });
    expect(runCalls).toHaveLength(0);
  });

  it('reuses the in-flight prepare promise for concurrent callers', async () => {
    let resolvePrepare: ((value: any) => void) | undefined;
    const prepareResult = new Promise((resolve) => {
      resolvePrepare = resolve;
    });
    const prepareSpy = vi.spyOn(envMgr as any, '_prepare').mockReturnValue(prepareResult);

    const firstCall = envMgr.prepareEnvironment('1.2.3', 'auto', false, undefined);
    const secondCall = envMgr.prepareEnvironment('1.2.3', 'auto', false, undefined);

    expect(firstCall).toBe(secondCall);
    expect(prepareSpy).toHaveBeenCalledTimes(1);

    resolvePrepare?.({ pythonPath: '/python', needsInstall: false });

    await expect(firstCall).resolves.toEqual({ pythonPath: '/python', needsInstall: false });
    await expect(secondCall).resolves.toEqual({ pythonPath: '/python', needsInstall: false });
  });

  it('falls back to the bundled wheel version when the extension version has no matching wheel', async () => {
    vi.spyOn(envMgr as any, 'findBundledWheelDir').mockImplementation((version: unknown) => version === '0.9.1' ? '/wheel' : undefined);
    vi.spyOn(envMgr as any, 'findBundledWheelVersions').mockReturnValue(['0.9.1']);
    const prepareSpy = vi.spyOn(envMgr as any, 'tryPreferredInterpreter').mockResolvedValue({
      pythonPath: '/python',
      needsInstall: false,
    });

    const result = await envMgr.prepareEnvironment('0.9.2', 'auto', false, {
      preferredPythonPath: '/python',
    });

    expect(prepareSpy).toHaveBeenCalledWith('0.9.1', '/wheel', '/python', undefined, false, false);
    expect(result).toEqual({ pythonPath: '/python', needsInstall: false });
  });

  describe('workspace venv handling', () => {
    let tmpRoot: string | undefined;
    const binDir = process.platform === 'win32' ? 'Scripts' : 'bin';
    const pyExe = process.platform === 'win32' ? 'python.exe' : 'python';
    beforeEach(() => {
      // create a temporary folder to act as the workspace root
      tmpRoot = fs.mkdtempSync(path.join(require('os').tmpdir(), 'dapper-test-'));
      (vscode.workspace as any).workspaceFolders = [{ uri: { fsPath: tmpRoot } }];
    });
    afterEach(() => {
      if (tmpRoot) {
        try { fs.rmSync(tmpRoot, { recursive: true, force: true }); } catch { }
      }
    });

    it('uses PYTHONPATH injection when version mismatches (no venv mutation)', async () => {
      // create a fake python executable file inside the workspace venv
      const candidate = path.join(tmpRoot!, '.venv', binDir, pyExe);
      fs.mkdirSync(path.dirname(candidate), { recursive: true });
      fs.writeFileSync(candidate, '');
      // pretend dapper importable with wrong version
      (envMgr as any).checkDapperImportable = async (_: string) => true;
      (envMgr as any).getDapperVersion = async (_: string) => '0.0.1';
      // stub ensureDapperLib to return a fake path instead of extracting
      (envMgr as any).ensureDapperLib = async () => '/tmp/dapper-lib/1.2.3';

      const res = await (envMgr as any).tryWorkspaceVenv('1.2.3', '/wheel', undefined, undefined, false);
      expect(res).toEqual({ pythonPath: candidate, needsInstall: false, dapperLibPath: '/tmp/dapper-lib/1.2.3' });
      // No pip install into the workspace venv should have occurred
      expect(runCalls.length).toBe(0);
    });

    it('uses PYTHONPATH injection when forceReinstall flag provided (no venv mutation)', async () => {
      // choose the second venvDir entry so we exercise a different path
      const candidate = path.join(tmpRoot!, 'venv', binDir, pyExe);
      fs.mkdirSync(path.dirname(candidate), { recursive: true });
      fs.writeFileSync(candidate, '');
      (envMgr as any).checkDapperImportable = async () => true;
      (envMgr as any).getDapperVersion = async () => '1.2.3';
      (envMgr as any).ensureDapperLib = async () => '/tmp/dapper-lib/1.2.3';

      const res = await (envMgr as any).tryWorkspaceVenv('1.2.3', '/wheel', undefined, undefined, true);
      expect(res).toEqual({ pythonPath: candidate, needsInstall: false, dapperLibPath: '/tmp/dapper-lib/1.2.3' });
      // forceReinstall should NOT result in pip install into workspace venv
      expect(runCalls.length).toBe(0);
    });

    it('returns as-is when dapper already installed with matching version', async () => {
      const candidate = path.join(tmpRoot!, '.venv', binDir, pyExe);
      fs.mkdirSync(path.dirname(candidate), { recursive: true });
      fs.writeFileSync(candidate, '');
      (envMgr as any).checkDapperImportable = async () => true;
      (envMgr as any).getDapperVersion = async () => '1.2.3';

      const res = await (envMgr as any).tryWorkspaceVenv('1.2.3', '/wheel', undefined, undefined, false);
      expect(res).toEqual({ pythonPath: candidate, needsInstall: false });
      expect(runCalls.length).toBe(0);
    });

    it('uses PYTHONPATH injection when dapper not installed', async () => {
      const candidate = path.join(tmpRoot!, '.venv', binDir, pyExe);
      fs.mkdirSync(path.dirname(candidate), { recursive: true });
      fs.writeFileSync(candidate, '');
      (envMgr as any).checkDapperImportable = async () => false;
      (envMgr as any).ensureDapperLib = async () => '/tmp/dapper-lib/1.2.3';

      const res = await (envMgr as any).tryWorkspaceVenv('1.2.3', '/wheel', undefined, undefined, false);
      expect(res).toEqual({ pythonPath: candidate, needsInstall: false, dapperLibPath: '/tmp/dapper-lib/1.2.3' });
      expect(runCalls.length).toBe(0);
    });

    it('offers to create a workspace .venv and uses it when accepted', async () => {
      vscode.window.showInformationMessage = vi.fn().mockResolvedValue('Create .venv');
      (envMgr as any).ensureDapperLib = async () => '/tmp/dapper-lib/1.2.3';

      const res = await (envMgr as any).createWorkspaceVenvOrAbort(
        '1.2.3',
        '/wheel',
        { uri: { fsPath: tmpRoot! } },
        undefined,
        '/usr/bin/python3',
        undefined,
        false,
      );

      const candidate = path.join(tmpRoot!, '.venv', binDir, pyExe);
      expect(vscode.window.showInformationMessage).toHaveBeenCalled();
      expect(runCalls).toContainEqual({
        cmd: '/usr/bin/python3',
        args: ['-m', 'venv', path.join(tmpRoot!, '.venv')],
        opts: { label: 'create venv' },
      });
      expect(res).toEqual({
        pythonPath: candidate,
        venvPath: path.join(tmpRoot!, '.venv'),
        needsInstall: false,
        dapperLibPath: '/tmp/dapper-lib/1.2.3',
      });
    });

    it('aborts when the user refuses to create a workspace .venv', async () => {
      vscode.window.showInformationMessage = vi.fn().mockResolvedValue(undefined);

      await expect((envMgr as any).createWorkspaceVenvOrAbort(
        '1.2.3',
        '/wheel',
        { uri: { fsPath: tmpRoot! } },
        undefined,
        '/usr/bin/python3',
        undefined,
        false,
      )).rejects.toThrow('Launch cancelled because Dapper requires a workspace virtual environment for this debug session.');

      expect(runCalls.length).toBe(0);
    });

    it('installs into an explicitly selected interpreter instead of falling back to workspace venv creation', async () => {
      const candidate = path.join(tmpRoot!, '.venv', binDir, pyExe);
      fs.mkdirSync(path.dirname(candidate), { recursive: true });
      fs.writeFileSync(candidate, '');
      (envMgr as any).checkDapperImportable = async () => false;
      const installFromPyPISpy = vi.spyOn(envMgr as any, 'installFromPyPI').mockResolvedValue(undefined);
      const ensurePipSpy = vi.spyOn(envMgr as any, 'ensurePip').mockResolvedValue(undefined);
      const upgradePipSpy = vi.spyOn(envMgr as any, 'upgradePip').mockResolvedValue(undefined);
      const createWorkspaceVenvSpy = vi.spyOn(envMgr as any, 'createWorkspaceVenvOrAbort');
      vi.spyOn(envMgr as any, 'findBundledWheelDir').mockReturnValue(undefined);
      vi.spyOn(envMgr as any, 'findBundledWheelVersions').mockReturnValue([]);

      const res = await envMgr.prepareEnvironment('1.2.3', 'auto', false, {
        workspaceFolder: { uri: { fsPath: tmpRoot! } } as vscode.WorkspaceFolder,
        preferredPythonPath: candidate,
        allowInstallToPreferredInterpreter: true,
      });

      expect(ensurePipSpy).toHaveBeenCalledWith(candidate);
      expect(upgradePipSpy).toHaveBeenCalledWith(candidate);
      expect(installFromPyPISpy).toHaveBeenCalledWith(candidate, '1.2.3', false);
      expect(createWorkspaceVenvSpy).not.toHaveBeenCalled();
      expect(res).toEqual({
        pythonPath: candidate,
        needsInstall: true,
        dapperVersionInstalled: '1.2.3',
        venvPath: undefined,
      });
    });

    it('finds a nested project venv by searching upward from the launch target', async () => {
      const nestedRoot = path.join(tmpRoot!, 'packages', 'agent_debug_workspace');
      const candidate = path.join(nestedRoot, '.venv', binDir, pyExe);
      fs.mkdirSync(path.dirname(candidate), { recursive: true });
      fs.writeFileSync(candidate, '');
      (envMgr as any).checkDapperImportable = async () => false;
      (envMgr as any).ensureDapperLib = async () => '/tmp/dapper-lib/1.2.3';
      vi.spyOn(envMgr as any, 'findBundledWheelDir').mockReturnValue('/wheel');

      const res = await envMgr.prepareEnvironment('1.2.3', 'auto', false, {
        workspaceFolder: { uri: { fsPath: tmpRoot! } } as vscode.WorkspaceFolder,
        searchRootPath: nestedRoot,
      });

      expect(res).toEqual({
        pythonPath: candidate,
        needsInstall: false,
        dapperLibPath: '/tmp/dapper-lib/1.2.3',
      });
    });
  });

  describe('installToTargetDir', () => {
    let tmpDir: string | undefined;
    beforeEach(() => {
      tmpDir = fs.mkdtempSync(path.join(require('os').tmpdir(), 'dapper-target-'));
    });
    afterEach(() => {
      if (tmpDir) {
        try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch { }
      }
    });

    it('uses Python zipfile to extract (no pip)', async () => {
      // Create a fake wheel file so the method can find it
      const wheelDir = path.join(tmpDir!, 'wheels');
      fs.mkdirSync(wheelDir, { recursive: true });
      fs.writeFileSync(path.join(wheelDir, 'dapper-0.9.1-py3-none-any.whl'), '');

      const targetDir = path.join(tmpDir!, 'lib');
      await (envMgr as any).installToTargetDir('/python', wheelDir, '0.9.1', targetDir);
      expect(runCalls.length).toBe(1);
      const { cmd, args } = runCalls[0];
      // Should invoke Python directly, not pip or uv
      expect(cmd).toBe('/python');
      expect(args[0]).toBe('-c');
      expect(args[1]).toContain('zipfile');
      expect(args[2]).toBe(path.join(wheelDir, 'dapper-0.9.1-py3-none-any.whl'));
      expect(args[3]).toBe(targetDir);
    });

    it('throws when no matching wheel is found', async () => {
      const wheelDir = path.join(tmpDir!, 'empty-wheels');
      fs.mkdirSync(wheelDir, { recursive: true });
      const targetDir = path.join(tmpDir!, 'lib');

      await expect((envMgr as any).installToTargetDir('/python', wheelDir, '0.9.1', targetDir))
        .rejects.toThrow('No wheel files matching');
      // No process should have been spawned
      expect(runCalls.length).toBe(0);
    });
  });
});
