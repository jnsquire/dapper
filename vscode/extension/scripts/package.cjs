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

// Use npx to ensure the locally installed vsce is used when available.
const cmd = 'npx';
const args = ['vsce', 'package', '--out', outFile];

const res = spawnSync(cmd, args, { cwd: root, stdio: 'inherit', shell: true });
if (res.error) {
  console.error('Failed to run vsce:', res.error);
  process.exit(1);
}
process.exit(res.status);
