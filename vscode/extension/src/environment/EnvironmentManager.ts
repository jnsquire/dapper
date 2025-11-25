import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { spawn } from 'child_process';

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
  private readonly output: vscode.OutputChannel;
  private preparePromise: Promise<PythonEnvInfo> | undefined;
  private readonly lock: { active: boolean } = { active: false }; // simple in-memory guard

  constructor(private readonly context: vscode.ExtensionContext) {
    this.output = vscode.window.createOutputChannel('Dapper Python Env');
  }

  /** Main entrypoint to ensure environment is ready. */
  prepareEnvironment(desiredVersion: string, mode: InstallMode, forceReinstall = false): Promise<PythonEnvInfo> {
    if (this.preparePromise) {
      return this.preparePromise; // de-duplicate concurrent calls
    }
    if (this.lock.active) {
      // Should be rare because preparePromise also guards; fallback to small delay reattempt
      return new Promise((resolve, reject) => {
        const interval = setInterval(() => {
          if (!this.lock.active && !this.preparePromise) {
            clearInterval(interval);
            this.prepareEnvironment(desiredVersion, mode, forceReinstall).then(resolve, reject);
          }
        }, 50);
      });
    }
    this.preparePromise = this._prepare(desiredVersion, mode, forceReinstall)
      .catch(err => {
        this.output.appendLine(`[ERROR] prepareEnvironment failed: ${err instanceof Error ? err.message : String(err)}`);
        // Rethrow to let caller handle
        throw err;
      })
      .finally(() => {
        this.preparePromise = undefined; // allow future re-prepares if needed
      });
    return this.preparePromise;
  }

  private async _prepare(desiredVersion: string, mode: InstallMode, forceReinstall: boolean): Promise<PythonEnvInfo> {
    this.lock.active = true;
    const config = vscode.workspace.getConfiguration('dapper.python');
    const baseInterpreterSetting = config.get<string>('baseInterpreter');
    const expectedVersionSetting = config.get<string>('expectedVersion');
    const effectiveDesiredVersion = expectedVersionSetting || desiredVersion;

    if (mode === 'workspace') {
      const pythonPath = this.resolveWorkspacePython(baseInterpreterSetting);
      this.output.appendLine(`[INFO] Using workspace interpreter: ${pythonPath}`);
      return { pythonPath, needsInstall: false };
    }

    const venvPath = path.join(this.context.globalStorageUri.fsPath, 'python-env');
    const pythonPath = this.getVenvPythonPath(venvPath);

    const venvExists = fs.existsSync(pythonPath);
    if (!venvExists) {
      const base = this.resolveBaseInterpreter(baseInterpreterSetting);
      this.output.appendLine(`[INFO] Creating venv at ${venvPath} with base interpreter ${base}`);
      await this.createVenv(base, venvPath);
    }

    // Ensure pip present & upgraded (best effort)
    await this.ensurePip(pythonPath);
    await this.upgradePip(pythonPath);

    const manifest = this.readManifest(venvPath);
    const wheelPath = this.findBundledWheel(effectiveDesiredVersion);
    const reinstallNeeded = this.shouldReinstall(manifest, effectiveDesiredVersion, forceReinstall);

    let performedInstall = false;
    if (reinstallNeeded) {
      if (mode === 'auto' || mode === 'wheel') {
        if (wheelPath) {
          this.output.appendLine(`[INFO] Installing dapper from bundled wheel: ${path.basename(wheelPath)}`);
          await this.installWheel(pythonPath, wheelPath, effectiveDesiredVersion);
          performedInstall = true;
        } else if (mode === 'wheel') {
          throw new Error(`Wheel mode requested but bundled wheel for version ${effectiveDesiredVersion} not found.`);
        }
      }
      if (!performedInstall && (mode === 'auto' || mode === 'pypi')) {
        this.output.appendLine(`[INFO] Installing dapper from PyPI: dapper==${effectiveDesiredVersion}`);
        try {
          await this.installFromPyPI(pythonPath, effectiveDesiredVersion);
          performedInstall = true;
        } catch (err) {
          if (mode === 'pypi') {
            throw new Error(`PyPI install failed for dapper==${effectiveDesiredVersion}: ${err}`);
          }
          // Fallback attempt: try wheel again if exists
          if (wheelPath) {
            this.output.appendLine('[WARN] PyPI install failed, falling back to bundled wheel.');
            await this.installWheel(pythonPath, wheelPath, effectiveDesiredVersion);
            performedInstall = true;
          } else {
            throw new Error('Both PyPI install and wheel fallback failed; cannot proceed.');
          }
        }
      }
      if (performedInstall) {
        const newManifest: EnvManifest = {
          dapperVersionInstalled: effectiveDesiredVersion,
          installSource: wheelPath && performedInstall && fs.existsSync(wheelPath) ? 'wheel' : 'pypi',
          created: manifest?.created || new Date().toISOString(),
          updated: new Date().toISOString(),
        };
        this.writeManifest(venvPath, newManifest);
      }
    } else {
      this.output.appendLine('[INFO] Reusing existing installation; no reinstall needed.');
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
      this.output.appendLine('[INFO] pip missing, running ensurepip');
      await this.runProcess(pythonPath, ['-m', 'ensurepip', '--upgrade'], { label: 'ensurepip' });
    }
  }

  private async upgradePip(pythonPath: string): Promise<void> {
    await this.runProcess(pythonPath, ['-m', 'pip', 'install', '--upgrade', 'pip'], { label: 'upgrade pip', allowFail: true });
  }

  private async installWheel(pythonPath: string, wheelPath: string, version: string): Promise<void> {
    await this.runProcess(pythonPath, ['-m', 'pip', 'install', wheelPath], { label: `install wheel ${version}` });
  }

  private async installFromPyPI(pythonPath: string, version: string): Promise<void> {
    await this.runProcess(pythonPath, ['-m', 'pip', 'install', `dapper==${version}`], { label: `install PyPI ${version}` });
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
      this.output.appendLine(`[WARN] Failed to read manifest: ${err}`);
      return undefined;
    }
  }

  private writeManifest(venvPath: string, manifest: EnvManifest): void {
    try {
      fs.writeFileSync(this.manifestPath(venvPath), JSON.stringify(manifest, null, 2), 'utf8');
    } catch (err) {
      this.output.appendLine(`[WARN] Failed to write manifest: ${err}`);
    }
  }

  private findBundledWheel(version: string): string | undefined {
    const wheelDir = path.join(this.context.extensionPath, 'resources', 'python-wheels');
    if (!fs.existsSync(wheelDir)) return undefined;
    const files = fs.readdirSync(wheelDir).filter(f => f.startsWith('dapper-') && f.endsWith('.whl'));
    // Prefer exact version match
    const exact = files.find(f => f.includes(`-${version}-`));
    const chosen = exact || files[0];
    return chosen ? path.join(wheelDir, chosen) : undefined;
  }

  /** Expose output channel for other components (e.g., descriptor factory) */
  getOutputChannel(): vscode.OutputChannel {
    return this.output;
  }

  /** Reset environment (delete venv) so next prepare triggers full rebuild */
  async resetEnvironment(): Promise<void> {
    const venvPath = path.join(this.context.globalStorageUri.fsPath, 'python-env');
    try {
      if (fs.existsSync(venvPath)) {
        this.output.appendLine(`[INFO] Removing venv at ${venvPath}`);
        await fs.promises.rm(venvPath, { recursive: true, force: true });
      }
    } catch (err) {
      this.output.appendLine(`[WARN] Failed to remove venv: ${err}`);
    }
  }

  private runProcess(cmd: string, args: string[], opts: { label: string; allowFail?: boolean }): Promise<void> {
    return new Promise((resolve, reject) => {
      this.output.appendLine(`[RUN] ${opts.label}: ${cmd} ${args.join(' ')}`);
      const child = spawn(cmd, args, { shell: process.platform === 'win32' });
      child.stdout.on('data', d => this.output.appendLine(d.toString()));
      child.stderr.on('data', d => this.output.appendLine(d.toString()));
      child.on('error', err => {
        if (opts.allowFail) {
          this.output.appendLine(`[WARN] ${opts.label} failed (allowFail): ${err.message}`);
          resolve();
        } else {
          reject(err);
        }
      });
      child.on('close', code => {
        if (code === 0 || opts.allowFail) {
          resolve();
        } else {
          reject(new Error(`${opts.label} exited with code ${code}`));
        }
      });
    });
  }
}
