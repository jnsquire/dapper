#!/usr/bin/env node
const { spawnSync } = require('child_process');

const extraArgs = process.argv.slice(2);

function run(cmd, args = []) {
  const res = spawnSync(cmd, args, { stdio: 'inherit', shell: true });
  if (res.error) {
    console.error(`Failed to run ${cmd} ${args.join(' ')}:`, res.error);
    process.exit(1);
  }
  if (res.status !== 0) {
    process.exit(res.status);
  }
}

console.log('Running prepare-python' + (extraArgs.length ? ` with args: ${extraArgs.join(' ')}` : ''));
const prepareArgs = extraArgs.length ? ['run', 'prepare-python', '--', ...extraArgs] : ['run', 'prepare-python'];
run('npm', prepareArgs);

// Continue with the remaining build steps
run('npm', ['run', 'compile']);
run('npm', ['run', 'bundle:extension']);

process.exit(0);
