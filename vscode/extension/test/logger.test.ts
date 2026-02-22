import { describe, it, expect, vi, beforeEach } from 'vitest';
import { Logger } from '../src/utils/logger.js';

// Access the vscode mock to customize behaviour per-test
import * as vscode from 'vscode';

describe('Logger', () => {
  let appendLineSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    // Reset the singleton so each test gets a fresh Logger
    (Logger as any)['instance'] = undefined;
    (Logger as any)['outputChannel'] = undefined;
    (Logger as any)['logLevel'] = 'info';
    (Logger as any)['logToConsole'] = false;

    // Patch createOutputChannel to return an object with a spy on appendLine
    appendLineSpy = vi.fn();
    vi.spyOn(vscode.window, 'createOutputChannel').mockReturnValue({
      appendLine: appendLineSpy,
      show: vi.fn(),
      dispose: vi.fn(),
    } as any);
  });

  it('should create an output channel', () => {
    const logger = Logger.getInstance();
    expect(vscode.window.createOutputChannel).toHaveBeenCalledWith('Dapper Debugger');
    expect((Logger as any)['outputChannel']).toBeDefined();
  });

  it('should be a singleton', () => {
    const a = Logger.getInstance();
    const b = Logger.getInstance();
    expect(a).toBe(b);
  });

  it('should respect log levels - debug level logs everything', () => {
    const logger = Logger.getInstance();
    // Force debug level
    (Logger as any)['logLevel'] = 'debug';

    logger.debug('d');
    logger.log('l');
    logger.warn('w');
    logger.error('e');

    // Each method produces at least one appendLine call for the message line
    const calls = appendLineSpy.mock.calls.map((c: any[]) => c[0] as string);
    expect(calls.some((m: string) => m.includes('DEBUG'))).toBe(true);
    expect(calls.some((m: string) => m.includes('INFO'))).toBe(true);
    expect(calls.some((m: string) => m.includes('WARN'))).toBe(true);
    expect(calls.some((m: string) => m.includes('ERROR'))).toBe(true);
  });

  it('should respect log levels - error level only logs errors', () => {
    const logger = Logger.getInstance();
    (Logger as any)['logLevel'] = 'error';

    appendLineSpy.mockClear();

    logger.debug('d');
    logger.log('l');
    logger.warn('w');

    const callsBefore = appendLineSpy.mock.calls.length;
    expect(callsBefore).toBe(0);

    logger.error('e');
    const calls = appendLineSpy.mock.calls.map((c: any[]) => c[0] as string);
    expect(calls.some((m: string) => m.includes('ERROR'))).toBe(true);
  });

  it('should log error stack traces when Error is passed', () => {
    const logger = Logger.getInstance();
    (Logger as any)['logLevel'] = 'error';
    appendLineSpy.mockClear();

    const err = new Error('boom');
    logger.error('something failed', err);

    const calls = appendLineSpy.mock.calls.map((c: any[]) => c[0] as string);
    // The error's toString and stack should both be logged
    expect(calls.some((m: string) => m.includes('boom'))).toBe(true);
    expect(calls.some((m: string) => m.includes('Error'))).toBe(true);
  });

  it('should log objects as JSON', () => {
    const logger = Logger.getInstance();
    (Logger as any)['logLevel'] = 'debug';
    appendLineSpy.mockClear();

    const data = { key: 'value', nested: { a: 1 } };
    logger.debug('obj test', data);

    const calls = appendLineSpy.mock.calls.map((c: any[]) => c[0] as string);
    // The JSON stringified version should appear
    expect(calls.some((m: string) => m.includes('"key"'))).toBe(true);
    expect(calls.some((m: string) => m.includes('"value"'))).toBe(true);
  });

  it('should handle circular references gracefully in log data', () => {
    const logger = Logger.getInstance();
    (Logger as any)['logLevel'] = 'debug';
    appendLineSpy.mockClear();

    const circular: any = { a: 1 };
    circular.self = circular;

    // Should not throw
    expect(() => logger.debug('circular', circular)).not.toThrow();

    // Should have logged something (falls back to String(data))
    expect(appendLineSpy).toHaveBeenCalled();
  });
});
