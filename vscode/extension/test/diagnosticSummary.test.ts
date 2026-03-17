import { describe, expect, it } from 'vitest';

import { computeDiagnosticSummary, filterByPathClass, isTestPath } from '../src/python/diagnosticSummary.js';
import type { PythonDiagnostic } from '../src/python/diagnostics.js';

function diag(overrides: Partial<PythonDiagnostic> = {}): PythonDiagnostic {
  return {
    source: 'ty',
    severity: 'warning',
    message: 'test message',
    ...overrides,
  };
}

describe('computeDiagnosticSummary', () => {
  it('groups counts by file, code, and severity', () => {
    const diagnostics: PythonDiagnostic[] = [
      diag({ file: 'a.py', code: 'E001', severity: 'error' }),
      diag({ file: 'a.py', code: 'E001', severity: 'error' }),
      diag({ file: 'a.py', code: 'E002', severity: 'warning' }),
      diag({ file: 'b.py', code: 'E001', severity: 'error' }),
    ];

    const summary = computeDiagnosticSummary(diagnostics);

    expect(summary.countsByFile).toEqual({ 'a.py': 3, 'b.py': 1 });
    expect(summary.countsByCode).toEqual({ 'E001': 3, 'E002': 1 });
    expect(summary.countsBySeverity).toEqual({ error: 3, warning: 1 });
  });

  it('produces hotspots sorted by descending count', () => {
    const diagnostics: PythonDiagnostic[] = [
      diag({ file: 'a.py', code: 'E001', startLine: 10 }),
      diag({ file: 'a.py', code: 'E001', startLine: 20 }),
      diag({ file: 'a.py', code: 'E001', startLine: 10 }),
      diag({ file: 'b.py', code: 'E002', startLine: 5 }),
    ];

    const summary = computeDiagnosticSummary(diagnostics);

    expect(summary.hotspots[0]).toEqual(expect.objectContaining({
      file: 'a.py',
      code: 'E001',
      count: 3,
      lines: [10, 20],
    }));
    expect(summary.hotspots[1]).toEqual(expect.objectContaining({
      file: 'b.py',
      code: 'E002',
      count: 1,
    }));
  });

  it('limits hotspots to maxHotspots', () => {
    const diagnostics = Array.from({ length: 20 }, (_, i) =>
      diag({ file: `file${i}.py`, code: `E${i}` }),
    );

    const summary = computeDiagnosticSummary(diagnostics, 5);
    expect(summary.hotspots).toHaveLength(5);
  });

  it('handles diagnostics with missing file and code', () => {
    const diagnostics: PythonDiagnostic[] = [
      diag({ file: undefined, code: undefined }),
    ];

    const summary = computeDiagnosticSummary(diagnostics);

    expect(summary.countsByFile).toEqual({ '<unknown>': 1 });
    expect(summary.countsByCode).toEqual({ '<unknown>': 1 });
  });

  it('returns empty summary for no diagnostics', () => {
    const summary = computeDiagnosticSummary([]);

    expect(summary.countsByFile).toEqual({});
    expect(summary.countsByCode).toEqual({});
    expect(summary.countsBySeverity).toEqual({});
    expect(summary.hotspots).toEqual([]);
  });
});

describe('isTestPath', () => {
  it.each([
    ['tests/test_foo.py', true],
    ['test/unit/test_bar.py', true],
    ['testing/helpers.py', true],
    ['src/test_module.py', true],
    ['src/module_test.py', true],
    ['tests/conftest.py', true],
    ['src/app.py', false],
    ['dapper/core/engine.py', false],
    ['dapper/utils/helpers.py', false],
  ])('isTestPath(%s) = %s', (path, expected) => {
    expect(isTestPath(path)).toBe(expected);
  });
});

describe('filterByPathClass', () => {
  const sourceDiag = diag({ file: 'src/app.py' });
  const testDiag = diag({ file: 'tests/test_app.py' });
  const noFileDiag = diag({ file: undefined });
  const all = [sourceDiag, testDiag, noFileDiag];

  it('returns all diagnostics for pathFilter=all', () => {
    expect(filterByPathClass(all, 'all')).toEqual(all);
  });

  it('returns only source diagnostics for pathFilter=source', () => {
    const result = filterByPathClass(all, 'source');
    expect(result).toEqual([sourceDiag, noFileDiag]);
  });

  it('returns only test diagnostics for pathFilter=tests', () => {
    const result = filterByPathClass(all, 'tests');
    expect(result).toEqual([testDiag]);
  });
});
