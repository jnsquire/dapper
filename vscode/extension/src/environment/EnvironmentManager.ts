import * as fs from 'fs';
import * as path from 'path';

import * as vscode from 'vscode';

import {
  checkDapperImportable,
  checkModuleImportable,
  computeWheelHash,
  createVenv,
  ensureDapperLib,
  ensurePip,
  findBundledWheelDir,
  findBundledWheelVersions,
  getDapperVersion,
  installFromPyPI,
  installToTargetDir,
  installWheel,
  manifestPath,
  readManifest,
  type EnvironmentInstallDeps,
  upgradePip,
  writeManifest,
} from './environmentInstall.js';
import {
  createWorkspaceVenvOrAbort as createWorkspaceVenvOrAbortHelper,
  tryPreferredInterpreter as tryPreferredInterpreterHelper,
  tryWorkspaceVenv as tryWorkspaceVenvHelper,
  type EnvironmentSelectionDeps,
} from './environmentSelection.js';
import { getVenvPythonPath, normalizePrepareOptions, resolveBaseInterpreter, resolveWorkspacePython } from './paths.js';
import { runLoggedProcess, runLoggedProcessResult, type ProcessRunResult } from './processRunner.js';
import type { EnvManifest, InstallMode, PrepareEnvironmentOptions, PythonEnvInfo } from './types.js';

export type { EnvManifest, InstallMode, PrepareEnvironmentOptions, PythonEnvInfo } from './types.js';

/**
 * Manages the Python runtime environment for the Dapper extension.
 * Responsible for creating a per-extension venv, installing the bundled or PyPI
 * dapper wheel, and exposing the interpreter path to the adapter factory.
 */
export class EnvironmentManager {
  private readonly output: vscode.LogOutputChannel;
  private preparePromise: Promise<PythonEnvInfo> | undefined;

  constructor(private readonly context: vscode.ExtensionContext, output: vscode.LogOutputChannel) {
    this.output = output;
  }

  /** Main entrypoint to ensure environment is ready. */
  prepareEnvironment(
    desiredVersion: string,
    mode: InstallMode,
    forceReinstall = false,
    options?: vscode.WorkspaceFolder | PrepareEnvironmentOptions,
  ): Promise<PythonEnvInfo> {
    const prepareOptions = this.normalizePrepareOptions(options);
    if (this.preparePromise) {
      return this.preparePromise;
    }

    this.preparePromise = this._prepare(desiredVersion, mode, forceReinstall, prepareOptions)
      .catch(err => {
        this.output.error(`prepareEnvironment failed: ${err instanceof Error ? err.message : String(err)}`);
        throw err;
      })
      .finally(() => {
        this.preparePromise = undefined;
      });
    return this.preparePromise;
  }

