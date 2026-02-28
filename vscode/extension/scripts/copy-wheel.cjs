#!/usr/bin/env node
// Build the dapper wheel for every supported CPython version and copy all
// of them into resources/python-wheels/ for bundling with the extension.
//
// uv will auto-download any Python version that isn't already installed.

const fs = require('fs');
const path = require('path');
const os = require('os');
const { spawn } = require('child_process');

function log(msg) { process.stdout.write(`[copy-wheel] ${msg}\n`); }
function warn(msg) { process.stderr.write(`[copy-wheel WARN] ${msg}\n`); }
function fail(msg) { process.stderr.write(`[copy-wheel ERROR] ${msg}\n`); process.exit(1); }

// CPython versions to build for (must satisfy the package's requires-python >=3.9)
const PYTHON_VERSIONS = ['3.9', '3.10', '3.11', '3.12', '3.13'];

function buildWheel(rootDir, pyVer, outDir) {
  return new Promise((resolve) => {
    const lines = [];
    const child = spawn(
      'uv',
      ['build', '--wheel', '--python', pyVer, '--out-dir', outDir],
      { cwd: rootDir, shell: process.platform === 'win32' }
    );
    child.stdout.on('data', d => lines.push(d.toString().trimEnd()));
    child.stderr.on('data', d => lines.push(d.toString().trimEnd()));
    child.on('close', code => resolve({ pyVer, outDir, code, output: lines.join('\n') }));
    child.on('error', err => resolve({ pyVer, outDir, code: -1, output: err.message }));
  });
}

async function main() {
  const extensionDir = path.resolve(__dirname, '..');
  const rootDir = path.resolve(extensionDir, '..', '..');
  const resourcesDir = path.join(extensionDir, 'resources', 'python-wheels');

  // Clear out stale wheels so old versions don't accumulate
  if (fs.existsSync(resourcesDir)) {
    for (const f of fs.readdirSync(resourcesDir)) {
      if (f.endsWith('.whl')) {
        fs.rmSync(path.join(resourcesDir, f));
        log(`Removed stale wheel: ${f}`);
      }
    }
  }
  fs.mkdirSync(resourcesDir, { recursive: true });

  // Create a unique temp dir per Python version so builds don't race on dist/
  const tmpBase = fs.mkdtempSync(path.join(os.tmpdir(), 'dapper-wheels-'));
  const outDirs = Object.fromEntries(
    PYTHON_VERSIONS.map(v => [v, path.join(tmpBase, `py${v}`)])
  );
  for (const dir of Object.values(outDirs)) fs.mkdirSync(dir, { recursive: true });

  log(`Building wheels for Python ${PYTHON_VERSIONS.join(', ')} in parallel...`);
  const results = await Promise.all(PYTHON_VERSIONS.map(v => buildWheel(rootDir, v, outDirs[v])));

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

  // Cleanup temp dirs
  fs.rmSync(tmpBase, { recursive: true, force: true });

  const allWheels = fs.readdirSync(resourcesDir).filter(f => f.endsWith('.whl'));
  if (allWheels.length === 0) fail('No wheels were produced for any Python version.');
  log(`Done. ${copiedCount} new wheel(s) copied to ${resourcesDir}`);
  log(`Total wheels bundled: ${allWheels.length} (${allWheels.join(', ')})`);
}

main().catch(err => fail(err instanceof Error ? err.message : String(err)));
