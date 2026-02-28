import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { spawn, spawnSync } from 'child_process';

export type InstallMode = 'auto' | 'wheel' | 'pypi' | 'workspace';

export interface EnvManifest {
  dapperVersionInstalled: string;
  installSource: 'wheel' | 'pypi';
  created: string;
  updated: string;
}

export interface PythonEnvInfo {
  pythonPath: string;        // interpreter used for launching adapter
  venvPath?: string;         // present unless workspace mode
  dapperVersionInstalled?: string;
  needsInstall: boolean;     // true if install performed this activation
}

/**
 * Manages the Python runtime environment for the Dapper extension.
 * Responsible for creating a per-extension venv, installing the bundled or PyPI
 * dapper wheel, and exposing the interpreter path to the adapter factory.
 */
export class EnvironmentManager {
  private readonly output: vscode.LogOutputChannel;
  private preparePromise: Promise<PythonEnvInfo> | undefined;
  private readonly lock: { active: boolean } = { active: false }; // simple in-memory guard

  constructor(private readonly context: vscode.ExtensionContext) {
    this.output = vscode.window.createOutputChannel('Dapper Python Env', { log: true });
  }

  /** Main entrypoint to ensure environment is ready. */
  prepareEnvironment(desiredVersion: string, mode: InstallMode, forceReinstall = false, workspaceFolder?: vscode.WorkspaceFolder): Promise<PythonEnvInfo> {
    if (this.preparePromise) {
      return this.preparePromise; // de-duplicate concurrent calls
    }
    if (this.lock.active) {
      // Should be rare because preparePromise also guards; fallback to small delay reattempt
      return new Promise((resolve, reject) => {
        const interval = setInterval(() => {
          if (!this.lock.active && !this.preparePromise) {
            clearInterval(interval);
            this.prepareEnvironment(desiredVersion, mode, forceReinstall, workspaceFolder).then(resolve, reject);
          }
        }, 50);
      });
    }
    this.preparePromise = this._prepare(desiredVersion, mode, forceReinstall, workspaceFolder)
      .catch(err => {
        this.output.error(`prepareEnvironment failed: ${err instanceof Error ? err.message : String(err)}`);
        // Rethrow to let caller handle
        throw err;
      })
      .finally(() => {
        this.preparePromise = undefined; // allow future re-prepares if needed
      });
    return this.preparePromise;
  }

