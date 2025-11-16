const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const pkgPath = path.join(root, 'package.json');
const pkg = require(pkgPath);

const outDir = path.join(root, 'dist');
fs.mkdirSync(outDir, { recursive: true });
const outFile = path.join(outDir, `${pkg.name}-${pkg.version}.vsix`);

console.log(`Packaging extension to ${outFile}`);

// Install only production dependencies to avoid bundling dev packages into the vsix
// Ensure the dev dependencies are installed so we can build the extension first
console.log('Ensuring dev dependencies are installed for build...');
const devInstallRes = spawnSync('npm', ['ci'], { cwd: root, stdio: 'inherit', shell: true });
if (devInstallRes.error) {
  console.error('Failed to install dependencies:', devInstallRes.error);
  process.exit(1);
}

// Build the extension so out/ contains compiled artifacts
console.log('Building extension for packaging...');
const buildRes = spawnSync('npm', ['run', 'build'], { cwd: root, stdio: 'inherit', shell: true });
if (buildRes.error || buildRes.status !== 0) {
  console.error('Build failed before packaging');
  process.exit(buildRes.status || 1);
}

// Now replace node_modules with production-only dependencies to shrink vsix
console.log('Installing production-only dependencies for packaging...');
const installRes = spawnSync('npm', ['ci', '--omit=dev'], { cwd: root, stdio: 'inherit', shell: true });
if (installRes.error) {
  console.error('Failed to install production dependencies:', installRes.error);
  process.exit(1);
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
process.exit(res.status);
