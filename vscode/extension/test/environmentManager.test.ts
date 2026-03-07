
import { describe, it, expect, beforeEach, vi } from 'vitest';
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

  beforeEach(() => {
    envMgr = new EnvironmentManager(fakeContext, fakeOutputChannel);
    runCalls = [];

    // stub runProcess so we can inspect the arguments passed and avoid spawning real processes
    (envMgr as any).runProcess = async (cmd: string, args: string[], opts: any) => {
      runCalls.push({ cmd, args, opts });
      return Promise.resolve();
    };
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
      vi.restoreAllMocks();
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

      const res = await (envMgr as any).tryWorkspaceVenv('1.2.3', '/wheel', undefined, false);
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

      const res = await (envMgr as any).tryWorkspaceVenv('1.2.3', '/wheel', undefined, true);
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

      const res = await (envMgr as any).tryWorkspaceVenv('1.2.3', '/wheel', undefined, false);
      expect(res).toEqual({ pythonPath: candidate, needsInstall: false });
      expect(runCalls.length).toBe(0);
    });

    it('uses PYTHONPATH injection when dapper not installed', async () => {
      const candidate = path.join(tmpRoot!, '.venv', binDir, pyExe);
      fs.mkdirSync(path.dirname(candidate), { recursive: true });
      fs.writeFileSync(candidate, '');
      (envMgr as any).checkDapperImportable = async () => false;
      (envMgr as any).ensureDapperLib = async () => '/tmp/dapper-lib/1.2.3';

      const res = await (envMgr as any).tryWorkspaceVenv('1.2.3', '/wheel', undefined, false);
      expect(res).toEqual({ pythonPath: candidate, needsInstall: false, dapperLibPath: '/tmp/dapper-lib/1.2.3' });
      expect(runCalls.length).toBe(0);
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
