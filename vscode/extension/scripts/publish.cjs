const { spawnSync } = require('child_process');
const path = require('path');

const root = path.resolve(__dirname, '..');
const pkg = require(path.join(root, 'package.json'));
const outFile = path.join(root, 'dist', `${pkg.name}-${pkg.version}.vsix`);
const isPreRelease = process.argv.includes('--pre-release');

console.log(`Publishing ${pkg.publisher}.${pkg.name} from ${outFile}`);
if (!process.env.VSCE_PAT) {
  console.log('VSCE_PAT is not set. vsce may prompt for a Personal Access Token if you have not already logged in.');
}

const packageResult = spawnSync('node', [path.join('scripts', 'package.cjs')], {
  cwd: root,
  stdio: 'inherit',
  shell: true,
});
if (packageResult.error || packageResult.status !== 0) {
  console.error('Packaging failed before publish');
  process.exit(packageResult.status || 1);
}

const args = ['vsce', 'publish', '--packagePath', outFile];
if (isPreRelease) {
  args.push('--pre-release');
}

const publishResult = spawnSync('npx', args, {
  cwd: root,
  stdio: 'inherit',
  shell: true,
  env: process.env,
});
if (publishResult.error) {
  console.error('Failed to run vsce publish:', publishResult.error);
  process.exit(1);
}

process.exit(publishResult.status || 0);