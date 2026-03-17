import type { EnvironmentSnapshotOptions, EnvironmentSnapshotService } from './environmentSnapshot.js';
import type { PythonDiagnostic, PythonDiagnosticsBackendStatus } from './diagnostics.js';
import type { TyCheckResult, TyRunnerService } from './tyRunner.js';
import { type DiagnosticSummary, computeDiagnosticSummary, filterByPathClass } from './diagnosticSummary.js';

export interface PythonTypecheckOptions extends EnvironmentSnapshotOptions {
  files?: string[];
  cwd?: string;
  limit?: number;
  pathFilter?: 'source' | 'tests' | 'all';
}

export interface PythonTypecheckResult {
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
  backend: PythonDiagnosticsBackendStatus;
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

export class PythonTypecheckService {
  constructor(
    private readonly environmentSnapshotService: Pick<EnvironmentSnapshotService, 'getSnapshot'>,
    private readonly tyRunnerService: Pick<TyRunnerService, 'runCheck'>,
  ) {}

  async getTypecheck(options: PythonTypecheckOptions = {}): Promise<PythonTypecheckResult> {
    const snapshot = await this.environmentSnapshotService.getSnapshot(options);
    const tyResult = await this.tyRunnerService.runCheck(options);
    const allDiagnostics = this._normalizeTyDiagnostics(tyResult);
    const pathFilter = options.pathFilter ?? 'all';
    const filteredDiagnostics = filterByPathClass(allDiagnostics, pathFilter);
    const summary = computeDiagnosticSummary(filteredDiagnostics);
    const limit = this._normalizeLimit(options.limit);
    const diagnostics = limit == null ? filteredDiagnostics : filteredDiagnostics.slice(0, limit);
    const backend: PythonDiagnosticsBackendStatus = {
      name: 'ty',
      status: this._mapTyStatus(tyResult),
      available: snapshot.ty.available,
      resolution: snapshot.ty.resolution,
      diagnosticCount: allDiagnostics.length,
      error: tyResult.error,
    };

    return {
      generatedAt: new Date().toISOString(),
      status: backend.status === 'complete' ? 'complete' : 'failed',
      workspaceFolder: snapshot.workspaceFolder,
      cwd: options.cwd ?? options.searchRootPath ?? options.workspaceFolder?.uri.fsPath ?? snapshot.workspaceFolder,
      files: options.files,
      pathFilter: pathFilter !== 'all' ? pathFilter : undefined,
      limit,
      truncated: diagnostics.length < filteredDiagnostics.length,
      totalDiagnostics: filteredDiagnostics.length,
      summary,
      diagnostics,
      backend,
    };
  }

  private _normalizeTyDiagnostics(result: TyCheckResult): PythonDiagnostic[] {
    return result.diagnostics
      .map(item => this._normalizeTyDiagnostic(item as TyDiagnosticPayload))
      .filter((item): item is PythonDiagnostic => item !== undefined);
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

  private _mapTyStatus(result: TyCheckResult): PythonDiagnosticsBackendStatus['status'] {
    if (result.status === 'failed') {
      return result.resolution === 'none' ? 'unavailable' : 'failed';
    }
    return 'complete';
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