  private async _prepare(desiredVersion: string, mode: InstallMode, forceReinstall: boolean, workspaceFolder?: vscode.WorkspaceFolder): Promise<PythonEnvInfo> {
    this.lock.active = true;
    const config = vscode.workspace.getConfiguration('dapper.python');
    const baseInterpreterSetting = config.get<string>('baseInterpreter');
    const expectedVersionSetting = config.get<string>('expectedVersion');
    const effectiveDesiredVersion = expectedVersionSetting || desiredVersion;

    this.output.info(
      `_prepare: mode=${mode} desiredVersion=${effectiveDesiredVersion} ` +
      `forceReinstall=${forceReinstall} workspaceFolder=${workspaceFolder?.uri.fsPath ?? '(none)'} ` +
      `baseInterpreter=${baseInterpreterSetting || '(default)'} platform=${process.platform}`
    );

    if (mode === 'workspace') {
      const pythonPath = this.resolveWorkspacePython(baseInterpreterSetting);
      this.output.info(`Using workspace interpreter: ${pythonPath}`);
      this.lock.active = false;
      return { pythonPath, needsInstall: false };
    }

    // In auto mode, prefer the workspace's own .venv so the target program runs with its
    // full project environment (e.g. requests, numpy, etc. are available).
    // We install dapper into the workspace venv from bundled wheels if it's not already there.
    if (mode === 'auto' && !forceReinstall) {
      const wheelDir = this.findBundledWheelDir(effectiveDesiredVersion);
      const wsResult = await this.tryWorkspaceVenv(effectiveDesiredVersion, wheelDir, workspaceFolder);
      if (wsResult) {
        this.lock.active = false;
        return wsResult;
      }
      if (!wheelDir) {
        // No bundled wheels and no usable workspace venv — last hope: any interpreter that already
        // has dapper before we try to build a managed venv and hit PyPI.
        this.output.info('auto mode: no bundled wheels found. Probing all interpreters...');
        const earlyFallback = await this.findInterpreterWithDapper(baseInterpreterSetting, workspaceFolder);
        if (earlyFallback) {
          this.output.info(`auto mode: found dapper at ${earlyFallback}, using it.`);
          this.lock.active = false;
          return { pythonPath: earlyFallback, needsInstall: false };
        }
        this.output.info('auto mode: no usable interpreter found; will attempt managed venv + PyPI.');
      }
    }

    const venvPath = path.join(this.context.globalStorageUri.fsPath, 'python-env');
    const pythonPath = this.getVenvPythonPath(venvPath);
    this.output.info(`Managed venv path: ${venvPath}`);

    const venvExists = fs.existsSync(pythonPath);
    this.output.info(`Venv python exists: ${venvExists} (${pythonPath})`);
    if (venvExists) {
      const r = spawnSync(pythonPath, ['--version'], { encoding: 'utf8' });
      const version = (r.stdout || r.stderr || '').trim();
      this.output.info(`Venv Python version: ${version}`);
    }
    if (!venvExists) {
      const base = this.resolveBaseInterpreter(baseInterpreterSetting);
      this.output.info(`Creating venv at ${venvPath} with base interpreter ${base}`);
      await this.createVenv(base, venvPath);
      this.output.info('Venv created.');
    }

    // Ensure pip present & upgraded (best effort)
    await this.ensurePip(pythonPath);
    await this.upgradePip(pythonPath);

    const manifest = this.readManifest(venvPath);
    const wheelDir = this.findBundledWheelDir(effectiveDesiredVersion);
    this.output.info(
      `Manifest: ${manifest ? `installed=${manifest.dapperVersionInstalled} source=${manifest.installSource}` : 'none'}` +
      ` | bundled wheels dir: ${wheelDir ?? 'none'}`
    );
    const reinstallNeeded = this.shouldReinstall(manifest, effectiveDesiredVersion, forceReinstall);
    this.output.info(`Reinstall needed: ${reinstallNeeded}`);

    let performedInstall = false;
    if (reinstallNeeded) {
      if (mode === 'auto' || mode === 'wheel') {
        if (wheelDir) {
          this.output.info(`Installing dapper from bundled wheels in: ${wheelDir}`);
          await this.installWheel(pythonPath, wheelDir, effectiveDesiredVersion);
          if (!await this.checkDapperImportable(pythonPath)) {
            throw new Error(
              `Wheel installed (pip exit 0) but 'import dapper' still fails. ` +
              `The wheel in ${wheelDir} may be incompatible with ${pythonPath}.`
            );
          }
          performedInstall = true;
        } else if (mode === 'wheel') {
          throw new Error(`Wheel mode requested but bundled wheels for version ${effectiveDesiredVersion} not found.`);
        }
      }
      if (!performedInstall && (mode === 'auto' || mode === 'pypi')) {
        this.output.info(`Installing dapper from PyPI: dapper==${effectiveDesiredVersion}`);
        try {
          await this.installFromPyPI(pythonPath, effectiveDesiredVersion);
          performedInstall = true;
        } catch (err) {
          if (mode === 'pypi') {
            throw new Error(`PyPI install failed for dapper==${effectiveDesiredVersion}: ${err}`);
          }
          // Fallback: try wheel dir if it appeared after the early probe
          if (wheelDir) {
            this.output.warn('PyPI install failed, falling back to bundled wheels.');
            await this.installWheel(pythonPath, wheelDir, effectiveDesiredVersion);
            performedInstall = true;
          } else {
            // Last resort: probe again (state may have changed)
            const lastResort = await this.findInterpreterWithDapper(baseInterpreterSetting, workspaceFolder);
            if (lastResort) {
              this.output.warn(
                `PyPI and wheel both failed; using ${lastResort} which already has dapper.`
              );
              this.lock.active = false;
              return { pythonPath: lastResort, needsInstall: false };
            }
            throw new Error('Both PyPI install and wheel fallback failed; cannot proceed.');
          }
        }
      }
      if (performedInstall) {
        const newManifest: EnvManifest = {
          dapperVersionInstalled: effectiveDesiredVersion,
          installSource: wheelDir ? 'wheel' : 'pypi',
          created: manifest?.created || new Date().toISOString(),
          updated: new Date().toISOString(),
        };
        this.writeManifest(venvPath, newManifest);
      }
    } else {
      this.output.info('Reusing existing installation; no reinstall needed.');
      // Sanity-check the key entry point is actually importable. Guards against stale
      // manifest entries where the wheel was updated without bumping the version.
      const entryOk = await this.checkModuleImportable(pythonPath, 'dapper.launcher.__main__');
      if (!entryOk) {
        this.output.warn('dapper.launcher.__main__ not importable — stale install detected. Forcing reinstall...');
        if (wheelDir) {
          await this.installWheel(pythonPath, wheelDir, effectiveDesiredVersion, true);
          if (!await this.checkDapperImportable(pythonPath)) {
            throw new Error(`Forced reinstall completed but 'import dapper' still fails.`);
          }
          performedInstall = true;
        } else {
          // No wheel available — wipe the manifest so next launch triggers a full reinstall
          try { fs.unlinkSync(this.manifestPath(venvPath)); } catch { /* ignore */ }
          throw new Error('Stale dapper install detected but no bundled wheel is available. Reload VS Code to retry.');
        }
      }
    }

    const finalManifest = this.readManifest(venvPath);
    this.lock.active = false;
    return {
      pythonPath,
      venvPath,
      dapperVersionInstalled: finalManifest?.dapperVersionInstalled,
      needsInstall: performedInstall,
    };
  }

