import * as vscode from 'vscode';

import { runLoggedProcessResult } from '../environment/processRunner.js';
import type { EnvironmentSnapshotOptions, EnvironmentSnapshotService, PythonToolingEnvironmentSnapshot } from './environmentSnapshot.js';

export interface RuffCheckOptions extends EnvironmentSnapshotOptions {
  files?: string[];
  fix?: boolean;
  cwd?: string;
}

export interface RuffAutofixOptions extends EnvironmentSnapshotOptions {
  files?: string[];
  cwd?: string;
  apply?: boolean;
  unsafe?: boolean;
}

export interface RuffFormatOptions extends EnvironmentSnapshotOptions {
  files?: string[];
  cwd?: string;
  apply?: boolean;
}

export interface RuffImportCleanupOptions extends EnvironmentSnapshotOptions {
  files?: string[];
  cwd?: string;
  apply?: boolean;
  unsafe?: boolean;
}

export interface RuffOrganizeImportsOptions extends EnvironmentSnapshotOptions {
  files?: string[];
  cwd?: string;
  apply?: boolean;
}

export interface RuffCheckResult {
  status: 'complete' | 'failed';
  command?: string;
  args: string[];
  cwd?: string;
  exitCode: number | null;
  diagnostics: unknown[];
  error?: string;
  resolution: PythonToolingEnvironmentSnapshot['ruff']['resolution'];
}

export interface RuffWriteResult {
  status: 'complete' | 'failed';
  command?: string;
  args: string[];
  cwd?: string;
  exitCode: number | null;
  changed: boolean;
  applied: boolean;
  diff?: string;
  error?: string;
  resolution: PythonToolingEnvironmentSnapshot['ruff']['resolution'];
}

export class RuffRunnerService {
  constructor(
    private readonly output: vscode.LogOutputChannel,
    private readonly environmentSnapshotService: Pick<EnvironmentSnapshotService, 'getSnapshot'>,
  ) {}

  async runCheck(options: RuffCheckOptions = {}): Promise<RuffCheckResult> {
    const snapshot = await this.environmentSnapshotService.getSnapshot(options);
    const ruff = snapshot.ruff;

    if (!ruff.available || !ruff.command) {
      return {
        status: 'failed',
        args: [],
        cwd: options.cwd ?? options.workspaceFolder?.uri.fsPath ?? snapshot.workspaceFolder,
        exitCode: null,
        diagnostics: [],
        error: ruff.error ?? 'Ruff is not available in the selected environment.',
        resolution: ruff.resolution,
      };
    }

    const args = [...ruff.args, 'check', '--output-format', 'json'];
    if (options.fix) {
      args.push('--fix');
    }
    if (options.files?.length) {
      args.push(...options.files);
    }

    const cwd = this._resolveCwd(options, snapshot.workspaceFolder);
    const result = await runLoggedProcessResult(this.output, ruff.command, args, { label: 'ruff check', cwd });
    const diagnostics = this._parseDiagnostics(result.stdout);

    if ((result.code === 0 || result.code === 1) && diagnostics) {
      return {
        status: 'complete',
        command: ruff.command,
        args,
        cwd,
        exitCode: result.code,
        diagnostics,
        resolution: ruff.resolution,
      };
    }

    return {
      status: 'failed',
      command: ruff.command,
      args,
      cwd,
      exitCode: result.code,
      diagnostics: diagnostics ?? [],
      error: result.error?.message ?? (result.stderr || result.stdout || 'Ruff execution failed.'),
      resolution: ruff.resolution,
    };
  }

  async runAutofix(options: RuffAutofixOptions = {}): Promise<RuffWriteResult> {
    const snapshot = await this.environmentSnapshotService.getSnapshot(options);
    const ruff = snapshot.ruff;
    const cwd = this._resolveCwd(options, snapshot.workspaceFolder);

    if (!ruff.available || !ruff.command) {
      return {
        status: 'failed',
        args: [],
        cwd,
        exitCode: null,
        changed: false,
        applied: options.apply !== false,
        error: ruff.error ?? 'Ruff is not available in the selected environment.',
        resolution: ruff.resolution,
      };
    }

    const apply = options.apply !== false;
    const args = [...ruff.args, 'check'];
    if (apply) {
      args.push('--fix-only', '--exit-non-zero-on-fix');
    } else {
      args.push('--diff');
    }
    if (options.unsafe) {
      args.push('--unsafe-fixes');
    }
    if (options.files?.length) {
      args.push(...options.files);
    }

    const result = await runLoggedProcessResult(this.output, ruff.command, args, { label: 'ruff autofix', cwd });
    const changed = apply ? result.code === 1 : result.stdout.trim().length > 0 || result.code === 1;

    if (result.code === 0 || result.code === 1) {
      return {
        status: 'complete',
        command: ruff.command,
        args,
        cwd,
        exitCode: result.code,
        changed,
        applied: apply,
        diff: apply ? undefined : (result.stdout || undefined),
        resolution: ruff.resolution,
      };
    }

    return {
      status: 'failed',
      command: ruff.command,
      args,
      cwd,
      exitCode: result.code,
      changed,
      applied: apply,
      diff: apply ? undefined : (result.stdout || undefined),
      error: result.error?.message ?? (result.stderr || result.stdout || 'Ruff autofix execution failed.'),
      resolution: ruff.resolution,
    };
  }

