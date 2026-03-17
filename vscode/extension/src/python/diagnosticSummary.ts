import type { PythonDiagnostic } from './diagnostics.js';

export interface DiagnosticSummary {
  countsByFile: Record<string, number>;
  countsByCode: Record<string, number>;
  countsBySeverity: Record<string, number>;
  hotspots: DiagnosticHotspot[];
}

export interface DiagnosticHotspot {
  file: string;
  code: string;
  count: number;
  lines: number[];
  message: string;
}

/**
 * Compute grouped summary statistics for an array of normalized diagnostics.
 * Hotspots are (file, code) pairs sorted by descending count.
 */
export function computeDiagnosticSummary(diagnostics: PythonDiagnostic[], maxHotspots = 15): DiagnosticSummary {
  const countsByFile: Record<string, number> = {};
  const countsByCode: Record<string, number> = {};
  const countsBySeverity: Record<string, number> = {};
  const hotspotMap = new Map<string, { file: string; code: string; count: number; lines: Set<number>; message: string }>();

  for (const d of diagnostics) {
    const file = d.file ?? '<unknown>';
    const code = d.code ?? '<unknown>';

    countsByFile[file] = (countsByFile[file] ?? 0) + 1;
    countsByCode[code] = (countsByCode[code] ?? 0) + 1;
    countsBySeverity[d.severity] = (countsBySeverity[d.severity] ?? 0) + 1;

    const key = `${file}\0${code}`;
    const existing = hotspotMap.get(key);
    if (existing) {
      existing.count++;
      if (d.startLine != null) existing.lines.add(d.startLine);
    } else {
      hotspotMap.set(key, {
        file,
        code,
        count: 1,
        lines: d.startLine != null ? new Set([d.startLine]) : new Set(),
        message: d.message,
      });
    }
  }

  const hotspots = Array.from(hotspotMap.values())
    .sort((a, b) => b.count - a.count)
    .slice(0, maxHotspots)
    .map(h => ({
      file: h.file,
      code: h.code,
      count: h.count,
      lines: Array.from(h.lines).sort((a, b) => a - b),
      message: h.message,
    }));

  return { countsByFile, countsByCode, countsBySeverity, hotspots };
}

/**
 * Test whether a file path looks like a test file or is under a test directory.
 */
export function isTestPath(filePath: string): boolean {
  const normalized = filePath.replace(/\\/g, '/');
  if (/(?:^|\/)(tests?|testing)\//.test(normalized)) return true;
  const basename = normalized.split('/').pop() ?? '';
  if (/^test_/.test(basename) || /_test\.py$/.test(basename) || basename === 'conftest.py') return true;
  return false;
}

/**
 * Filter diagnostics by path class: source code, test code, or all.
 */
export function filterByPathClass(diagnostics: PythonDiagnostic[], pathFilter: 'source' | 'tests' | 'all'): PythonDiagnostic[] {
  if (pathFilter === 'all') return diagnostics;
  return diagnostics.filter(d => {
    if (!d.file) return pathFilter === 'source';
    const isTest = isTestPath(d.file);
    return pathFilter === 'tests' ? isTest : !isTest;
  });
}