  /**
   * Try to use the workspace's own .venv as the adapter interpreter.
   * If dapper is not yet installed there but we have bundled wheels, install it.
   * Returns a PythonEnvInfo if successful, undefined if the workspace has no .venv.
   */
  private async tryWorkspaceVenv(
    version: string,
    wheelDir: string | undefined,
    workspaceFolder?: vscode.WorkspaceFolder
  ): Promise<PythonEnvInfo | undefined> {
    const binDir = process.platform === 'win32' ? 'Scripts' : 'bin';
    const pyExe = process.platform === 'win32' ? 'python.exe' : 'python';
    const venvDirs = ['.venv', 'venv', 'env', '.env'];

    // Collect candidate workspace folders (session folder first)
    const allWsFolders = (vscode.workspace.workspaceFolders ?? []).map(f => f.uri.fsPath);
    const sessionFolder = workspaceFolder?.uri.fsPath;
    const folders = sessionFolder && !allWsFolders.includes(sessionFolder)
      ? [sessionFolder, ...allWsFolders]
      : (sessionFolder ? [sessionFolder, ...allWsFolders.filter(f => f !== sessionFolder)] : allWsFolders);
    this.output.info(`tryWorkspaceVenv: scanning folders [${folders.join(', ')}]`);

    for (const folder of folders) {
      for (const vd of venvDirs) {
        const candidate = path.join(folder, vd, binDir, pyExe);
        this.output.debug(`tryWorkspaceVenv: checking ${candidate}`);
        if (!fs.existsSync(candidate)) continue;

        this.output.info(`auto mode: found workspace venv at ${candidate}`);

        // Check if dapper is already importable
        if (await this.checkDapperImportable(candidate)) {
          this.output.info(`auto mode: dapper already installed in workspace venv, using it.`);
          return { pythonPath: candidate, needsInstall: false };
        }

        // Not installed — try to install from bundled wheels
        if (wheelDir) {
          this.output.info(`auto mode: installing dapper into workspace venv at ${candidate}...`);
          try {
            await this.installWheel(candidate, wheelDir, version);
            if (await this.checkDapperImportable(candidate)) {
              this.output.info(`auto mode: dapper installed into workspace venv successfully.`);
              return { pythonPath: candidate, needsInstall: true };
            }
            this.output.warn(`auto mode: wheel installed but dapper still not importable from ${candidate}; falling back.`);
          } catch (err) {
            this.output.warn(`auto mode: could not install dapper into workspace venv (${err}); falling back.`);
          }
        } else {
          this.output.info(`auto mode: workspace venv found but no bundled wheels to install dapper; falling back to managed venv.`);
        }
        // First venv found is the one to try — don't silently skip to the next
        return undefined;
      }
    }
    return undefined;
  }

