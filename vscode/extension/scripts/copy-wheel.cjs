#!/usr/bin/env node
// Build the dapper wheel for every supported CPython version and copy all
// of them into resources/python-wheels/ for bundling with the extension.
//
// Each version is built inside a temporary venv created with the stdlib
// `venv` module.  The target Python interpreter for each version must
// already be installed on the system (e.g. python3.9, python3.10, …).
// On Windows the `py` launcher is tried first (e.g. `py -3.9`).

const fs = require('fs');
const path = require('path');
const os = require('os');
const crypto = require('crypto');
const { spawn, spawnSync } = require('child_process');

function log(msg)  { process.stdout.write(`[copy-wheel] ${msg}\n`); }
function warn(msg) { process.stderr.write(`[copy-wheel WARN] ${msg}\n`); }
function fail(msg) { process.stderr.write(`[copy-wheel ERROR] ${msg}\n`); process.exit(1); }

// CPython versions to build for (must satisfy the package's requires-python >=3.9)
const PYTHON_VERSIONS = ['3.9', '3.10', '3.11', '3.12', '3.13', '3.14'];

const DOWNLOAD_MISSING = process.argv.includes('--download-missing');
const FORCE_REBUILD = process.argv.includes('--force');

const FINGERPRINT_ROOTS = ['dapper'];
const FINGERPRINT_FILE_EXTENSIONS = new Set(['.py', '.pyx', '.pxd', '.pxi', '.c', '.h']);
const FINGERPRINT_FILES = ['pyproject.toml', 'setup.py', 'setup.cfg', 'MANIFEST.in', 'README.md'];
const BUILD_MANIFEST_FILE = '.build-manifest.json';

function walkFiles(dirPath, relativeTo, files = []) {
  if (!fs.existsSync(dirPath)) {
    return files;
  }

  const entries = fs.readdirSync(dirPath, { withFileTypes: true });
  for (const entry of entries) {
    if (entry.name === '__pycache__') {
      continue;
    }

    const fullPath = path.join(dirPath, entry.name);
    if (entry.isDirectory()) {
      walkFiles(fullPath, relativeTo, files);
      continue;
    }

    if (FINGERPRINT_FILE_EXTENSIONS.has(path.extname(entry.name))) {
      files.push(path.relative(relativeTo, fullPath).split(path.sep).join('/'));
    }
  }

  return files;
}

function computeInputFingerprint(rootDir) {
  const hash = crypto.createHash('sha256');
  const relativeFiles = [];

  for (const file of FINGERPRINT_FILES) {
    const fullPath = path.join(rootDir, file);
    if (fs.existsSync(fullPath)) {
      relativeFiles.push(file);
    }
  }

  for (const dir of FINGERPRINT_ROOTS) {
    walkFiles(path.join(rootDir, dir), rootDir, relativeFiles);
  }

  relativeFiles.sort();

  for (const relativeFile of relativeFiles) {
    const fullPath = path.join(rootDir, relativeFile);
    hash.update(relativeFile);
    hash.update('\0');
    hash.update(fs.readFileSync(fullPath));
    hash.update('\0');
  }

  return {
    fingerprint: hash.digest('hex'),
    files: relativeFiles,
  };
}

function readBuildManifest(resourcesDir) {
  const manifestPath = path.join(resourcesDir, BUILD_MANIFEST_FILE);
  if (!fs.existsSync(manifestPath)) {
    return null;
  }

  try {
    return JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  } catch (error) {
    warn(`Failed to read build manifest at ${manifestPath}: ${error}`);
    return null;
  }
}

function writeBuildManifest(resourcesDir, manifest) {
  const manifestPath = path.join(resourcesDir, BUILD_MANIFEST_FILE);
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2), 'utf8');
}

function existingWheelFiles(resourcesDir) {
  if (!fs.existsSync(resourcesDir)) {
    return [];
  }

  return fs.readdirSync(resourcesDir)
    .filter(f => f.endsWith('.whl'))
    .sort();
}

