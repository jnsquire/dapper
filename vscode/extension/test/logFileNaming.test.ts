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
    expect(filePath).toBe(pathJoin(os.tmpdir(), 'dapper-debug-20260307-184527-012-session-123.log'));
  });

  it('builds the default run log filename with a timestamp and token', () => {
    const filePath = buildDefaultLogFilePath('run', 'run-abc', new Date(2026, 2, 7, 18, 45, 27, 12));
    expect(filePath).toBe(pathJoin(os.tmpdir(), 'dapper-run-20260307-184527-012-run-abc.log'));
  });
});