  private getVenvPythonPath(venvPath: string): string {
    // Windows vs POSIX layout
    return process.platform === 'win32'
      ? path.join(venvPath, 'Scripts', 'python.exe')
      : path.join(venvPath, 'bin', 'python');
  }

  private resolveBaseInterpreter(setting?: string): string {
    if (setting && fs.existsSync(setting)) {
      return setting;
    }
    // Fallback to 'python' on PATH; caller must handle missing
    // Try common alternative on *nix systems
    if (process.platform !== 'win32') {
      return 'python3';
    }
    return 'python';
  }

  private resolveWorkspacePython(setting?: string): string {
    if (setting && fs.existsSync(setting)) {
      return setting;
    }
    return process.platform !== 'win32' ? 'python3' : 'python'; // Defer failure if not found
  }

  private async createVenv(baseInterpreter: string, venvPath: string): Promise<void> {
    await this.runProcess(baseInterpreter, ['-m', 'venv', venvPath], { label: 'create venv' });
  }

  private async ensurePip(pythonPath: string): Promise<void> {
    try {
      await this.runProcess(pythonPath, ['-m', 'pip', '--version'], { label: 'check pip', allowFail: true });
    } catch {
      this.output.info('pip missing, running ensurepip');
      await this.runProcess(pythonPath, ['-m', 'ensurepip', '--upgrade'], { label: 'ensurepip' });
    }
  }

  private async upgradePip(pythonPath: string): Promise<void> {
    await this.runProcess(pythonPath, ['-m', 'pip', 'install', '--upgrade', 'pip'], { label: 'upgrade pip', allowFail: true });
  }

  private async installWheel(pythonPath: string, wheelDir: string, version: string, force = false): Promise<void> {
    // Let pip select the right platform/ABI-specific wheel from the directory.
    const pipArgs = ['-m', 'pip', 'install', `dapper==${version}`, '--find-links', wheelDir, '--no-index'];
    if (force) pipArgs.push('--force-reinstall');
    const label = `install wheel ${version}${force ? ' (forced)' : ''}`;
    try {
      await this.runProcess(pythonPath, pipArgs, { label });
    } catch (pipErr) {
      const msg = pipErr instanceof Error ? pipErr.message : String(pipErr);
      if (msg.includes('No module named pip')) {
        // uv-managed venvs don't include pip — use uv pip install instead
        this.output.info(`pip not available in venv, trying uv pip install...`);
        const uvArgs = ['pip', 'install', `dapper==${version}`, '--find-links', wheelDir, '--no-index', '--python', pythonPath];
        if (force) uvArgs.push('--reinstall');
        await this.runProcess('uv', uvArgs, { label: `${label} (uv)` });
      } else {
        throw pipErr;
      }
    }
  }

  private async installFromPyPI(pythonPath: string, version: string): Promise<void> {
    await this.runProcess(pythonPath, ['-m', 'pip', 'install', `dapper==${version}`], { label: `install PyPI ${version}` });
  }

  private async checkDapperImportable(pythonPath: string): Promise<boolean> {
    try {
      await this.runProcess(pythonPath, ['-c', 'import dapper'], { label: 'check dapper importable', allowFail: false });
      this.output.debug('  → importable: YES');
      return true;
    } catch {
      this.output.debug('  → importable: NO');
      return false;
    }
  }

