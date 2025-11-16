const { spawnSync } = require('child_process');
if (process.env.SKIP_VSCODE_PREPUBLISH) {
  console.log('Skipping vscode:prepublish because SKIP_VSCODE_PREPUBLISH is set.');
  process.exit(0);
}
console.log('Running vscode:prepublish: prepare-python and build');
let result = spawnSync('npm', ['run', 'prepare-python'], { cwd: process.cwd(), stdio: 'inherit', shell: true });
if (result.status !== 0) process.exit(result.status);
result = spawnSync('npm', ['run', 'build'], { cwd: process.cwd(), stdio: 'inherit', shell: true });
if (result.status !== 0) process.exit(result.status);
process.exit(0);
