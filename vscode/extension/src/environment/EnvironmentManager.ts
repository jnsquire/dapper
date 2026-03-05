import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { spawn, spawnSync } from 'child_process';

export type InstallMode = 'auto' | 'wheel' | 'pypi' | 'workspace';

export interface EnvManifest {
  dapperVersionInstalled: string;
  installSource: 'wheel' | 'pypi';
  // SHA256 of the bundle wheel directory contents; used to detect rebuilds
  wheelHash?: string;
  created: string;
  updated: string;
}

export interface PythonEnvInfo {
  pythonPath: string;        // interpreter used for launching adapter
  venvPath?: string;         // present unless workspace mode
  dapperVersionInstalled?: string;
  needsInstall: boolean;     // true if install performed this activation
  /** When set, this directory must be prepended to PYTHONPATH so that
   *  `import dapper` resolves without dapper being installed into the
   *  interpreter's own site-packages. */
  dapperLibPath?: string;
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

  constructor(private readonly context: vscode.ExtensionContext, output: vscode.LogOutputChannel) {
    this.output = output;
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
    // Dapper is made available via PYTHONPATH injection — the workspace venv is never modified.
    if (mode === 'auto') {
      const wheelDir = this.findBundledWheelDir(effectiveDesiredVersion);
      const wsResult = await this.tryWorkspaceVenv(effectiveDesiredVersion, wheelDir, workspaceFolder, forceReinstall);
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
    
    let currentWheelHash: string | undefined;
    if (wheelDir) {
      currentWheelHash = await this.computeWheelHash(wheelDir);
      this.output.info(`Current wheel hash: ${currentWheelHash}`);
    }
    const reinstallNeeded = this.shouldReinstall(
      manifest,
      effectiveDesiredVersion,
      forceReinstall,
      currentWheelHash,
    );
    this.output.info(`Reinstall needed: ${reinstallNeeded}`);

    let performedInstall = false;
    if (reinstallNeeded) {
      if (mode === 'auto' || mode === 'wheel') {
        if (wheelDir) {
          this.output.info(`Installing dapper from bundled wheels in: ${wheelDir}`);
          await this.installWheel(pythonPath, wheelDir, effectiveDesiredVersion, true);
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
          await this.installFromPyPI(pythonPath, effectiveDesiredVersion, true);
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
          wheelHash: currentWheelHash,
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
   *
   * **Important**: this method never installs dapper into the workspace venv.
   * If the correct version is already present (e.g. the user installed it) we
   * use it directly; otherwise we extract the bundled wheel to an
   * extension-managed directory and return a `dapperLibPath` that the caller
   * must inject via PYTHONPATH.
   */
  private async tryWorkspaceVenv(
    version: string,
    wheelDir: string | undefined,
    workspaceFolder?: vscode.WorkspaceFolder,
    forceReinstall = false
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

        // If the workspace venv already has the right version of dapper and
        // we are not forcing a reinstall, use it directly — no mutation needed.
        if (!forceReinstall && await this.checkDapperImportable(candidate)) {
          const installedVersion = await this.getDapperVersion(candidate);
          if (installedVersion === version) {
            this.output.info(`auto mode: dapper already installed in workspace venv (version ${installedVersion}), using it.`);
            return { pythonPath: candidate, needsInstall: false };
          }
          this.output.info(
            `auto mode: workspace venv has dapper ${installedVersion} but need ${version}; ` +
            'will use PYTHONPATH injection instead of modifying the venv.'
          );
        }

        // Either dapper is missing from the venv, the version is wrong, or a
        // force-reinstall was requested.  Instead of touching the workspace
        // venv, extract dapper to an extension-managed directory.
        if (wheelDir) {
          const libPath = await this.ensureDapperLib(candidate, version, wheelDir, forceReinstall);
          if (libPath) {
            this.output.info(`auto mode: dapper ${version} available via PYTHONPATH at ${libPath}`);
            return { pythonPath: candidate, needsInstall: false, dapperLibPath: libPath };
          }
          this.output.warn('auto mode: failed to extract dapper for PYTHONPATH injection; falling back.');
        } else {
          this.output.info('auto mode: workspace venv found but no bundled wheels for PYTHONPATH injection; falling back to managed venv.');
        }
        // First venv found is the one to try — don't silently skip to the next
        return undefined;
      }
    }
    return undefined;
  }

  // ---------------------------------------------------------------------------
  // PYTHONPATH-based dapper injection (avoids installing into workspace venvs)
  // ---------------------------------------------------------------------------

  /**
   * Ensure the dapper package is available in an isolated, extension-managed
   * directory suitable for PYTHONPATH injection.  Uses `pip install --target`
   * (or `uv pip install --target`) to extract the correct platform-specific
   * wheel without modifying any venv.
   *
   * Returns the target directory path, or `undefined` on failure.
   */
  private async ensureDapperLib(
    pythonPath: string,
    version: string,
    wheelDir: string,
    forceReinstall: boolean,
  ): Promise<string | undefined> {
    const libBase = path.join(this.context.globalStorageUri.fsPath, 'dapper-lib');
    const targetDir = path.join(libBase, version);
    const manifestPath = path.join(libBase, 'dapper-lib.json');

    // Read existing manifest
    let manifest: { version: string; wheelHash?: string } | undefined;
    try {
      if (fs.existsSync(manifestPath)) {
        manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
      }
    } catch { /* ignore corrupt manifest */ }

    const currentWheelHash = await this.computeWheelHash(wheelDir);

    const extractNeeded = forceReinstall
      || !manifest
      || manifest.version !== version
      || (currentWheelHash && manifest.wheelHash !== currentWheelHash)
      || !fs.existsSync(path.join(targetDir, 'dapper', '__init__.py'));

    if (!extractNeeded) {
      this.output.info(`dapper lib already extracted at ${targetDir}; reusing.`);
      return targetDir;
    }

    this.output.info(`Extracting dapper ${version} to ${targetDir} for PYTHONPATH injection...`);

    // Clean up any previous extraction so we start fresh
    if (fs.existsSync(targetDir)) {
      await fs.promises.rm(targetDir, { recursive: true, force: true });
    }

    try {
      await this.installToTargetDir(pythonPath, wheelDir, version, targetDir);

      // Verify the extraction produced a usable package tree
      if (!fs.existsSync(path.join(targetDir, 'dapper', '__init__.py'))) {
        this.output.error('Extraction succeeded but dapper/__init__.py not found in target dir');
        return undefined;
      }

      // Persist manifest so subsequent launches skip re-extraction
      const newManifest = { version, wheelHash: currentWheelHash };
      fs.mkdirSync(libBase, { recursive: true });
      fs.writeFileSync(manifestPath, JSON.stringify(newManifest, null, 2), 'utf8');

      this.output.info(`dapper ${version} extracted successfully to ${targetDir}`);
      return targetDir;
    } catch (err) {
      this.output.error(`Failed to extract dapper to target dir: ${err}`);
      return undefined;
    }
  }

  /**
   * Extract the dapper wheel into an isolated target directory using only
   * Python's stdlib `zipfile` module.  This avoids any dependency on pip,
   * uv, or any other package manager.
   *
   * A `.whl` file is a standard zip archive whose top-level entries are the
   * package directory (e.g. `dapper/`) and a `*.dist-info/` metadata
   * directory.  Extracting the zip into `targetDir` produces exactly the
   * layout needed for PYTHONPATH-based imports.
   */
  private async installToTargetDir(
    pythonPath: string,
    wheelDir: string,
    version: string,
    targetDir: string,
  ): Promise<void> {
    fs.mkdirSync(targetDir, { recursive: true });

    // Locate the wheel file — there may be several platform-specific wheels;
    // prefer the most specific one but fall back to a universal wheel.
    const allWheels = fs.readdirSync(wheelDir)
      .filter(f => f.startsWith(`dapper-${version}`) && f.endsWith('.whl'))
      .sort();
    if (allWheels.length === 0) {
      throw new Error(`No wheel files matching dapper-${version}*.whl found in ${wheelDir}`);
    }
    const wheelFile = path.join(wheelDir, allWheels[0]);
    this.output.info(`Extracting wheel ${allWheels[0]} → ${targetDir}`);

    // Use Python's zipfile stdlib module to extract — available everywhere.
    const extractScript = [
      'import sys, zipfile, os',
      `whl = sys.argv[1]`,
      `dst = sys.argv[2]`,
      'os.makedirs(dst, exist_ok=True)',
      'with zipfile.ZipFile(whl) as zf:',
      '    zf.extractall(dst)',
    ].join('\n');

    await this.runProcess(
      pythonPath,
      ['-c', extractScript, wheelFile, targetDir],
      { label: `extract wheel dapper ${version}` },
    );
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
    const pipArgs = ['-m', 'pip', 'install', `dapper==${version}`, '--find-links', wheelDir, '--no-index', '--no-cache-dir'];
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

  private async installFromPyPI(pythonPath: string, version: string, force = false): Promise<void> {
    const args = ['-m', 'pip', 'install', `dapper==${version}`];
    if (force) {
      args.push('--force-reinstall');
    }
    await this.runProcess(pythonPath, args, { label: `install PyPI ${version}${force ? ' (forced)' : ''}` });
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

  private shouldReinstall(
    manifest: EnvManifest | undefined,
    desiredVersion: string,
    force: boolean,
    wheelHash?: string,
  ): boolean {
    if (force) {
      return true;
    }
    if (!manifest) {
      return true;
    }
    if (manifest.dapperVersionInstalled !== desiredVersion) {
      return true;
    }
    if (wheelHash && manifest.wheelHash !== wheelHash) {
      // rebuild of the same version; force reinstall so the venv reflects
      // the freshly built wheel.
      this.output.info('Wheel hash changed; reinstall required');
      return true;
    }
    return false;
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

  private async computeWheelHash(wheelDir: string): Promise<string> {
    // compute SHA256 of concatenated wheel filenames and contents
    const hash = await new Promise<string>((resolve, reject) => {
      const crypto = require('crypto');
      const h = crypto.createHash('sha256');
      fs.readdirSync(wheelDir)
        .filter(f => f.endsWith('.whl'))
        .sort()
        .forEach(fn => {
          const p = path.join(wheelDir, fn);
          h.update(fn);
          const data = fs.readFileSync(p);
          h.update(data);
        });
      resolve(h.digest('hex'));
    });
    return hash;
  }

  /** Return the installed dapper.__version__ from the given interpreter, or undefined if import fails. */
  private async getDapperVersion(pythonPath: string): Promise<string | undefined> {
    // spawnSync is used for simplicity since we just need the stdout result.
    try {
      const r = spawnSync(pythonPath, ['-c', 'import dapper; print(dapper.__version__)'], { encoding: 'utf8' });
      if (r.status === 0) {
        return (r.stdout || '').trim();
      }
    } catch {
      // ignore
    }
    return undefined;
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
