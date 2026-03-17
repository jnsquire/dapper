import { spawn } from 'child_process';

import * as vscode from 'vscode';

export interface ProcessRunOptions {
  label: string;
  cwd?: string;
}

export interface ProcessRunResult {
  ok: boolean;
  code: number | null;
  output: string;
  stdout: string;
  stderr: string;
  error?: Error;
}

function formatProcessFailure(result: ProcessRunResult, label: string): Error {
  if (result.error) {
    return result.error;
  }
  const suffix = result.output ? `:\n${result.output}` : '';
  return new Error(`${label} exited with code ${result.code}${suffix}`);
}

export function runLoggedProcessResult(
  output: vscode.LogOutputChannel,
  cmd: string,
  args: string[],
  opts: ProcessRunOptions,
): Promise<ProcessRunResult> {
  return new Promise((resolve) => {
    output.debug(`[run] ${opts.label}: ${cmd} ${args.join(' ')}`);
    const child = spawn(cmd, args, { shell: process.platform === 'win32', cwd: opts.cwd });
    const stdoutChunks: string[] = [];
    const stderrChunks: string[] = [];
    let settled = false;

    const finish = (result: ProcessRunResult) => {
      if (settled) {
        return;
      }
      settled = true;
      resolve(result);
    };

    child.stdout.on('data', (chunk: Buffer) => {
      const text = chunk.toString();
      output.trace(text.trimEnd());
      stdoutChunks.push(text);
    });
    child.stderr.on('data', (chunk: Buffer) => {
      const text = chunk.toString();
      output.trace(text.trimEnd());
      stderrChunks.push(text);
    });
    child.on('error', error => {
      const stdout = stdoutChunks.join('');
      const stderr = stderrChunks.join('');
      finish({ ok: false, code: null, output: [stdout, stderr].filter(Boolean).join('\n'), stdout, stderr, error });
    });
    child.on('close', code => {
      const stdout = stdoutChunks.join('');
      const stderr = stderrChunks.join('');
      finish({ ok: code === 0, code, output: [stdout, stderr].filter(Boolean).join('\n'), stdout, stderr });
    });
  });
}

export async function runLoggedProcess(
  output: vscode.LogOutputChannel,
  cmd: string,
  args: string[],
  opts: ProcessRunOptions,
): Promise<void> {
  const result = await runLoggedProcessResult(output, cmd, args, opts);
  if (!result.ok) {
    throw formatProcessFailure(result, opts.label);
  }
}