function canReuseExistingWheels(resourcesDir, inputFingerprint) {
  if (FORCE_REBUILD) {
    return false;
  }

  const manifest = readBuildManifest(resourcesDir);
  if (!manifest || manifest.inputFingerprint !== inputFingerprint) {
    return false;
  }

  const currentWheels = existingWheelFiles(resourcesDir);
  const recordedWheels = Array.isArray(manifest.wheels) ? [...manifest.wheels].sort() : [];
  if (recordedWheels.length === 0 || currentWheels.length !== recordedWheels.length) {
    return false;
  }

  return recordedWheels.every((wheel, index) => currentWheels[index] === wheel);
}

/** Return a Promise that resolves with { code, output } for a spawned command. */
function run(cmd, args, options = {}) {
  return new Promise((resolve) => {
    const lines = [];
    const child = spawn(cmd, args, { shell: process.platform === 'win32', ...options });
    child.stdout?.on('data', d => lines.push(d.toString().trimEnd()));
    child.stderr?.on('data', d => lines.push(d.toString().trimEnd()));
    child.on('close', code => resolve({ code, output: lines.join('\n') }));
    child.on('error', err  => resolve({ code: -1, output: err.message }));
  });
}

/** Check whether `uv` is available on PATH. */
function uvAvailable() {
  const r = spawnSync('uv', ['--version'], { encoding: 'utf8' });
  return r.status === 0;
}

/**
 * Use `uv python install X.Y` to download a Python version, then return
 * the path to its interpreter via `uv python find X.Y`.
 * Returns the interpreter path string, or null on failure.
 */
async function downloadPython(pyVer) {
  log(`Downloading Python ${pyVer} via uv...`);
  const installRes = await run('uv', ['python', 'install', pyVer]);
  if (installRes.code !== 0) {
    warn(`uv python install ${pyVer} failed:\n${installRes.output}`);
    return null;
  }
  const findRes = spawnSync('uv', ['python', 'find', pyVer], { encoding: 'utf8' });
  if (findRes.status !== 0) {
    warn(`uv python find ${pyVer} failed after install.`);
    return null;
  }
  return findRes.stdout.trim();
}

/**
 * Find the system Python executable for a given X.Y version string.
 * Returns [cmd, extraArgs] or null if not found.
 */
function findPythonExec(pyVer) {
  if (process.platform === 'win32') {
    // Prefer the Windows `py` launcher
    const r = spawnSync('py', [`-${pyVer}`, '-c', 'import sys; print(sys.version)'], { encoding: 'utf8' });
    if (r.status === 0) return ['py', [`-${pyVer}`]];
    // Fallback: python3.X on PATH
    const r2 = spawnSync(`python${pyVer}`, ['--version'], { encoding: 'utf8', shell: true });
    if (r2.status === 0) return [`python${pyVer}`, []];
  } else {
    // Unix: python3.X (standard on most distros)
    const r = spawnSync(`python${pyVer}`, ['--version'], { encoding: 'utf8' });
    if (r.status === 0) return [`python${pyVer}`, []];
  }
  return null;
}

async function buildWheel(rootDir, pyVer, outDir) {
  let pyCmd, pyArgs;

  const found = findPythonExec(pyVer);
  if (found) {
    [pyCmd, pyArgs] = found;
  } else if (DOWNLOAD_MISSING) {
    if (!uvAvailable()) {
      return { pyVer, outDir, code: -1, output: `Python ${pyVer} not found and 'uv' is not on PATH – cannot download.` };
    }
    const downloaded = await downloadPython(pyVer);
    if (!downloaded) {
      return { pyVer, outDir, code: -1, output: `Python ${pyVer} could not be downloaded.` };
    }
    pyCmd = downloaded;
    pyArgs = [];
  } else {
    return { pyVer, outDir, code: -1, output: `Python ${pyVer} not found on PATH – skipping. (Pass --download-missing to auto-install.)` };
  }

  const venvDir = path.join(os.tmpdir(), `dapper-venv-${pyVer.replace('.', '')}-${process.pid}`);

  // 1. Create isolated venv
  const createRes = await run(pyCmd, [...pyArgs, '-m', 'venv', venvDir]);
  if (createRes.code !== 0) {
    return { pyVer, outDir, code: createRes.code, output: `venv creation failed:\n${createRes.output}` };
  }

  const venvPython = process.platform === 'win32'
    ? path.join(venvDir, 'Scripts', 'python.exe')
    : path.join(venvDir, 'bin', 'python');

  // 2. Install the `build` front-end inside the venv
  const installRes = await run(venvPython, ['-m', 'pip', 'install', '--quiet', 'build']);
  if (installRes.code !== 0) {
    fs.rmSync(venvDir, { recursive: true, force: true });
    return { pyVer, outDir, code: installRes.code, output: `pip install build failed:\n${installRes.output}` };
  }

  // 3. Build the wheel
  const buildRes = await run(venvPython, ['-m', 'build', '--wheel', '--outdir', outDir, rootDir]);

  fs.rmSync(venvDir, { recursive: true, force: true });

  const combinedOutput = [createRes.output, installRes.output, buildRes.output].filter(Boolean).join('\n');
  return { pyVer, outDir, code: buildRes.code, output: combinedOutput };
}

