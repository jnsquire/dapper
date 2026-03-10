import { spawnSync } from 'child_process';
import { createHash } from 'crypto';
import * as fs from 'fs';
import * as path from 'path';

import * as vscode from 'vscode';

import type { ProcessRunOptions, ProcessRunResult } from './processRunner.js';
import type { EnvManifest } from './types.js';

export interface EnvironmentInstallDeps {
  context: vscode.ExtensionContext;
  output: vscode.LogOutputChannel;
  runProcess(cmd: string, args: string[], opts: ProcessRunOptions): Promise<void>;
  runProcessResult(cmd: string, args: string[], opts: ProcessRunOptions): Promise<ProcessRunResult>;
}

interface DapperLibManifest {
  version: string;
  wheelHash?: string;
}

export async function createVenv(
  baseInterpreter: string,
  venvPath: string,
  deps: EnvironmentInstallDeps,
): Promise<void> {
  try {
    await deps.runProcess(baseInterpreter, ['-m', 'venv', venvPath], { label: 'create venv' });
  } catch (err) {
    // On Windows the user may not have `python` on PATH but have the `py`
    // launcher available. If creation with the resolved interpreter fails,
    // attempt to create the venv with `py -3` as a fallback before bailing.
    if (process.platform === 'win32') {
      deps.output.info('create venv failed with resolved interpreter; trying Windows `py -3` fallback');
      try {
        await deps.runProcess('py', ['-3', '-m', 'venv', venvPath], { label: 'create venv (py -3)' });
        return;
      } catch (err2) {
        deps.output.warn('Fallback `py -3` venv creation also failed');
      }
    }
    throw err;
  }
}

export async function ensurePip(pythonPath: string, deps: EnvironmentInstallDeps): Promise<void> {
  const result = await deps.runProcessResult(pythonPath, ['-m', 'pip', '--version'], { label: 'check pip' });
  if (result.ok) {
    return;
  }
  deps.output.info('pip missing, running ensurepip');
  await deps.runProcess(pythonPath, ['-m', 'ensurepip', '--upgrade'], { label: 'ensurepip' });
}

export async function upgradePip(pythonPath: string, deps: EnvironmentInstallDeps): Promise<void> {
  const result = await deps.runProcessResult(
    pythonPath,
    ['-m', 'pip', 'install', '--upgrade', 'pip'],
    { label: 'upgrade pip' },
  );
  if (!result.ok) {
    deps.output.warn(`upgrade pip failed${result.output ? `: ${result.output}` : ''}`);
  }
}

export async function installWheel(
  pythonPath: string,
  wheelDir: string,
  version: string,
  force: boolean,
  deps: EnvironmentInstallDeps,
): Promise<void> {
  const pipArgs = ['-m', 'pip', 'install', `dapper==${version}`, '--find-links', wheelDir, '--no-index', '--no-cache-dir'];
  if (force) {
    pipArgs.push('--force-reinstall');
  }
  const label = `install wheel ${version}${force ? ' (forced)' : ''}`;
  try {
    await deps.runProcess(pythonPath, pipArgs, { label });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (!message.includes('No module named pip')) {
      throw error;
    }

    deps.output.info('pip not available in venv, trying uv pip install...');
    const uvArgs = ['pip', 'install', `dapper==${version}`, '--find-links', wheelDir, '--no-index', '--python', pythonPath];
    if (force) {
      uvArgs.push('--reinstall');
    }
    await deps.runProcess('uv', uvArgs, { label: `${label} (uv)` });
  }
}

export async function installFromPyPI(
  pythonPath: string,
  version: string,
  force: boolean,
  deps: EnvironmentInstallDeps,
): Promise<void> {
  const args = ['-m', 'pip', 'install', `dapper==${version}`];
  if (force) {
    args.push('--force-reinstall');
  }
  await deps.runProcess(pythonPath, args, { label: `install PyPI ${version}${force ? ' (forced)' : ''}` });
}

export async function checkDapperImportable(
  pythonPath: string,
  deps: EnvironmentInstallDeps,
): Promise<boolean> {
  const result = await deps.runProcessResult(pythonPath, ['-c', 'import dapper'], { label: 'check dapper importable' });
  deps.output.debug(`  → importable: ${result.ok ? 'YES' : 'NO'}`);
  return result.ok;
}

export async function checkModuleImportable(
  pythonPath: string,
  moduleName: string,
  deps: EnvironmentInstallDeps,
): Promise<boolean> {
  const code = `import importlib.util, sys; sys.exit(0 if importlib.util.find_spec(${JSON.stringify(moduleName)}) else 1)`;
  const result = await deps.runProcessResult(pythonPath, ['-c', code], { label: `check ${moduleName}` });
  deps.output.debug(`  → ${moduleName}: ${result.ok ? 'FOUND' : 'NOT FOUND'}`);
  return result.ok;
}

