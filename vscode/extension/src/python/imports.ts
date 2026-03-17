import type { RuffImportCleanupOptions, RuffOrganizeImportsOptions, RuffRunnerService, RuffWriteResult } from './ruffRunner.js';

export type PythonImportsMode = 'cleanup' | 'organize' | 'all';

export interface PythonImportsOptions {
  mode?: PythonImportsMode;
  files?: string[];
  cwd?: string;
  apply?: boolean;
  unsafe?: boolean;
  workspaceFolder?: RuffImportCleanupOptions['workspaceFolder'];
  searchRootPath?: string;
}

export interface PythonImportsResult extends RuffWriteResult {
  mode: PythonImportsMode;
}

export interface PythonImportsAllResult {
  mode: 'all';
  cleanup: PythonImportsResult;
  organize: PythonImportsResult;
}

export class PythonImportsService {
  constructor(
    private readonly ruffRunnerService: Pick<RuffRunnerService, 'runImportCleanup' | 'runOrganizeImports'>,
  ) {}

  async run(options: PythonImportsOptions = {}): Promise<PythonImportsResult | PythonImportsAllResult> {
    const mode = options.mode ?? 'all';

    if (mode === 'cleanup') {
      return this._runCleanup(options);
    }
    if (mode === 'organize') {
      return this._runOrganize(options);
    }

    const [cleanup, organize] = await Promise.all([
      this._runCleanup(options),
      this._runOrganize(options),
    ]);
    return { mode: 'all', cleanup, organize };
  }

  private async _runCleanup(options: PythonImportsOptions): Promise<PythonImportsResult> {
    const result = await this.ruffRunnerService.runImportCleanup({
      workspaceFolder: options.workspaceFolder,
      searchRootPath: options.searchRootPath,
      files: options.files,
      cwd: options.cwd,
      apply: options.apply,
      unsafe: options.unsafe,
    } satisfies RuffImportCleanupOptions);
    return { ...result, mode: 'cleanup' };
  }

  private async _runOrganize(options: PythonImportsOptions): Promise<PythonImportsResult> {
    const result = await this.ruffRunnerService.runOrganizeImports({
      workspaceFolder: options.workspaceFolder,
      searchRootPath: options.searchRootPath,
      files: options.files,
      cwd: options.cwd,
      apply: options.apply,
    } satisfies RuffOrganizeImportsOptions);
    return { ...result, mode: 'organize' };
  }
}
