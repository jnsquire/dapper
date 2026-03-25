import type { EnvironmentSnapshotOptions, EnvironmentSnapshotService } from './environmentSnapshot.js';
import type { RuffCheckOptions, RuffCheckResult, RuffRunnerService } from './ruffRunner.js';
import type { PythonDiagnosticContext, PythonTypeInfo } from './semanticPayloads.js';
import type { TyCheckResult, TyRunnerService } from './tyRunner.js';
import { type DiagnosticSummary, computeDiagnosticSummary, filterByPathClass } from './diagnosticSummary.js';

export interface PythonDiagnosticsOptions extends EnvironmentSnapshotOptions {
  files?: string[];
  cwd?: string;
  limit?: number;
  pathFilter?: 'source' | 'tests' | 'all';
}

export interface PythonDiagnostic {
  source: 'ruff' | 'ty';
  severity: 'error' | 'warning' | 'information' | 'hint' | 'unknown';
  nativeSeverity?: string;
  code?: string;
  message: string;
  file?: string;
  startLine?: number;
  startColumn?: number;
  endLine?: number;
  endColumn?: number;
  fixable?: boolean;
  fingerprint?: string;
  url?: string;
  typeInfo?: PythonTypeInfo;
  diagnosticContext?: PythonDiagnosticContext;
}

export interface PythonDiagnosticsBackendStatus {
  name: 'ruff' | 'ty';
  status: 'complete' | 'failed' | 'unavailable' | 'not-implemented';
  available: boolean;
  resolution?: string;
  diagnosticCount: number;
  error?: string;
}

export interface PythonDiagnosticsResult {
  generatedAt: string;
  status: 'complete' | 'failed';
  workspaceFolder?: string;
  cwd?: string;
  files?: string[];
  pathFilter?: 'source' | 'tests' | 'all';
  limit?: number;
  truncated: boolean;
  totalDiagnostics: number;
  summary: DiagnosticSummary;
  diagnostics: PythonDiagnostic[];
  backends: {
    ruff: PythonDiagnosticsBackendStatus;
    ty: PythonDiagnosticsBackendStatus;
  };
}

interface RuffDiagnosticPayload {
  code?: string;
  message?: string;
  filename?: string;
  location?: {
    row?: number;
    column?: number;
  };
  end_location?: {
    row?: number;
    column?: number;
  };
  fix?: unknown;
  url?: string;
}

export class PythonDiagnosticsService {
  constructor(
    private readonly environmentSnapshotService: Pick<EnvironmentSnapshotService, 'getSnapshot'>,
    private readonly ruffRunnerService: Pick<RuffRunnerService, 'runCheck'>,
    private readonly tyRunnerService: Pick<TyRunnerService, 'runCheck'>,
  ) {}

  async getDiagnostics(options: PythonDiagnosticsOptions = {}): Promise<PythonDiagnosticsResult> {
    const snapshot = await this.environmentSnapshotService.getSnapshot(options);
    const [ruffResult, tyResult] = await Promise.all([
      this.ruffRunnerService.runCheck(this._toRuffOptions(options)),
      this.tyRunnerService.runCheck(this._toTyOptions(options)),
    ]);
    const normalizedRuffDiagnostics = this._normalizeRuffDiagnostics(ruffResult);
    const normalizedTyDiagnostics = this._normalizeTyDiagnostics(tyResult);
    const combinedDiagnostics = [...normalizedTyDiagnostics, ...normalizedRuffDiagnostics];
    const pathFilter = options.pathFilter ?? 'all';
    const filteredDiagnostics = filterByPathClass(combinedDiagnostics, pathFilter);
    const summary = computeDiagnosticSummary(filteredDiagnostics);
    const limit = this._normalizeLimit(options.limit);
    const diagnostics = limit == null ? filteredDiagnostics : filteredDiagnostics.slice(0, limit);
    const tyStatus: PythonDiagnosticsBackendStatus = {
      name: 'ty',
      status: this._mapTyStatus(tyResult),
      available: snapshot.ty.available,
      resolution: snapshot.ty.resolution,
      diagnosticCount: normalizedTyDiagnostics.length,
      error: tyResult.error,
    };
    const ruffStatus: PythonDiagnosticsBackendStatus = {
      name: 'ruff',
      status: this._mapRuffStatus(ruffResult),
      available: snapshot.ruff.available,
      resolution: snapshot.ruff.resolution,
      diagnosticCount: normalizedRuffDiagnostics.length,
      error: ruffResult.error,
    };

    return {
      generatedAt: new Date().toISOString(),
      status: this._mapOverallStatus(ruffStatus, tyStatus),
      workspaceFolder: snapshot.workspaceFolder,
      cwd: options.cwd ?? options.workspaceFolder?.uri.fsPath ?? snapshot.workspaceFolder,
      files: options.files,
      pathFilter: pathFilter !== 'all' ? pathFilter : undefined,
      limit,
      truncated: diagnostics.length < filteredDiagnostics.length,
      totalDiagnostics: filteredDiagnostics.length,
      summary,
      diagnostics,
      backends: {
        ruff: ruffStatus,
        ty: tyStatus,
      },
    };
  }

