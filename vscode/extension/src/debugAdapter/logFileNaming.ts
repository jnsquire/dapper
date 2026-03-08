import * as os from 'os';
import { join as pathJoin } from 'path';

function pad2(value: number): string {
  return String(value).padStart(2, '0');
}

function pad3(value: number): string {
  return String(value).padStart(3, '0');
}

export function formatLogTimestamp(date: Date): string {
  return [
    date.getFullYear(),
    pad2(date.getMonth() + 1),
    pad2(date.getDate()),
    '-',
    pad2(date.getHours()),
    pad2(date.getMinutes()),
    pad2(date.getSeconds()),
    '-',
    pad3(date.getMilliseconds()),
  ].join('');
}

export function buildDefaultLogFilePath(
  mode: 'debug' | 'run',
  runToken: string,
  date: Date = new Date(),
): string {
  const timestamp = formatLogTimestamp(date);
  return pathJoin(os.tmpdir(), `dapper-${mode}-${timestamp}-${runToken}.log`);
}