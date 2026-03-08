import { spawn } from 'child_process';

import * as vscode from 'vscode';

export interface ProcessRunOptions {
  label: string;
}

export interface ProcessRunResult {
  ok: boolean;
  code: number | null;
  output: string;
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
    const child = spawn(cmd, args, { shell: process.platform === 'win32' });
    const outputLines: string[] = [];
    let settled = false;

    const finish = (result: ProcessRunResult) => {
      if (settled) {
        return;
      }
      settled = true;
      resolve(result);
    };

    const onData = (chunk: Buffer) => {
      const text = chunk.toString().trimEnd();
      output.trace(text);
      outputLines.push(text);
    };

    child.stdout.on('data', onData);
    child.stderr.on('data', onData);
    child.on('error', error => {
      finish({ ok: false, code: null, output: outputLines.filter(Boolean).join('\n'), error });
    });
    child.on('close', code => {
      finish({ ok: code === 0, code, output: outputLines.filter(Boolean).join('\n') });
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