  private async _prepare(
    desiredVersion: string,
    mode: InstallMode,
    forceReinstall: boolean,
    options: PrepareEnvironmentOptions,
  ): Promise<PythonEnvInfo> {
    const config = vscode.workspace.getConfiguration('dapper.python');
    const baseInterpreterSetting = config.get<string>('baseInterpreter');
    const expectedVersionSetting = config.get<string>('expectedVersion');
    const effectiveDesiredVersion = this.resolveDesiredVersion(desiredVersion, expectedVersionSetting);
    const workspaceFolder = options.workspaceFolder;

    this.output.info(
      `_prepare: mode=${mode} desiredVersion=${effectiveDesiredVersion} ` +
      `forceReinstall=${forceReinstall} workspaceFolder=${workspaceFolder?.uri.fsPath ?? '(none)'} ` +
      `baseInterpreter=${baseInterpreterSetting || '(default)'} platform=${process.platform} ` +
      `preferredPython=${options.preferredPythonPath || '(none)'} preferredVenv=${options.preferredVenvPath || '(none)'}`
    );

    if (mode === 'workspace') {
      const pythonPath = this.resolveWorkspacePython(
        baseInterpreterSetting,
        options.preferredPythonPath,
        options.preferredVenvPath,
      );
      this.output.info(`Using workspace interpreter: ${pythonPath}`);
      return { pythonPath, needsInstall: false, venvPath: options.preferredVenvPath };
    }

    const wheelDir = this.findBundledWheelDir(effectiveDesiredVersion);

    const preferred = await this.tryPreferredInterpreter(
      effectiveDesiredVersion,
      wheelDir,
      options.preferredPythonPath,
      options.preferredVenvPath,
      forceReinstall,
      options.allowInstallToPreferredInterpreter ?? false,
    );
    if (preferred) {
      return preferred;
    }

    if (mode === 'auto') {
      const wsResult = await this.tryWorkspaceVenv(
        effectiveDesiredVersion,
        wheelDir,
        workspaceFolder,
        options.searchRootPath,
        forceReinstall,
      );
      if (wsResult) {
        return wsResult;
      }

      return this.createWorkspaceVenvOrAbort(
        effectiveDesiredVersion,
        wheelDir,
        workspaceFolder,
        baseInterpreterSetting,
        options.preferredPythonPath,
        options.preferredVenvPath,
        forceReinstall,
      );
    }

    const venvPath = path.join(this.context.globalStorageUri.fsPath, 'python-env');
    const pythonPath = this.getVenvPythonPath(venvPath);
    this.output.info(`Managed venv path: ${venvPath}`);

    const venvExists = fs.existsSync(pythonPath);
    this.output.info(`Venv python exists: ${venvExists} (${pythonPath})`);
    if (!venvExists) {
      const base = this.resolveBaseInterpreter(baseInterpreterSetting);
      this.output.info(`Creating venv at ${venvPath} with base interpreter ${base}`);
      await this.createVenv(base, venvPath);
      this.output.info('Venv created.');
    }

    await this.ensurePip(pythonPath);
    await this.upgradePip(pythonPath);

    const manifest = this.readManifest(venvPath);
    this.output.info(
      `Manifest: ${manifest ? `installed=${manifest.dapperVersionInstalled} source=${manifest.installSource}` : 'none'}` +
      ` | bundled wheels dir: ${wheelDir ?? 'none'}`
    );

    let currentWheelHash: string | undefined;
    if (wheelDir) {
      currentWheelHash = this.computeWheelHash(wheelDir);
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
      if (mode === 'wheel') {
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
        } else {
          throw new Error(`Wheel mode requested but bundled wheels for version ${effectiveDesiredVersion} not found.`);
        }
      }
      if (!performedInstall && mode === 'pypi') {
        this.output.info(`Installing dapper from PyPI: dapper==${effectiveDesiredVersion}`);
        await this.installFromPyPI(pythonPath, effectiveDesiredVersion, true);
        performedInstall = true;
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
          try { fs.unlinkSync(this.manifestPath(venvPath)); } catch { /* ignore */ }
          throw new Error('Stale dapper install detected but no bundled wheel is available. Reload VS Code to retry.');
        }
      }
    }

    const finalManifest = this.readManifest(venvPath);
    return {
      pythonPath,
      venvPath,
      dapperVersionInstalled: finalManifest?.dapperVersionInstalled,
      needsInstall: performedInstall,
    };
  }

  private installDeps(): EnvironmentInstallDeps {
    return {
      context: this.context,
      output: this.output,
      runProcess: this.runProcess.bind(this),
      runProcessResult: this.runProcessResult.bind(this),
    };
  }

  private selectionDeps(): EnvironmentSelectionDeps {
    return {
      output: this.output,
      checkDapperImportable: this.checkDapperImportable.bind(this),
      createVenv: this.createVenv.bind(this),
      ensureDapperLib: this.ensureDapperLib.bind(this),
      ensurePip: this.ensurePip.bind(this),
      getDapperVersion: this.getDapperVersion.bind(this),
      getVenvPythonPath: this.getVenvPythonPath.bind(this),
      installFromPyPI: this.installFromPyPI.bind(this),
      installWheel: this.installWheel.bind(this),
      resolveWorkspacePython: this.resolveWorkspacePython.bind(this),
      upgradePip: this.upgradePip.bind(this),
    };
  }

  private async createWorkspaceVenvOrAbort(
    version: string,
    wheelDir: string | undefined,
    workspaceFolder: vscode.WorkspaceFolder | undefined,
    baseInterpreterSetting: string | undefined,
    preferredPythonPath: string | undefined,
    preferredVenvPath: string | undefined,
    forceReinstall: boolean,
  ): Promise<PythonEnvInfo> {
    return createWorkspaceVenvOrAbortHelper(
      version,
      wheelDir,
      workspaceFolder,
      baseInterpreterSetting,
      preferredPythonPath,
      preferredVenvPath,
      forceReinstall,
      this.selectionDeps(),
    );
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
    searchRootPath?: string,
    forceReinstall = false
  ): Promise<PythonEnvInfo | undefined> {
    return tryWorkspaceVenvHelper(version, wheelDir, workspaceFolder, searchRootPath, forceReinstall, this.selectionDeps());
  }

  private async tryPreferredInterpreter(
    version: string,
    wheelDir: string | undefined,
    preferredPythonPath: string | undefined,
    preferredVenvPath: string | undefined,
    forceReinstall: boolean,
    allowInstallToPreferredInterpreter: boolean,
  ): Promise<PythonEnvInfo | undefined> {
    return tryPreferredInterpreterHelper(
      version,
      wheelDir,
      preferredPythonPath,
      preferredVenvPath,
      forceReinstall,
      allowInstallToPreferredInterpreter,
      this.selectionDeps(),
    );
  }
  private async ensureDapperLib(
    pythonPath: string,
    version: string,
    wheelDir: string,
    forceReinstall: boolean,
  ): Promise<string | undefined> {
    return ensureDapperLib(pythonPath, version, wheelDir, forceReinstall, this.installDeps());
  }

  private async installToTargetDir(
    pythonPath: string,
    wheelDir: string,
    version: string,
    targetDir: string,
  ): Promise<void> {
    await installToTargetDir(pythonPath, wheelDir, version, targetDir, this.installDeps());
  }

  private getVenvPythonPath(venvPath: string): string {
    return getVenvPythonPath(venvPath);
  }

  private resolveBaseInterpreter(setting?: string): string {
    return resolveBaseInterpreter(setting);
  }

  private resolveWorkspacePython(setting?: string, preferredPythonPath?: string, preferredVenvPath?: string): string {
    return resolveWorkspacePython(setting, preferredPythonPath, preferredVenvPath);
  }

  private normalizePrepareOptions(options?: vscode.WorkspaceFolder | PrepareEnvironmentOptions): PrepareEnvironmentOptions {
    return normalizePrepareOptions(options);
  }

  private async createVenv(baseInterpreter: string, venvPath: string): Promise<void> {
    await createVenv(baseInterpreter, venvPath, this.installDeps());
  }

  private async ensurePip(pythonPath: string): Promise<void> {
    await ensurePip(pythonPath, this.installDeps());
  }

  private async upgradePip(pythonPath: string): Promise<void> {
    await upgradePip(pythonPath, this.installDeps());
  }

  private async installWheel(pythonPath: string, wheelDir: string, version: string, force = false): Promise<void> {
    await installWheel(pythonPath, wheelDir, version, force, this.installDeps());
  }

  private async installFromPyPI(pythonPath: string, version: string, force = false): Promise<void> {
    await installFromPyPI(pythonPath, version, force, this.installDeps());
  }

  private async checkDapperImportable(pythonPath: string): Promise<boolean> {
    return checkDapperImportable(pythonPath, this.installDeps());
  }

  private async checkModuleImportable(pythonPath: string, moduleName: string): Promise<boolean> {
    return checkModuleImportable(pythonPath, moduleName, this.installDeps());
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
    return manifestPath(venvPath);
  }

  private readManifest(venvPath: string): EnvManifest | undefined {
    return readManifest(venvPath, this.output);
  }

  private writeManifest(venvPath: string, manifest: EnvManifest): void {
    writeManifest(venvPath, manifest, this.output);
  }

  private findBundledWheelDir(version: string): string | undefined {
    return findBundledWheelDir(this.context.extensionPath, version, this.output);
  }

  private findBundledWheelVersions(): string[] {
    return findBundledWheelVersions(this.context.extensionPath);
  }

  private resolveDesiredVersion(desiredVersion: string, expectedVersionSetting?: string): string {
    if (expectedVersionSetting) {
      return expectedVersionSetting;
    }

    if (this.findBundledWheelDir(desiredVersion)) {
      return desiredVersion;
    }

    const bundledVersions = this.findBundledWheelVersions();
    if (bundledVersions.length === 0) {
      return desiredVersion;
    }

    const bundledVersion = bundledVersions[0];
    if (bundledVersion !== desiredVersion) {
      this.output.warn(
        `No bundled wheel matches requested dapper ${desiredVersion}; using bundled dapper ${bundledVersion} instead. ` +
        'Set dapper.python.expectedVersion to override this fallback.',
      );
    }
    return bundledVersion;
  }

  private computeWheelHash(wheelDir: string): string {
    return computeWheelHash(wheelDir);
  }

  private async getDapperVersion(pythonPath: string): Promise<string | undefined> {
    return getDapperVersion(pythonPath);
  }

  getOutputChannel(): vscode.LogOutputChannel {
    return this.output;
  }

  showOutputChannel(): void {
    this.output.show(true);
  }

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

  private runProcessResult(cmd: string, args: string[], opts: { label: string }): Promise<ProcessRunResult> {
    return runLoggedProcessResult(this.output, cmd, args, opts);
  }

  private runProcess(cmd: string, args: string[], opts: { label: string }): Promise<void> {
    return runLoggedProcess(this.output, cmd, args, opts);
  }
}