  private async checkModuleImportable(pythonPath: string, moduleName: string): Promise<boolean> {
    // Use find_spec so __main__.py is located without being executed.
    const code = `import importlib.util, sys; sys.exit(0 if importlib.util.find_spec(${JSON.stringify(moduleName)}) else 1)`;
    try {
      await this.runProcess(pythonPath, ['-c', code], { label: `check ${moduleName}`, allowFail: false });
      this.output.debug(`  → ${moduleName}: FOUND`);
      return true;
    } catch {
      this.output.debug(`  → ${moduleName}: NOT FOUND`);
      return false;
    }
  }

  /**
   * Probe a prioritised list of interpreter candidates and return the first one
   * that can successfully `import dapper`, or undefined if none can.
   */
  private async findInterpreterWithDapper(
    baseInterpreterSetting: string | undefined,
    workspaceFolder?: vscode.WorkspaceFolder
  ): Promise<string | undefined> {
    const candidates: string[] = [];

    this.output.info(
      `findInterpreterWithDapper: sessionFolder=${workspaceFolder?.uri.fsPath ?? '(none)'} ` +
      `vscodeWorkspaceFolders=[${(vscode.workspace.workspaceFolders ?? []).map(f => f.uri.fsPath).join(', ')}]`
    );

    // 1. Active interpreter from the ms-python extension (highest priority)
    try {
      const pyExt = vscode.extensions.getExtension('ms-python.python');
      if (pyExt) {
        if (!pyExt.isActive) {
          this.output.debug('Activating ms-python extension...');
          await pyExt.activate();
        }
        const api = pyExt.exports;
        // ms-python v2022+ exposes environments.getActiveEnvironmentPath
        const envPath = api?.environments?.getActiveEnvironmentPath?.(workspaceFolder?.uri);
        const resolved = typeof envPath?.path === 'string' ? envPath.path
          : typeof envPath === 'string' ? envPath : undefined;
        this.output.debug(`ms-python getActiveEnvironmentPath returned: ${JSON.stringify(envPath)}`);
        if (resolved) {
          const exists = fs.existsSync(resolved);
          this.output.debug(`ms-python resolved path: ${resolved} (exists on disk: ${exists})`);
          if (exists) {
            candidates.push(resolved);
          }
        } else {
          this.output.debug('ms-python did not return a resolvable interpreter path.');
        }
      } else {
        this.output.debug('ms-python extension (ms-python.python) is not installed.');
      }
    } catch (e) {
      this.output.debug(`Could not query ms-python extension: ${e}`);
    }

    // 2. Workspace folder venvs (common patterns: .venv, venv, env).
    // Always check ALL open VS Code workspace folders, plus the session folder if different.
    const allWsFolders = (vscode.workspace.workspaceFolders ?? []).map(f => f.uri.fsPath);
    const sessionFolder = workspaceFolder?.uri.fsPath;
    const folders = sessionFolder && !allWsFolders.includes(sessionFolder)
      ? [sessionFolder, ...allWsFolders]
      : allWsFolders;
    const venvDirs = ['.venv', 'venv', 'env', '.env'];
    const binDir = process.platform === 'win32' ? 'Scripts' : 'bin';
    const pyExe = process.platform === 'win32' ? 'python.exe' : 'python';
    this.output.debug(`Scanning ${folders.length} folder(s) for local venvs: [${folders.join(', ')}]`);
    for (const folder of folders) {
      for (const vd of venvDirs) {
        const candidate = path.join(folder, vd, binDir, pyExe);
        const exists = fs.existsSync(candidate);
        this.output.debug(`  ${candidate} — ${exists ? 'FOUND' : 'not found'}`);
        if (exists) {
          candidates.push(candidate);
        }
      }
    }

    // 3. Explicit base interpreter setting / system PATH fallback
    candidates.push(this.resolveBaseInterpreter(baseInterpreterSetting));
    // Also try python3/python directly from PATH (covers active shell venvs)
    if (process.platform !== 'win32') {
      candidates.push('python3', 'python');
    } else {
      candidates.push('python');
    }

    // Deduplicate and probe
    const seen = new Set<string>();
    this.output.info(`Probing ${candidates.length} candidate interpreter(s)...`);
    for (const candidate of candidates) {
      if (seen.has(candidate)) continue;
      seen.add(candidate);
      this.output.debug(`Probing: ${candidate}`);
      if (await this.checkDapperImportable(candidate)) {
        this.output.info(`Found working interpreter: ${candidate}`);
        return candidate;
      }
    }
    this.output.warn('No candidate interpreter could import dapper.');
    return undefined;
  }