  async runFormat(options: RuffFormatOptions = {}): Promise<RuffWriteResult> {
    const snapshot = await this.environmentSnapshotService.getSnapshot(options);
    const ruff = snapshot.ruff;
    const cwd = this._resolveCwd(options, snapshot.workspaceFolder);

    if (!ruff.available || !ruff.command) {
      return {
        status: 'failed',
        args: [],
        cwd,
        exitCode: null,
        changed: false,
        applied: options.apply !== false,
        error: ruff.error ?? 'Ruff is not available in the selected environment.',
        resolution: ruff.resolution,
      };
    }

    const apply = options.apply !== false;
    const args = [...ruff.args, 'format'];
    if (apply) {
      args.push('--exit-non-zero-on-format');
    } else {
      args.push('--diff');
    }
    if (options.files?.length) {
      args.push(...options.files);
    }

    const result = await runLoggedProcessResult(this.output, ruff.command, args, { label: 'ruff format', cwd });
    const changed = apply ? result.code === 1 : result.stdout.trim().length > 0 || result.code === 1;

    if (result.code === 0 || result.code === 1) {
      return {
        status: 'complete',
        command: ruff.command,
        args,
        cwd,
        exitCode: result.code,
        changed,
        applied: apply,
        diff: apply ? undefined : (result.stdout || undefined),
        resolution: ruff.resolution,
      };
    }

    return {
      status: 'failed',
      command: ruff.command,
      args,
      cwd,
      exitCode: result.code,
      changed,
      applied: apply,
      diff: apply ? undefined : (result.stdout || undefined),
      error: result.error?.message ?? (result.stderr || result.stdout || 'Ruff format execution failed.'),
      resolution: ruff.resolution,
    };
  }

  async runImportCleanup(options: RuffImportCleanupOptions = {}): Promise<RuffWriteResult> {
    return this._runRuleScopedFix(options, {
      label: 'ruff import cleanup',
      selection: 'F401',
      unsafe: options.unsafe === true,
    });
  }

  async runOrganizeImports(options: RuffOrganizeImportsOptions = {}): Promise<RuffWriteResult> {
    return this._runRuleScopedFix(options, {
      label: 'ruff organize imports',
      selection: 'I',
      unsafe: false,
    });
  }

  private async _runRuleScopedFix(
    options: EnvironmentSnapshotOptions & { files?: string[]; cwd?: string; apply?: boolean },
    config: { label: string; selection: string; unsafe: boolean },
  ): Promise<RuffWriteResult> {
    const snapshot = await this.environmentSnapshotService.getSnapshot(options);
    const ruff = snapshot.ruff;
    const cwd = this._resolveCwd(options, snapshot.workspaceFolder);

    if (!ruff.available || !ruff.command) {
      return {
        status: 'failed',
        args: [],
        cwd,
        exitCode: null,
        changed: false,
        applied: options.apply !== false,
        error: ruff.error ?? 'Ruff is not available in the selected environment.',
        resolution: ruff.resolution,
      };
    }

    const apply = options.apply !== false;
    const args = [...ruff.args, 'check', '--select', config.selection];
    if (apply) {
      args.push('--fix-only', '--exit-non-zero-on-fix');
    } else {
      args.push('--diff');
    }
    if (config.unsafe) {
      args.push('--unsafe-fixes');
    }
    if (options.files?.length) {
      args.push(...options.files);
    }

    const result = await runLoggedProcessResult(this.output, ruff.command, args, { label: config.label, cwd });
    const changed = apply ? result.code === 1 : result.stdout.trim().length > 0 || result.code === 1;

    if (result.code === 0 || result.code === 1) {
      return {
        status: 'complete',
        command: ruff.command,
        args,
        cwd,
        exitCode: result.code,
        changed,
        applied: apply,
        diff: apply ? undefined : (result.stdout || undefined),
        resolution: ruff.resolution,
      };
    }

    return {
      status: 'failed',
      command: ruff.command,
      args,
      cwd,
      exitCode: result.code,
      changed,
      applied: apply,
      diff: apply ? undefined : (result.stdout || undefined),
      error: result.error?.message ?? (result.stderr || result.stdout || `${config.label} execution failed.`),
      resolution: ruff.resolution,
    };
  }

  private _resolveCwd(
    options: EnvironmentSnapshotOptions & { cwd?: string },
    workspaceFolder: string | undefined,
  ): string | undefined {
    return options.cwd ?? options.workspaceFolder?.uri.fsPath ?? workspaceFolder;
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
}