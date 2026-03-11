import * as os from 'os';
import { join as pathJoin } from 'path';
import { describe, expect, it } from 'vitest';
import { buildDefaultLogFilePath, formatLogTimestamp } from '../src/debugAdapter/logFileNaming.js';

describe('logFileNaming', () => {
  it('formats timestamps for log filenames using a filesystem-safe layout', () => {
    const timestamp = formatLogTimestamp(new Date(2026, 2, 7, 18, 45, 27, 12));
    expect(timestamp).toBe('20260307-184527-012');
  });

  it('builds the default debug log filename with a timestamp and token', () => {
    const filePath = buildDefaultLogFilePath('debug', 'session-123', new Date(2026, 2, 7, 18, 45, 27, 12));
    // we don't know the pid until runtime; just confirm the pattern at the
    // appropriate location and that the rest of the filename is correct.
    const expectedBase = `dapper-debug-20260307-184527-012-`;
    expect(filePath.startsWith(pathJoin(os.tmpdir(), expectedBase))).toBe(true);
    expect(filePath.endsWith(`-session-123.log`)).toBe(true);
  });

  it('builds the default run log filename with a timestamp and token', () => {
    const filePath = buildDefaultLogFilePath('run', 'run-abc', new Date(2026, 2, 7, 18, 45, 27, 12));
    const expectedBase = `dapper-run-20260307-184527-012-`;
    expect(filePath.startsWith(pathJoin(os.tmpdir(), expectedBase))).toBe(true);
    expect(filePath.endsWith(`-run-abc.log`)).toBe(true);
  });
});