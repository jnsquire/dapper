import type { EnvironmentSnapshotOptions, EnvironmentSnapshotService } from './environmentSnapshot.js';
import type { PythonDiagnostic, PythonDiagnosticsBackendStatus } from './diagnostics.js';
import type {
  PythonDiagnosticContext,
  PythonOutputBudget,
  PythonRelatedLocation,
  PythonToolCompletionStatus,
  PythonTypeInfo,
} from './semanticPayloads.js';
import type { TyCheckResult, TyRunnerService } from './tyRunner.js';
import { type DiagnosticSummary, computeDiagnosticSummary, filterByPathClass } from './diagnosticSummary.js';

export interface PythonTypecheckOptions extends EnvironmentSnapshotOptions {
  files?: string[];
  cwd?: string;
  limit?: number;
  offset?: number;
  pathFilter?: 'source' | 'tests' | 'all';
}

export interface PythonTypecheckResult {
  generatedAt: string;
  status: 'complete' | 'failed';
  completionStatus: PythonToolCompletionStatus;
  workspaceFolder?: string;
  cwd?: string;
  files?: string[];
  pathFilter?: 'source' | 'tests' | 'all';
  limit?: number;
  offset?: number;
  truncated: boolean;
  totalDiagnostics: number;
  outputBudget: PythonOutputBudget;
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
    const offset = this._normalizeOffset(options.offset);
    const diagnostics = this._slicePage(filteredDiagnostics, offset, limit);
    const backend: PythonDiagnosticsBackendStatus = {
      name: 'ty',
      status: this._mapTyStatus(tyResult),
      available: snapshot.ty.available,
      resolution: snapshot.ty.resolution,
      diagnosticCount: allDiagnostics.length,
      error: tyResult.error,
    };
    const nextOffset = offset + diagnostics.length;
    const truncated = nextOffset < filteredDiagnostics.length;
    const partial = offset > 0 || truncated;

    return {
      generatedAt: new Date().toISOString(),
      status: backend.status === 'complete' ? 'complete' : 'failed',
      completionStatus: this._mapCompletionStatus(backend.status, partial),
      workspaceFolder: snapshot.workspaceFolder,
      cwd: options.cwd ?? options.searchRootPath ?? options.workspaceFolder?.uri.fsPath ?? snapshot.workspaceFolder,
      files: options.files,
      pathFilter: pathFilter !== 'all' ? pathFilter : undefined,
      limit,
      offset,
      truncated,
      totalDiagnostics: filteredDiagnostics.length,
      outputBudget: {
        requestedLimit: options.limit,
        appliedLimit: limit,
        requestedOffset: options.offset,
        appliedOffset: offset,
        returnedItems: diagnostics.length,
        totalItems: filteredDiagnostics.length,
        truncated,
        nextOffset: truncated ? nextOffset : undefined,
      },
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

    const message = this._normalizeTyMessage(item);

    return {
      source: 'ty',
      severity: this._mapTySeverity(item.severity),
      nativeSeverity: item.severity,
      code: item.check_name,
      message,
      file: item.location?.path,
      startLine: item.location?.positions?.begin?.line,
      startColumn: item.location?.positions?.begin?.column,
      endLine: item.location?.positions?.end?.line,
      endColumn: item.location?.positions?.end?.column,
      fingerprint: item.fingerprint,
      typeInfo: this._normalizeTypeInfo(item, message),
      diagnosticContext: this._normalizeDiagnosticContext(item, message),
    };
  }

  private _normalizeTypeInfo(item: TyDiagnosticPayload, message: string): PythonTypeInfo | undefined {
    const pair = this._extractExpectedFoundTypes(message);
    const declaredType = pair?.expected;
    const inferredType = pair?.found;
    const symbolKind = item.check_name === 'invalid-return-type' ? 'function' : undefined;
    if (!declaredType && !inferredType && !symbolKind) {
      return undefined;
    }

    return {
      declaredType,
      inferredType,
      symbolKind,
      source: 'ty',
    };
  }

  private _normalizeDiagnosticContext(item: TyDiagnosticPayload, message: string): PythonDiagnosticContext | undefined {
    const summary = this._humanizeTyCheckName(item.check_name);
    const explanation = message;
    const code = this._firstString(item.check_name);

    if (!summary && !explanation && !code) {
      return undefined;
    }

    return {
      summary,
      explanation,
      code,
      rule: code,
    };
  }

  private _normalizeTyMessage(item: TyDiagnosticPayload): string {
    const description = item.description?.trim() ?? '';
    const prefix = item.check_name ? `${item.check_name}: ` : undefined;
    if (prefix && description.startsWith(prefix)) {
      return description.slice(prefix.length);
    }
    return description;
  }

  private _extractExpectedFoundTypes(message: string): { expected?: string; found?: string } | undefined {
    const match = /expected `([^`]+)`, found `([^`]+)`/.exec(message);
    if (!match) {
      return undefined;
    }

    return {
      expected: match[1]?.trim(),
      found: match[2]?.trim(),
    };
  }

  private _humanizeTyCheckName(value: string | undefined): string | undefined {
    if (!value) {
      return undefined;
    }

    return value
      .split('-')
      .filter(part => part.length > 0)
      .map(part => part.charAt(0).toUpperCase() + part.slice(1))
      .join(' ');
  }

  private _firstString(...values: unknown[]): string | undefined {
    for (const value of values) {
      if (typeof value === 'string') {
        const trimmed = value.trim();
        if (trimmed.length > 0) {
          return trimmed;
        }
      }
    }
    return undefined;
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

  private _mapCompletionStatus(
    backendStatus: PythonDiagnosticsBackendStatus['status'],
    partial: boolean,
  ): PythonToolCompletionStatus {
    if (backendStatus === 'failed' || backendStatus === 'unavailable' || backendStatus === 'not-implemented') {
      return 'failed';
    }
    return partial ? 'partial' : 'complete';
  }

  private _normalizeLimit(value: number | undefined): number | undefined {
    if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) {
      return undefined;
    }
    return Math.floor(value);
  }

  private _normalizeOffset(value: number | undefined): number {
    if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) {
      return 0;
    }
    return Math.floor(value);
  }

  private _slicePage<T>(items: T[], offset: number, limit: number | undefined): T[] {
    if (limit == null) {
      return items.slice(offset);
    }
    return items.slice(offset, offset + limit);
  }
}