  private _toRuffOptions(options: PythonDiagnosticsOptions): RuffCheckOptions {
    return {
      workspaceFolder: options.workspaceFolder,
      searchRootPath: options.searchRootPath,
      files: options.files,
      cwd: options.cwd,
    };
  }

  private _toTyOptions(options: PythonDiagnosticsOptions): EnvironmentSnapshotOptions & { files?: string[]; cwd?: string } {
    return {
      workspaceFolder: options.workspaceFolder,
      searchRootPath: options.searchRootPath,
      files: options.files,
      cwd: options.cwd,
    };
  }

  private _normalizeRuffDiagnostics(result: RuffCheckResult): PythonDiagnostic[] {
    return result.diagnostics
      .map(item => this._normalizeRuffDiagnostic(item as RuffDiagnosticPayload))
      .filter((item): item is PythonDiagnostic => item !== undefined);
  }

  private _normalizeTyDiagnostics(result: TyCheckResult): PythonDiagnostic[] {
    return result.diagnostics
      .map(item => this._normalizeTyDiagnostic(item as TyDiagnosticPayload))
      .filter((item): item is PythonDiagnostic => item !== undefined);
  }

  private _normalizeRuffDiagnostic(item: RuffDiagnosticPayload): PythonDiagnostic | undefined {
    if (!item || typeof item.message !== 'string') {
      return undefined;
    }

    return {
      source: 'ruff',
      severity: 'warning',
      nativeSeverity: 'warning',
      code: item.code,
      message: item.message,
      file: item.filename,
      startLine: item.location?.row,
      startColumn: item.location?.column,
      endLine: item.end_location?.row,
      endColumn: item.end_location?.column,
      fixable: item.fix != null,
      url: item.url,
    };
  }

  private _normalizeTyDiagnostic(item: TyDiagnosticPayload): PythonDiagnostic | undefined {
    if (!item || typeof item.description !== 'string') {
      return undefined;
    }

    return {
      source: 'ty',
      severity: this._mapTySeverity(item.severity),
      nativeSeverity: item.severity,
      code: item.check_name,
      message: item.description,
      file: item.location?.path,
      startLine: item.location?.lines?.begin ?? item.location?.positions?.begin?.line,
      startColumn: item.location?.positions?.begin?.column,
      endLine: item.location?.lines?.end ?? item.location?.positions?.end?.line,
      endColumn: item.location?.positions?.end?.column,
      fingerprint: item.fingerprint,
    };
  }

  private _mapRuffStatus(result: RuffCheckResult): PythonDiagnosticsBackendStatus['status'] {
    if (result.status === 'failed') {
      return result.resolution === 'none' ? 'unavailable' : 'failed';
    }
    return 'complete';
  }

  private _mapTyStatus(result: TyCheckResult): PythonDiagnosticsBackendStatus['status'] {
    if (result.status === 'failed') {
      return result.resolution === 'none' ? 'unavailable' : 'failed';
    }
    return 'complete';
  }

  private _mapOverallStatus(
    ruffStatus: PythonDiagnosticsBackendStatus,
    tyStatus: PythonDiagnosticsBackendStatus,
  ): PythonDiagnosticsResult['status'] {
    if (ruffStatus.status === 'complete' || tyStatus.status === 'complete') {
      return 'complete';
    }
    return 'failed';
  }

  private _mapTySeverity(severity: string | undefined): PythonDiagnostic['severity'] {
    switch (severity) {
      case 'blocker':
      case 'critical':
      case 'error':
        return 'error';
      case 'major':
      case 'minor':
      case 'warning':
        return 'warning';
      case 'info':
        return 'information';
      case 'hint':
        return 'hint';
      default:
        return 'unknown';
    }
  }

  private _normalizeLimit(value: number | undefined): number | undefined {
    if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) {
      return undefined;
    }
    return Math.floor(value);
  }
}

interface TyDiagnosticPayload {
  description?: string;
  check_name?: string;
  fingerprint?: string;
  severity?: string;
  location?: {
    path?: string;
    lines?: {
      begin?: number;
      end?: number;
    };
    positions?: {
      begin?: {
        line?: number;
        column?: number;
      };
      end?: {
        line?: number;
        column?: number;
      };
    };
  };
}