import { describe, it, expect } from 'vitest';
import { validateConfig, sanitizeConfig, mergeWithDefaults, defaultConfig } from '../src/webview/utils/configValidation.js';
import type { DebugConfiguration } from '../src/webview/types/debug.js';

function makeValidConfig(overrides: Partial<DebugConfiguration> = {}): DebugConfiguration {
  return {
    name: 'Test Config',
    type: 'dapper',
    request: 'launch',
    program: 'main.py',
    args: [],
    cwd: '/workspace',
    debugServer: 4711,
    useIpc: true,
    ipcTransport: 'pipe',
    frameEval: true,
    inProcess: false,
    stopOnEntry: true,
    justMyCode: true,
    ...overrides,
  } as DebugConfiguration;
}

describe('validateConfig', () => {
  it('should pass validation with valid config', () => {
    const result = validateConfig(makeValidConfig());
    expect(result.valid).toBe(true);
    expect(result.errors).toHaveLength(0);
  });

  it('should fail when name is missing', () => {
    const result = validateConfig(makeValidConfig({ name: undefined as any }));
    expect(result.valid).toBe(false);
    expect(result.errors).toContain('Configuration name is required');
  });

  it('should fail when name is whitespace only', () => {
    const result = validateConfig(makeValidConfig({ name: '   ' }));
    expect(result.valid).toBe(false);
    expect(result.errors).toContain('Configuration name is required');
  });

  it('should fail when both program and module are missing', () => {
    const result = validateConfig(makeValidConfig({ program: undefined as any }));
    expect(result.valid).toBe(false);
    expect(result.errors).toContain('Program path or module name is required');
  });

  it('should fail when program and module are empty strings', () => {
    const result = validateConfig(makeValidConfig({ program: '' }));
    expect(result.valid).toBe(false);
    expect(result.errors).toContain('Program path or module name is required');
  });

  it('should pass when module is provided without program', () => {
    const result = validateConfig(makeValidConfig({ program: undefined as any, module: 'pkg.main' }));
    expect(result.valid).toBe(true);
    expect(result.errors).toHaveLength(0);
  });

  it('should fail when subProcess is true but subProcessName is missing', () => {
    const result = validateConfig(makeValidConfig({ subProcess: true }));
    expect(result.valid).toBe(false);
    expect(result.errors).toContain('Subprocess name is required when subprocess debugging is enabled');
  });

  it('should fail when useIpc is true but ipcTransport is missing', () => {
    const result = validateConfig(makeValidConfig({ useIpc: true, ipcTransport: undefined as any }));
    expect(result.valid).toBe(false);
    expect(result.errors).toContain('IPC transport method is required when using IPC');
  });

  it('should return multiple errors at once', () => {
    const result = validateConfig({ } as any);
    expect(result.valid).toBe(false);
    expect(result.errors.length).toBeGreaterThanOrEqual(2);
    expect(result.errors).toContain('Configuration name is required');
    expect(result.errors).toContain('Program path or module name is required');
  });

  it('should pass when subProcess is false even without subProcessName', () => {
    const result = validateConfig(makeValidConfig({ subProcess: false }));
    expect(result.valid).toBe(true);
    expect(result.errors).toHaveLength(0);
  });
});

describe('sanitizeConfig', () => {
  it('should remove undefined and null values', () => {
    const config = makeValidConfig({ pythonPath: undefined, env: null as any });
    const result = sanitizeConfig(config);
    expect(result).not.toHaveProperty('pythonPath');
    expect(result).not.toHaveProperty('env');
  });

  it('should keep empty strings', () => {
    const config = makeValidConfig({ name: '' });
    const result = sanitizeConfig(config);
    expect(result.name).toBe('');
  });

  it('should initialize args array when not present', () => {
    const config = makeValidConfig({ args: undefined as any });
    const result = sanitizeConfig(config);
    expect(Array.isArray(result.args)).toBe(true);
    expect(result.args).toEqual([]);
  });

  it('should initialize debugOptions array when not present', () => {
    const config = makeValidConfig({ debugOptions: undefined as any });
    const result = sanitizeConfig(config);
    expect(Array.isArray(result.debugOptions)).toBe(true);
    expect(result.debugOptions).toEqual([]);
  });

  it('should initialize subProcess arrays when subProcess is true', () => {
    const config = makeValidConfig({ subProcess: true });
    const result = sanitizeConfig(config);
    expect(Array.isArray(result.subProcessArgs)).toBe(true);
    expect(Array.isArray(result.subProcessDebugOptions)).toBe(true);
  });

  it('should always set type to dapper', () => {
    const config = makeValidConfig({ type: 'other' as any });
    const result = sanitizeConfig(config);
    expect(result.type).toBe('dapper');
  });

  it('should not mutate the original object', () => {
    const config = makeValidConfig({ type: 'other' as any });
    const originalName = config.name;
    sanitizeConfig(config);
    expect(config.type).toBe('other');
    expect(config.name).toBe(originalName);
  });

  it('should deep copy the config', () => {
    const config = makeValidConfig({ args: ['--verbose'] });
    const result = sanitizeConfig(config);
    result.args.push('--extra');
    expect(config.args).toEqual(['--verbose']);
  });
});

describe('mergeWithDefaults', () => {
  it('should fill all defaults when given empty config', () => {
    const result = mergeWithDefaults({});
    expect(result.type).toBe(defaultConfig.type);
    expect(result.request).toBe(defaultConfig.request);
    expect(result.program).toBe(defaultConfig.program);
    expect(result.cwd).toBe(defaultConfig.cwd);
    expect(result.debugServer).toBe(defaultConfig.debugServer);
    expect(result.useIpc).toBe(defaultConfig.useIpc);
    expect(result.ipcTransport).toBe(defaultConfig.ipcTransport);
    expect(result.frameEval).toBe(defaultConfig.frameEval);
    expect(result.inProcess).toBe(defaultConfig.inProcess);
    expect(result.stopOnEntry).toBe(defaultConfig.stopOnEntry);
    expect(result.justMyCode).toBe(defaultConfig.justMyCode);
  });

  it('should use provided name over default', () => {
    const result = mergeWithDefaults({ name: 'My Config' });
    expect(result.name).toBe('My Config');
  });

  it('should default name to "Dapper Debug" when not provided', () => {
    const result = mergeWithDefaults({});
    expect(result.name).toBe('Dapper Debug');
  });

  it('should trim whitespace from name', () => {
    const result = mergeWithDefaults({ name: '  My Config  ' });
    expect(result.name).toBe('My Config');
  });

  it('should merge env objects', () => {
    const result = mergeWithDefaults({ env: { MY_VAR: 'value' } });
    expect(result.env).toEqual({ MY_VAR: 'value' });
  });

  it('should merge debugOptions arrays', () => {
    const result = mergeWithDefaults({ debugOptions: ['RedirectOutput'] });
    expect(result.debugOptions).toContain('RedirectOutput');
  });

  it('should handle subprocess defaults when subProcess is true', () => {
    const result = mergeWithDefaults({ subProcess: true, subProcessArgs: ['--child'] });
    expect(result.subProcessArgs).toContain('--child');
    expect(result.subProcessEnv).toBeDefined();
    expect(result.subProcessDebugOptions).toBeDefined();
  });

  it('should not add subprocess fields when subProcess is false', () => {
    const result = mergeWithDefaults({ subProcess: false });
    expect(result.subProcessEnv).toBeUndefined();
    expect(result.subProcessArgs).toBeUndefined();
    expect(result.subProcessDebugOptions).toBeUndefined();
  });
});