  private shouldReinstall(manifest: EnvManifest | undefined, desiredVersion: string, force: boolean): boolean {
    if (force) return true;
    if (!manifest) return true;
    return manifest.dapperVersionInstalled !== desiredVersion;
  }

  private manifestPath(venvPath: string): string {
    return path.join(venvPath, 'dapper-env.json');
  }

  private readManifest(venvPath: string): EnvManifest | undefined {
    const mp = this.manifestPath(venvPath);
    if (!fs.existsSync(mp)) return undefined;
    try {
      return JSON.parse(fs.readFileSync(mp, 'utf8')) as EnvManifest;
    } catch (err) {
      this.output.warn(`Failed to read manifest: ${err}`);
      return undefined;
    }
  }

  private writeManifest(venvPath: string, manifest: EnvManifest): void {
    try {
      fs.writeFileSync(this.manifestPath(venvPath), JSON.stringify(manifest, null, 2), 'utf8');
    } catch (err) {
      this.output.warn(`Failed to write manifest: ${err}`);
    }
  }

  private findBundledWheelDir(version: string): string | undefined {
    const wheelDir = path.join(this.context.extensionPath, 'resources', 'python-wheels');
    if (!fs.existsSync(wheelDir)) return undefined;
    const files = fs.readdirSync(wheelDir).filter(f => f.startsWith(`dapper-${version}`) && f.endsWith('.whl'));
    if (files.length === 0) return undefined;
    this.output.debug(`findBundledWheelDir: found ${files.length} wheel(s) for v${version}: ${files.join(', ')}`);
    return wheelDir;
  }

  /** Expose output channel for other components (e.g., descriptor factory) */
  getOutputChannel(): vscode.LogOutputChannel {
    return this.output;
  }

  /** Reveal the output channel in the UI. */
  showOutputChannel(): void {
    this.output.show(true /* preserveFocus */);
  }

  /** Reset environment (delete venv) so next prepare triggers full rebuild */
  async resetEnvironment(): Promise<void> {
    const venvPath = path.join(this.context.globalStorageUri.fsPath, 'python-env');
    try {
      if (fs.existsSync(venvPath)) {
        this.output.info(`Removing venv at ${venvPath}`);
        await fs.promises.rm(venvPath, { recursive: true, force: true });
      }
    } catch (err) {
      this.output.warn(`Failed to remove venv: ${err}`);
    }
  }

  private runProcess(cmd: string, args: string[], opts: { label: string; allowFail?: boolean }): Promise<void> {
    return new Promise((resolve, reject) => {
      this.output.debug(`[run] ${opts.label}: ${cmd} ${args.join(' ')}`);
      const child = spawn(cmd, args, { shell: process.platform === 'win32' });
      const outputLines: string[] = [];
      const onData = (d: Buffer) => {
        const text = d.toString().trimEnd();
        this.output.trace(text);
        outputLines.push(text);
      };
      child.stdout.on('data', onData);
      child.stderr.on('data', onData);
      child.on('error', err => {
        if (opts.allowFail) {
          this.output.warn(`${opts.label} failed (allowFail): ${err.message}`);
          resolve();
        } else {
          reject(err);
        }
      });
      child.on('close', code => {
        if (code === 0 || opts.allowFail) {
          resolve();
        } else {
          const tail = outputLines.slice(-20).join('\n');
          reject(new Error(`${opts.label} exited with code ${code}:\n${tail}`));
        }
      });
    });
  }
}
