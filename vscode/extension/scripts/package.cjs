const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const pkgPath = path.join(root, 'package.json');
const pkg = require(pkgPath);

const outDir = path.join(root, 'dist');
fs.mkdirSync(outDir, { recursive: true });
const outFile = path.join(outDir, `${pkg.name}-${pkg.version}.vsix`);
const useFreshInstall = process.argv.includes('--fresh');

console.log(`Packaging extension to ${outFile}`);
if (useFreshInstall) {
  console.log('Fresh mode enabled. Running npm ci before build.');
}

const nodeModulesPath = path.join(root, 'node_modules');
if (useFreshInstall || !fs.existsSync(nodeModulesPath)) {
  console.log(useFreshInstall ? 'Installing fresh dependencies...' : 'node_modules not found. Installing dependencies...');
  const devInstallRes = spawnSync('npm', ['ci'], { cwd: root, stdio: 'inherit', shell: true });
  if (devInstallRes.error || devInstallRes.status !== 0) {
    console.error('Failed to install dependencies:', devInstallRes.error || `exit code ${devInstallRes.status}`);
    process.exit(devInstallRes.status || 1);
  }
} else {
  console.log('Using existing dependencies in node_modules.');
}

// Build the extension so out/ contains compiled artifacts
console.log('Building extension for packaging...');
const buildRes = spawnSync('npm', ['run', 'build'], { cwd: root, stdio: 'inherit', shell: true });
if (buildRes.error || buildRes.status !== 0) {
  console.error('Build failed before packaging');
  process.exit(buildRes.status || 1);
}

// Use npx to ensure the locally installed vsce is used when available.
const cmd = 'npx';
const args = ['vsce', 'package', '--out', outFile];

const env = Object.assign({}, process.env, { SKIP_VSCODE_PREPUBLISH: '1' });
const res = spawnSync(cmd, args, { cwd: root, stdio: 'inherit', shell: true, env });
if (res.error) {
  console.error('Failed to run vsce:', res.error);
  process.exit(1);
}

process.exit(res.status || 0);
