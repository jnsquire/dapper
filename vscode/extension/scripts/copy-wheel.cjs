#!/usr/bin/env node
// Copy the built dapper wheel into the extension resources/python-wheels directory.
// Steps:
// 1. Run `uv build` (fails gracefully if uv missing)
// 2. Locate wheel matching extension version (fallback to first wheel)
// 3. Ensure resources/python-wheels exists
// 4. Copy wheel (overwrite) and log result

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

function log(msg) { process.stdout.write(`[copy-wheel] ${msg}\n`); }
function warn(msg) { process.stderr.write(`[copy-wheel WARN] ${msg}\n`); }
function fail(msg) { process.stderr.write(`[copy-wheel ERROR] ${msg}\n`); process.exit(1); }

try {
  const extensionDir = path.resolve(__dirname, '..');
  const rootDir = path.resolve(extensionDir, '..', '..');
  const distDir = path.join(rootDir, 'dist');
  const resourcesDir = path.join(extensionDir, 'resources', 'python-wheels');
  const pkgJson = JSON.parse(fs.readFileSync(path.join(extensionDir, 'package.json'), 'utf8'));
  const extVersion = pkgJson.version;

  // Attempt uv build
  log('Running `uv build` to produce fresh wheel...');
  const uvResult = spawnSync('uv', ['build'], { cwd: rootDir, stdio: 'inherit', shell: process.platform === 'win32' });
  if (uvResult.status !== 0) {
    warn('`uv build` failed or uv not installed; continuing if wheel already exists.');
  }

  if (!fs.existsSync(distDir)) {
    fail(`dist directory not found at ${distDir}`);
  }
  const wheels = fs.readdirSync(distDir).filter(f => /^dapper-.*\.whl$/.test(f));
  if (wheels.length === 0) {
    fail('No dapper wheel found in dist/. Did the build succeed?');
  }

  // Prefer exact version match
  const versionPattern = new RegExp(`^dapper-${extVersion}.*\\.whl$`);
  let wheelName = wheels.find(w => versionPattern.test(w));
  if (!wheelName) {
    warn(`No wheel matching extension version ${extVersion}; using first available wheel ${wheels[0]}`);
    wheelName = wheels[0];
  }

  const wheelSrc = path.join(distDir, wheelName);
  fs.mkdirSync(resourcesDir, { recursive: true });
  const wheelDest = path.join(resourcesDir, wheelName);
  fs.copyFileSync(wheelSrc, wheelDest);
  log(`Copied wheel ${wheelName} to ${wheelDest}`);
  process.exit(0);
} catch (err) {
  fail(err instanceof Error ? err.message : String(err));
}
