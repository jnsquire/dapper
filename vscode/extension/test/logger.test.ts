import { describe, it, expect, vi, beforeEach } from 'vitest';
import { Logger } from '../src/utils/logger.js';

// Access the vscode mock to customize behaviour per-test
import * as vscode from 'vscode';

describe('Logger', () => {
let debugSpy: ReturnType<typeof vi.fn>;
    let infoSpy: ReturnType<typeof vi.fn>;
    let warnSpy: ReturnType<typeof vi.fn>;
    let errorSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    // Reset the singleton so each test gets a fresh Logger
    (Logger as any)['instance'] = undefined;
    (Logger as any)['outputChannel'] = undefined;
    (Logger as any)['logLevel'] = 'info';
    (Logger as any)['logToConsole'] = false;

    // Patch createOutputChannel to return a fake LogOutputChannel with spies
    debugSpy = vi.fn();
    infoSpy = vi.fn();
    warnSpy = vi.fn();
    errorSpy = vi.fn();
    vi.spyOn(vscode.window, 'createOutputChannel').mockReturnValue({
      debug: debugSpy,
      info: infoSpy,
      warn: warnSpy,
      error: errorSpy,
      show: vi.fn(),
      dispose: vi.fn(),
    } as any);
  });

  it('should create an output channel', () => {
    const logger = Logger.getInstance();
    expect(vscode.window.createOutputChannel).toHaveBeenCalledWith('Dapper Debugger', { log: true });
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

    const allMessages = [
      ...debugSpy.mock.calls.map(c => c[0]),
      ...infoSpy.mock.calls.map(c => c[0]),
      ...warnSpy.mock.calls.map(c => c[0]),
      ...errorSpy.mock.calls.map(c => c[0]),
    ];
    expect(allMessages.some(m => m.includes('DEBUG'))).toBe(true);
    expect(allMessages.some(m => m.includes('INFO'))).toBe(true);
    expect(allMessages.some(m => m.includes('WARN'))).toBe(true);
    expect(allMessages.some(m => m.includes('ERROR'))).toBe(true);
  });

  it('should respect log levels - error level only logs errors', () => {
    const logger = Logger.getInstance();
    (Logger as any)['logLevel'] = 'error';

    debugSpy.mockClear();
    infoSpy.mockClear();
    warnSpy.mockClear();
    errorSpy.mockClear();

    logger.debug('d');
    logger.log('l');
    logger.warn('w');

    expect(debugSpy).not.toHaveBeenCalled();
    expect(infoSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();

    logger.error('e');
    const errorMsgs = errorSpy.mock.calls.map(c => c[0]);
    expect(errorMsgs.some(m => m.includes('ERROR'))).toBe(true);
  });

  it('should log error stack traces when Error is passed', () => {
    const logger = Logger.getInstance();
    (Logger as any)['logLevel'] = 'error';
    errorSpy.mockClear();

    const err = new Error('boom');
    logger.error('something failed', err);

    const msgs = errorSpy.mock.calls.map(c => c[0]);
    expect(msgs.some(m => m.includes('boom'))).toBe(true);
    expect(msgs.some(m => m.includes('Error'))).toBe(true);
  });

  it('should log objects as JSON', () => {
    const logger = Logger.getInstance();
    (Logger as any)['logLevel'] = 'debug';
    debugSpy.mockClear();

    const data = { key: 'value', nested: { a: 1 } };
    logger.debug('obj test', data);

    const calls = debugSpy.mock.calls.map((c: any[]) => c[0] as string);
    expect(calls.some(m => m.includes('"key"'))).toBe(true);
    expect(calls.some(m => m.includes('"value"'))).toBe(true);
  });

  it('should handle circular references gracefully in log data', () => {
    const logger = Logger.getInstance();
    (Logger as any)['logLevel'] = 'debug';
    debugSpy.mockClear();

    const circular: any = { a: 1 };
    circular.self = circular;

    // Should not throw
    expect(() => logger.debug('circular', circular)).not.toThrow();

    // Should have logged something (falls back to String(data))
    expect(debugSpy).toHaveBeenCalled();
  });
});