export async function ensureDapperLib(
  pythonPath: string,
  version: string,
  wheelDir: string,
  forceReinstall: boolean,
  deps: EnvironmentInstallDeps,
): Promise<string | undefined> {
  const libBase = path.join(deps.context.globalStorageUri.fsPath, 'dapper-lib');
  const targetDir = path.join(libBase, version);
  const manifestFile = path.join(libBase, 'dapper-lib.json');

  let manifest: DapperLibManifest | undefined;
  try {
    if (fs.existsSync(manifestFile)) {
      manifest = JSON.parse(fs.readFileSync(manifestFile, 'utf8')) as DapperLibManifest;
    }
  } catch {
    manifest = undefined;
  }

  const currentWheelHash = computeWheelHash(wheelDir);
  const extractNeeded = forceReinstall
    || !manifest
    || manifest.version !== version
    || manifest.wheelHash !== currentWheelHash
    || !fs.existsSync(path.join(targetDir, 'dapper', '__init__.py'));

  if (!extractNeeded) {
    deps.output.info(`dapper lib already extracted at ${targetDir}; reusing.`);
    return targetDir;
  }

  deps.output.info(`Extracting dapper ${version} to ${targetDir} for PYTHONPATH injection...`);
  if (fs.existsSync(targetDir)) {
    await fs.promises.rm(targetDir, { recursive: true, force: true });
  }

  try {
    await installToTargetDir(pythonPath, wheelDir, version, targetDir, deps);
    if (!fs.existsSync(path.join(targetDir, 'dapper', '__init__.py'))) {
      deps.output.error('Extraction succeeded but dapper/__init__.py not found in target dir');
      return undefined;
    }

    fs.mkdirSync(libBase, { recursive: true });
    fs.writeFileSync(manifestFile, JSON.stringify({ version, wheelHash: currentWheelHash }, null, 2), 'utf8');
    deps.output.info(`dapper ${version} extracted successfully to ${targetDir}`);
    return targetDir;
  } catch (error) {
    deps.output.error(`Failed to extract dapper to target dir: ${error}`);
    return undefined;
  }
}

export async function installToTargetDir(
  pythonPath: string,
  wheelDir: string,
  version: string,
  targetDir: string,
  deps: EnvironmentInstallDeps,
): Promise<void> {
  fs.mkdirSync(targetDir, { recursive: true });

  const allWheels = fs.readdirSync(wheelDir)
    .filter(fileName => fileName.startsWith(`dapper-${version}`) && fileName.endsWith('.whl'))
    .sort();
  if (allWheels.length === 0) {
    throw new Error(`No wheel files matching dapper-${version}*.whl found in ${wheelDir}`);
  }

  const wheelFile = path.join(wheelDir, allWheels[0]);
  deps.output.info(`Extracting wheel ${allWheels[0]} → ${targetDir}`);

  const extractScript = [
    'import sys, zipfile, os',
    'whl = sys.argv[1]',
    'dst = sys.argv[2]',
    'os.makedirs(dst, exist_ok=True)',
    'with zipfile.ZipFile(whl) as zf:',
    '    zf.extractall(dst)',
  ].join('\n');

  await deps.runProcess(pythonPath, ['-c', extractScript, wheelFile, targetDir], {
    label: `extract wheel dapper ${version}`,
  });
}

export function manifestPath(venvPath: string): string {
  return path.join(venvPath, 'dapper-env.json');
}

export function readManifest(
  venvPath: string,
  output: vscode.LogOutputChannel,
): EnvManifest | undefined {
  const filePath = manifestPath(venvPath);
  if (!fs.existsSync(filePath)) {
    return undefined;
  }
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8')) as EnvManifest;
  } catch (error) {
    output.warn(`Failed to read manifest: ${error}`);
    return undefined;
  }
}

export function writeManifest(
  venvPath: string,
  manifest: EnvManifest,
  output: vscode.LogOutputChannel,
): void {
  try {
    fs.writeFileSync(manifestPath(venvPath), JSON.stringify(manifest, null, 2), 'utf8');
  } catch (error) {
    output.warn(`Failed to write manifest: ${error}`);
  }
}

export function findBundledWheelDir(
  extensionPath: string,
  version: string,
  output: vscode.LogOutputChannel,
): string | undefined {
  if (!extensionPath) {
    return undefined;
  }
  const wheelDir = path.join(extensionPath, 'resources', 'python-wheels');
  if (!fs.existsSync(wheelDir)) {
    return undefined;
  }
  const files = fs.readdirSync(wheelDir).filter(fileName => fileName.startsWith(`dapper-${version}`) && fileName.endsWith('.whl'));
  if (files.length === 0) {
    return undefined;
  }
  output.debug(`findBundledWheelDir: found ${files.length} wheel(s) for v${version}: ${files.join(', ')}`);
  return wheelDir;
}

export function findBundledWheelVersions(extensionPath: string): string[] {
  if (!extensionPath) {
    return [];
  }
  const wheelDir = path.join(extensionPath, 'resources', 'python-wheels');
  if (!fs.existsSync(wheelDir)) {
    return [];
  }

  const versions = new Set<string>();
  for (const fileName of fs.readdirSync(wheelDir)) {
    const match = /^dapper-([^-]+)-.+\.whl$/.exec(fileName);
    if (match) {
      versions.add(match[1]);
    }
  }

  return [...versions].sort((left, right) => right.localeCompare(left, undefined, { numeric: true }));
}

export function computeWheelHash(wheelDir: string): string {
  const hash = createHash('sha256');
  for (const fileName of fs.readdirSync(wheelDir).filter(file => file.endsWith('.whl')).sort()) {
    hash.update(fileName);
    hash.update(fs.readFileSync(path.join(wheelDir, fileName)));
  }
  return hash.digest('hex');
}

export async function getDapperVersion(pythonPath: string): Promise<string | undefined> {
  try {
    const result = spawnSync(pythonPath, ['-c', 'import dapper; print(dapper.__version__)'], { encoding: 'utf8' });
    if (result.status === 0) {
      return (result.stdout || '').trim();
    }
  } catch {
  }
  return undefined;
}
