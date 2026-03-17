import * as vscode from 'vscode';

import { runLoggedProcessResult } from '../environment/processRunner.js';
import type { EnvironmentSnapshotOptions, EnvironmentSnapshotService, PythonToolingEnvironmentSnapshot } from './environmentSnapshot.js';

export interface TyCheckOptions extends EnvironmentSnapshotOptions {
  files?: string[];
  cwd?: string;
}

export interface TyCheckResult {
  status: 'complete' | 'failed';
  command?: string;
  args: string[];
  cwd?: string;
  exitCode: number | null;
  diagnostics: unknown[];
  error?: string;
  resolution: PythonToolingEnvironmentSnapshot['ty']['resolution'];
}

export class TyRunnerService {
  constructor(
    private readonly output: vscode.LogOutputChannel,
    private readonly environmentSnapshotService: Pick<EnvironmentSnapshotService, 'getSnapshot'>,
  ) {}

  async runCheck(options: TyCheckOptions = {}): Promise<TyCheckResult> {
    const snapshot = await this.environmentSnapshotService.getSnapshot(options);
    const ty = snapshot.ty;

    if (!ty.available || !ty.command) {
      return {
        status: 'failed',
        args: [],
        cwd: this._resolveCwd(options, snapshot.workspaceFolder),
        exitCode: null,
        diagnostics: [],
        error: ty.error ?? 'Ty is not available in the selected environment.',
        resolution: ty.resolution,
      };
    }

    const cwd = this._resolveCwd(options, snapshot.workspaceFolder);
    const args = [...ty.args, 'check', '--output-format', 'gitlab', '--no-progress'];
    if (cwd) {
      args.push('--project', cwd);
    }
    if (snapshot.python.pythonPath) {
      args.push('--python', snapshot.python.pythonPath);
    }
    if (options.files?.length) {
      args.push(...options.files);
    }

    const result = await runLoggedProcessResult(this.output, ty.command, args, { label: 'ty check', cwd });
    const diagnostics = this._parseDiagnostics(result.stdout);

    if ((result.code === 0 || result.code === 1) && diagnostics) {
      return {
        status: 'complete',
        command: ty.command,
        args,
        cwd,
        exitCode: result.code,
        diagnostics,
        resolution: ty.resolution,
      };
    }

    return {
      status: 'failed',
      command: ty.command,
      args,
      cwd,
      exitCode: result.code,
      diagnostics: diagnostics ?? [],
      error: this._buildErrorMessage(result),
      resolution: ty.resolution,
    };
  }

  private _parseDiagnostics(output: string): unknown[] | undefined {
    const trimmed = output.trim();
    if (!trimmed) {
      return [];
    }

    try {
      const parsed = JSON.parse(trimmed);
      return Array.isArray(parsed) ? parsed : undefined;
    } catch {
      return undefined;
    }
  }

  private _resolveCwd(options: TyCheckOptions, workspaceFolder: string | undefined): string | undefined {
    return options.cwd ?? options.searchRootPath ?? options.workspaceFolder?.uri.fsPath ?? workspaceFolder;
  }

  private _buildErrorMessage(result: import('../environment/processRunner.js').ProcessRunResult): string {
    if (result.error?.message) {
      return result.error.message;
    }
    const parts: string[] = [];
    if (result.stderr) {
      parts.push(result.stderr);
    }
    if (!parts.length && result.stdout) {
      parts.push(result.stdout);
    }
    if (!parts.length) {
      parts.push(`Ty execution failed (exit code ${result.code}).`);
    }
    return parts.join('\n');
  }
}