async function main() {
  const extensionDir = path.resolve(__dirname, '..');
  const rootDir = path.resolve(extensionDir, '..', '..');
  const resourcesDir = path.join(extensionDir, 'resources', 'python-wheels');
  fs.mkdirSync(resourcesDir, { recursive: true });

  const { fingerprint: inputFingerprint, files: fingerprintFiles } = computeInputFingerprint(rootDir);
  if (canReuseExistingWheels(resourcesDir, inputFingerprint)) {
    const wheels = existingWheelFiles(resourcesDir);
    log(`Inputs unchanged; reusing existing bundled wheels from ${resourcesDir}`);
    log(`Total wheels bundled: ${wheels.length} (${wheels.join(', ')})`);
    return;
  }

  // Clear out stale wheels so old versions don't accumulate
  if (fs.existsSync(resourcesDir)) {
    for (const f of fs.readdirSync(resourcesDir)) {
      if (f.endsWith('.whl')) {
        fs.rmSync(path.join(resourcesDir, f));
        log(`Removed stale wheel: ${f}`);
      }
    }
  }
  // Create a unique output dir per Python version so builds don't race on dist/
  const outDirs = Object.fromEntries(
    PYTHON_VERSIONS.map(v => [v, fs.mkdtempSync(path.join(os.tmpdir(), `dapper-out-py${v.replace('.', '')}-`))])
  );

  // Builds must run sequentially: setuptools writes intermediate files to
  // build/bdist.linux-x86_64/wheel/ inside the project root, so parallel
  // builds race on that shared directory and corrupt each other's output.
  log(`Building wheels for Python ${PYTHON_VERSIONS.join(', ')} (sequential to avoid build-dir races)...`);
  const results = [];
  for (const v of PYTHON_VERSIONS) {
    results.push(await buildWheel(rootDir, v, outDirs[v]));
  }

  let copiedCount = 0;
  for (const { pyVer, outDir, code, output } of results) {
    if (code !== 0) {
      warn(`Build for Python ${pyVer} failed (exit ${code}):\n${output}`);
      continue;
    }
    const wheels = fs.readdirSync(outDir).filter(f => /^dapper-.*\.whl$/.test(f));
    if (wheels.length === 0) {
      warn(`No wheel produced for Python ${pyVer}; skipping.`);
      continue;
    }
    for (const wheelName of wheels) {
      const dest = path.join(resourcesDir, wheelName);
      fs.copyFileSync(path.join(outDir, wheelName), dest);
      log(`  -> ${wheelName}`);
      copiedCount++;
    }
  }

  // Cleanup temp output dirs
  for (const dir of Object.values(outDirs)) fs.rmSync(dir, { recursive: true, force: true });

  const allWheels = fs.readdirSync(resourcesDir).filter(f => f.endsWith('.whl'));
  if (allWheels.length === 0) fail('No wheels were produced for any Python version.');
  writeBuildManifest(resourcesDir, {
    inputFingerprint,
    fingerprintFiles,
    wheels: allWheels.sort(),
    pythonVersions: PYTHON_VERSIONS,
    builtAt: new Date().toISOString(),
  });
  log(`Done. ${copiedCount} new wheel(s) copied to ${resourcesDir}`);
  log(`Total wheels bundled: ${allWheels.length} (${allWheels.join(', ')})`);
}

main().catch(err => fail(err instanceof Error ? err.message : String(err)));
